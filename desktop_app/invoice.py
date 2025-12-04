import base64
import hashlib
import hmac
import json
from io import BytesIO
from datetime import datetime
import xml.etree.ElementTree as ET

import qrcode
import requests

from .config import MERCHANT_LOGIN, PASSWORD1, PASSWORD2, TAX
from .paths import INVOICE_DEBUG_LOG

INVOICE_API_URL = "https://services.robokassa.ru/InvoiceServiceWebApi/api/CreateInvoice"
OPSTATE_URL = "https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt"


def log_invoice_debug(header_obj, payload_obj, header_b64, payload_b64, token, body_text, response: requests.Response):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = []
        lines.append("=" * 80)
        lines.append(f"[{ts}] Invoice debug")
        lines.append("=== REQUEST TO INVOICE API ===")
        lines.append("Headers:")
        hdr = {"Content-Type": "application/json; charset=utf-8"}
        lines.append(json.dumps(hdr, ensure_ascii=False, indent=2))
        lines.append("Header JSON:")
        lines.append(json.dumps(header_obj, ensure_ascii=False, indent=2))
        lines.append("Payload JSON:")
        lines.append(json.dumps(payload_obj, ensure_ascii=False, indent=2))
        lines.append("Signing input (header.payload):")
        lines.append(f"{header_b64}.{payload_b64}")
        lines.append("JWT token:")
        lines.append(token)
        lines.append("HTTP body:")
        lines.append(body_text)
        lines.append("")
        lines.append("=" * 80)
        lines.append(f"[{ts}] Invoice debug")
        lines.append("=== RESPONSE (JSON) ===")
        lines.append(f"Status: {response.status_code}")
        try:
            resp_json = response.json()
            lines.append("JSON:")
            lines.append(json.dumps(resp_json, ensure_ascii=False, indent=2))
        except Exception:
            lines.append("Raw text:")
            lines.append(response.text)
        lines.append("")
        with INVOICE_DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def build_invoice_jwt(description: str, amount: float, item_name: str):
    if not MERCHANT_LOGIN or not PASSWORD1:
        raise RuntimeError("Не заданы MerchantLogin / Password1 в настройках Robokassa.")

    header_obj = {
        "typ": "JWT",
        "alg": "MD5",
    }

    tax_value = TAX or "none"

    payload_obj = {
        "MerchantLogin": MERCHANT_LOGIN,
        "InvoiceType": "OneTime",
        "Culture": "ru",
        "OutSum": float(amount),
        "Description": description,
        "InvoiceItems": [
            {
                "Name": item_name,
                "Quantity": 1,
                "Cost": float(amount),
                "Tax": tax_value,
                "PaymentMethod": "full_payment",
                "PaymentObject": "service",
            }
        ],
    }

    header_json = json.dumps(header_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_json = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    header_b64 = base64.urlsafe_b64encode(header_json).decode("ascii").rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    key = f"{MERCHANT_LOGIN}:{PASSWORD1}".encode("utf-8")

    hmac_bytes = hmac.new(key, signing_input, hashlib.md5).digest()
    signature_b64 = base64.urlsafe_b64encode(hmac_bytes).decode("ascii").rstrip("=")

    token = f"{header_b64}.{payload_b64}.{signature_b64}"
    return token, header_obj, payload_obj, header_b64, payload_b64


def create_invoice_and_get_link(description: str, amount: float, item_name: str):
    token, header_obj, payload_obj, header_b64, payload_b64 = build_invoice_jwt(
        description=description,
        amount=amount,
        item_name=item_name,
    )

    body_text = json.dumps(token, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        resp = requests.post(
            INVOICE_API_URL,
            data=body_text.encode("utf-8"),
            headers=headers,
            timeout=20,
        )
    except Exception as e:
        raise RuntimeError(f"Не удалось обратиться к Invoice API: {e}")

    log_invoice_debug(
        header_obj, payload_obj, header_b64, payload_b64, token, body_text, resp
    )

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(
            f"Некорректный ответ Robokassa (ожидали JSON): {resp.text[:500]}"
        )

    if not data.get("isSuccess"):
        msg = data.get("message") or "Неизвестная ошибка Invoice API"
        raise RuntimeError(f"Robokassa вернула ошибку: {msg}")

    link = (
        data.get("invoiceUrl")
        or data.get("InvoiceUrl")
        or data.get("url")
        or data.get("Url")
        or data.get("paymentUrl")
        or data.get("PaymentUrl")
    )

    invoice_id = data.get("invId") or data.get("invoiceId") or data.get("InvoiceId")

    if not link:
        raise RuntimeError(
            "Не удалось найти ссылку в ответе Invoice API: "
            + json.dumps(data, ensure_ascii=False)
        )

    return link, invoice_id


def build_qr_image_bytes(url: str) -> BytesIO:
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


def parse_opstate_xml(xml_text: str) -> dict:
    text = xml_text.lstrip("\ufeff").strip()

    try:
        root = ET.fromstring(text)
    except Exception as e:
        raise RuntimeError(
            f"Не удалось разобрать XML от OpState:\n{e}\n\nТело:\n{text[:2000]}"
        )

    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    result: dict[str, str] = {}

    rc_el = root.find("Result/Code")
    if rc_el is not None and rc_el.text:
        result["ResultCode"] = rc_el.text.strip()

    rd_el = root.find("Result/Description")
    if rd_el is not None and rd_el.text:
        result["ResultDescription"] = rd_el.text.strip()

    state_code_el = root.find("State/Code")
    if state_code_el is not None and state_code_el.text:
        result["StateCode"] = state_code_el.text.strip()

    rd_el2 = root.find("State/RequestDate")
    if rd_el2 is not None and rd_el2.text:
        result["RequestDate"] = rd_el2.text.strip()

    sd_el = root.find("State/StateDate")
    if sd_el is not None and sd_el.text:
        result["StateDate"] = sd_el.text.strip()

    inc_curr = root.find("Info/IncCurrLabel")
    if inc_curr is not None and inc_curr.text:
        result["IncCurrLabel"] = inc_curr.text.strip()

    inc_sum = root.find("Info/IncSum")
    if inc_sum is not None and inc_sum.text:
        result["IncSum"] = inc_sum.text.strip()

    inc_acc = root.find("Info/IncAccount")
    if inc_acc is not None and inc_acc.text:
        result["IncAccount"] = inc_acc.text.strip()

    pm_el = root.find("Info/PaymentMethodCode")
    if pm_el is not None and pm_el.text:
        result["PaymentMethodCode"] = pm_el.text.strip()

    out_curr = root.find("Info/OutCurrLabel")
    if out_curr is not None and out_curr.text:
        result["OutCurrLabel"] = out_curr.text.strip()

    out_sum = root.find("Info/OutSum")
    if out_sum is not None and out_sum.text:
        result["OutSum"] = out_sum.text.strip()

    op_key = root.find("Info/OpKey")
    if op_key is not None and op_key.text:
        result["OpKey"] = op_key.text.strip()

    return result


def get_payment_state(inv_id: str | int) -> dict:
    if not MERCHANT_LOGIN or not PASSWORD2:
        raise RuntimeError("Не заданы MerchantLogin / Password2 в настройках Robokassa.")

    sig_src = f"{MERCHANT_LOGIN}:{inv_id}:{PASSWORD2}"
    signature = hashlib.md5(sig_src.encode("utf-8")).hexdigest()

    params = {
        "MerchantLogin": MERCHANT_LOGIN,
        "InvoiceID": str(inv_id),
        "Signature": signature,
    }

    try:
        resp = requests.get(OPSTATE_URL, params=params, timeout=20)
    except Exception as e:
        raise RuntimeError(f"Не удалось обратиться к OpStateExt: {e}")

    if not resp.ok:
        raise RuntimeError(f"OpStateExt вернул HTTP {resp.status_code}: {resp.text[:500]}")

    raw_bytes = resp.content
    try:
        xml_text = raw_bytes.decode("utf-8-sig")
    except Exception:
        xml_text = raw_bytes.decode("utf-8", errors="replace")

    xml_text = xml_text.lstrip("\ufeff").strip()
    if xml_text.startswith("ï»¿"):
        xml_text = xml_text[3:]
    first_lt = xml_text.find("<")
    if first_lt > 0:
        xml_text = xml_text[first_lt:]

    info = parse_opstate_xml(xml_text)
    info["_raw"] = xml_text
    return info
