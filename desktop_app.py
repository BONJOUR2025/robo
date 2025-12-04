#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BONJOUR — локальное приложение для выставления счётов через Robokassa.

- Настройки Robokassa (логин, пароли, СНО, НДС, email).
- SQLite-база payments.sqlite3.
- Встроенный ResultURL-сервер на aiohttp (порт по умолчанию 8085).
- Отправка QR и ссылки в Telegram по user_chat_id.
- Создание счетов через Invoice API (JWT).
- Онлайн-проверка статуса платежа через WebService OpStateExt.
"""

import json
import base64
import sqlite3
from io import BytesIO
from pathlib import Path
import threading
import asyncio
import hmac
import hashlib
from datetime import datetime
import xml.etree.ElementTree as ET

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import requests
import qrcode

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    web = None
    AIOHTTP_AVAILABLE = False

# ---------- Пути и общие константы ----------

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
LOGO_PATH = APP_DIR / "logo.png"

DB_PATH = APP_DIR / "data"
DB_PATH.mkdir(exist_ok=True)
DB_FILE = DB_PATH / "payments.sqlite3"

INVOICE_DEBUG_LOG = APP_DIR / "invoice_debug.log"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    tg_user_id INTEGER,
    tg_username TEXT,
    order_number TEXT NOT NULL,
    services TEXT NOT NULL,
    amount REAL NOT NULL,
    payment_url TEXT NOT NULL,
    status TEXT NOT NULL,
    invoice_id INTEGER
);
"""

# ---------- Цвета/темы интерфейса ----------

COLOR_BG = "#111827"
COLOR_PRIMARY = "#0F172A"
COLOR_CARD_BG = "#020617"
COLOR_ACCENT = "#F59E0B"
COLOR_ACCENT_DARK = "#D97706"
COLOR_ENTRY_BG = "#020617"
COLOR_ENTRY_BORDER = "#1F2937"
COLOR_TABLE_BG = "#020617"
COLOR_TABLE_BORDER = "#1F2937"
COLOR_TABLE_HEADER_BG = "#111827"
COLOR_TABLE_HEADER_FG = "#E5E7EB"
COLOR_LABEL = "#E5E7EB"
COLOR_MUTED = "#9CA3AF"

# ---------- Глобальные настройки (подхватываются из config.json) ----------

MERCHANT_LOGIN = ""
PASSWORD1 = ""
PASSWORD2 = ""
SHOP_SNO = "patent"
TAX = "none"
CUSTOMER_EMAIL = "example@example.com"
IS_TEST = 0

BOT_TOKEN = ""
ADMIN_ID = 0
USER_CHAT_ID = 0
RESULT_PORT = 8085

APP_CONFIG: dict = {}

# ---------- Конфиг ----------


def get_default_config() -> dict:
    return {
        "merchant_login": "",
        "password1": "",
        "password2": "",
        "shop_sno": "patent",
        "tax": "none",
        "customer_email": "example@example.com",
        "is_test": 0,
        "telegram_token": "",
        "admin_id": 0,
        "user_chat_id": 0,
        "result_port": 8085,
        # Firebird
        "fb_db_path": "",
        "fb_user": "",
        "fb_password": "",
    }


def apply_config_to_globals(cfg: dict):
    global MERCHANT_LOGIN, PASSWORD1, PASSWORD2, SHOP_SNO, TAX, CUSTOMER_EMAIL, IS_TEST
    global BOT_TOKEN, ADMIN_ID, USER_CHAT_ID, RESULT_PORT, APP_CONFIG

    MERCHANT_LOGIN = cfg.get("merchant_login", "") or ""
    PASSWORD1 = cfg.get("password1", "") or ""
    PASSWORD2 = cfg.get("password2", "") or ""
    SHOP_SNO = cfg.get("shop_sno", "patent") or "patent"
    TAX = cfg.get("tax", "none") or "none"
    CUSTOMER_EMAIL = cfg.get("customer_email", "example@example.com") or "example@example.com"
    IS_TEST = int(cfg.get("is_test", 0) or 0)

    BOT_TOKEN = cfg.get("telegram_token", "") or ""
    ADMIN_ID = int(cfg.get("admin_id") or 0)
    USER_CHAT_ID = int(cfg.get("user_chat_id") or 0)
    RESULT_PORT = int(cfg.get("result_port") or 8085)

    APP_CONFIG = cfg


def load_or_init_config() -> dict:
    cfg = get_default_config()
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                cfg.update(stored)
        except Exception:
            pass

    # приведение типов
    for key in ("admin_id", "user_chat_id", "result_port"):
        try:
            if cfg.get(key) not in (None, ""):
                cfg[key] = int(cfg[key])
            else:
                cfg[key] = 0
        except Exception:
            cfg[key] = 0

    apply_config_to_globals(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    apply_config_to_globals(cfg)


# ---------- Работа с базой ----------

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(CREATE_TABLE_SQL)
    # миграция: добавляем колонку invoice_id, если её не было
    try:
        conn.execute("ALTER TABLE payments ADD COLUMN invoice_id INTEGER")
        conn.commit()
    except Exception:
        pass
    conn.close()


def insert_payment(
    tg_user_id: int,
    tg_username: str,
    order_number: str,
    services: str,
    amount: float,
    payment_url: str,
    status: str = "created",
    invoice_id: int | None = None,
):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO payments
            (created_at, tg_user_id, tg_username, order_number,
             services, amount, payment_url, status, invoice_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            tg_user_id,
            tg_username,
            order_number,
            services,
            amount,
            payment_url,
            status,
            invoice_id,
        ),
    )
    conn.commit()
    conn.close()


def update_payment_status(order_number: str, new_status: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE payments
        SET status = ?
        WHERE order_number = ?
        """,
        (new_status, order_number),
    )
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


def get_last_payment(order_number: str):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, created_at, amount, status, tg_username, tg_user_id, invoice_id
        FROM payments
        WHERE order_number = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (order_number,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_recent_payments_for_order(order_number: str, limit: int = 3):
    """
    Возвращает до `limit` последних платежей по заказу (id DESC).
    """
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id, created_at, amount, status, tg_username, tg_user_id, invoice_id
        FROM payments
        WHERE order_number = ?
        ORDER BY id DESC
        LIMIT {int(limit)}
        """,
        (order_number,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_payments(filter_order: str = ""):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if filter_order:
        cur.execute(
            """
            SELECT id, created_at, order_number, services, amount, status,
                   tg_username, tg_user_id, payment_url, invoice_id
            FROM payments
            WHERE order_number LIKE ?
            ORDER BY id DESC
            """,
            (f"%{filter_order}%",),
        )
    else:
        cur.execute(
            """
            SELECT id, created_at, order_number, services, amount, status,
                   tg_username, tg_user_id, payment_url, invoice_id
            FROM payments
            ORDER BY id DESC
            """
        )

    rows = cur.fetchall()
    conn.close()
    return rows


# ---------- Robokassa Invoice API (JWT) + OpStateExt ----------

INVOICE_API_URL = "https://services.robokassa.ru/InvoiceServiceWebApi/api/CreateInvoice"

# ВАЖНО: именно auth.robokassa.ru, не roboxchange.com
OPSTATE_URL = "https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt"


def log_invoice_debug(header_obj, payload_obj, header_b64, payload_b64, token, body_text, response: requests.Response):
    """
    Пишем подробный лог в файл invoice_debug.log, чтобы видеть точный запрос и ответ.
    """
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
    """
    Формируем JWT-токен для Invoice API.
    """
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
    """
    Создаём счёт через Invoice API и возвращаем (ссылка, invoice_id).
    """
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
    """
    Разбор XML-ответа OpStateExt.

    Возвращает словарь с ключами:
      - ResultCode, ResultDescription
      - StateCode, RequestDate, StateDate
      - IncCurrLabel, IncSum, IncAccount, PaymentMethodCode,
        OutCurrLabel, OutSum, OpKey
    """
    text = xml_text.lstrip("\ufeff").strip()

    try:
        root = ET.fromstring(text)
    except Exception as e:
        raise RuntimeError(
            f"Не удалось разобрать XML от OpState:\n{e}\n\nТело:\n{text[:2000]}"
        )

    # убираем namespace
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    result: dict[str, str] = {}

    # Result
    rc_el = root.find("Result/Code")
    if rc_el is not None and rc_el.text:
        result["ResultCode"] = rc_el.text.strip()

    rd_el = root.find("Result/Description")
    if rd_el is not None and rd_el.text:
        result["ResultDescription"] = rd_el.text.strip()

    # State
    state_code_el = root.find("State/Code")
    if state_code_el is not None and state_code_el.text:
        result["StateCode"] = state_code_el.text.strip()
    else:
        state_el = root.find("State")
        if state_el is not None and state_el.text and state_el.text.strip().isdigit():
            result["StateCode"] = state_el.text.strip()

    req_date_el = root.find("State/RequestDate")
    if req_date_el is not None and req_date_el.text:
        result["RequestDate"] = req_date_el.text.strip()

    state_date_el = root.find("State/StateDate")
    if state_date_el is not None and state_date_el.text:
        result["StateDate"] = state_date_el.text.strip()

    # Info
    def grab(path: str, key: str):
        el = root.find(path)
        if el is not None and el.text:
            result[key] = el.text.strip()

    grab("Info/IncCurrLabel", "IncCurrLabel")
    grab("Info/IncSum", "IncSum")
    grab("Info/IncAccount", "IncAccount")
    grab("Info/PaymentMethod/Code", "PaymentMethodCode")
    grab("Info/OutCurrLabel", "OutCurrLabel")
    grab("Info/OutSum", "OutSum")
    grab("Info/OpKey", "OpKey")

    return result


def get_payment_state_by_inv_id(inv_id: int) -> dict:
    """
    Проверка статуса платежа через WebService OpStateExt по InvId.

    Signature = MD5(MerchantLogin:InvoiceID:Password2)
    """
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


# ---------- Telegram отправка ----------

def send_qr_to_telegram(qr_bytes: BytesIO, payment_url: str, order_number: str):
    token = APP_CONFIG.get("telegram_token", "").strip()
    user_chat_id = APP_CONFIG.get("user_chat_id")

    if not token or not user_chat_id:
        print("[TELEGRAM] Не настроен токен или chat_id, отправка QR пропущена")
        return

    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    caption = (
        f"Оплата заказа {order_number}\n\n"
        f"Ссылка для оплаты: {payment_url}"
    )

    files = {
        "photo": ("qr.png", qr_bytes, "image/png"),
    }
    data = {
        "chat_id": user_chat_id,
        "caption": caption,
    }

    try:
        r = requests.post(url, data=data, files=files, timeout=10)
        if not r.ok:
            print("[TELEGRAM] Ошибка отправки фото:", r.status_code, r.text)
    except Exception as e:
        print("[TELEGRAM] Исключение при отправке фото:", e)


# ---------- ResultURL-сервер ----------

class ResultHandler:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    async def handle(self, request: "web.Request"):
        try:
            if request.method == "POST":
                data = await request.post()
            else:
                data = request.query

            out_sum = data.get("OutSum")
            inv_id = data.get("InvId")
            signature = data.get("SignatureValue")
            shp_order = data.get("Shp_order")

            if shp_order:
                updated = update_payment_status(shp_order, "paid")
                if updated:
                    try:
                        row = get_last_payment(shp_order)
                        if row:
                            self.notify_admin_paid(row)
                    except Exception:
                        pass

            return web.Response(text="OK")
        except Exception as e:
            return web.Response(status=500, text=f"Error: {e}")

    def notify_admin_paid(self, row: sqlite3.Row):
        token = self.cfg.get("telegram_token", "").strip()
        admin_id = self.cfg.get("admin_id")
        if not token or not admin_id:
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"

        buyer = f"@{row['tg_username']}" if row["tg_username"] else "(покупатель не указан)"

        text = (
            f"💸 Оплата получена\n"
            f"Заказ (ID записи): {row['id']}\n"
            f"Сумма: {row['amount']:.2f} руб.\n"
            f"Покупатель: {buyer}"
        )

        try:
            r = requests.post(
                url, json={"chat_id": admin_id, "text": text}, timeout=10
            )
            if not r.ok:
                print("[TELEGRAM] Ошибка отправки уведомления админу:", r.text)
        except Exception:
            pass


def start_result_server_in_background():
    if not AIOHTTP_AVAILABLE:
        print("[RESULT] aiohttp не установлен, ResultURL-сервер не запущен")
        return

    cfg = APP_CONFIG.copy()
    handler = ResultHandler(cfg)

    async def _app_factory():
        app = web.Application()
        app.router.add_get("/result", handler.handle)
        app.router.add_post("/result", handler.handle)
        return app

    async def _run():
        app = await _app_factory()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", cfg.get("result_port", 8085))
        await site.start()
        print(f"[RESULT] Сервер запущен на порту {cfg.get('result_port', 8085)}")
        while True:
            await asyncio.sleep(3600)

    def _thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())

    t = threading.Thread(target=_thread_target, daemon=True)
    t.start()


# ---------- GUI ----------

class App(tk.Tk):
    def __init__(self, cfg: dict):
        super().__init__()
        self.title("BONJOUR — Robokassa Desktop")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        self.configure(bg=COLOR_BG)

        self.cfg = cfg
        self.items: list[dict] = []
        self._settings_window: tk.Toplevel | None = None

        try:
            self.iconphoto(False, tk.PhotoImage(file=str(LOGO_PATH)))
        except Exception:
            pass

        self.style = ttk.Style(self)
        self._init_styles()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        self.frame_main = ttk.Frame(self.notebook, padding=16)
        self.frame_payments = ttk.Frame(self.notebook, padding=16)

        self.notebook.add(self.frame_main, text="Выставление счёта")
        self.notebook.add(self.frame_payments, text="Журнал платежей")

        self._build_main_tab()
        self._build_payments_tab()

        # Скрытые настройки: открываются только по Ctrl+Alt+S
        self.bind_all("<Control-Alt-s>", self.open_settings_window)

    # ---------- Стили ----------

    def _init_styles(self):
        style = self.style
        style.theme_use("clam")

        style.configure(
            ".",
            background=COLOR_BG,
            foreground=COLOR_LABEL,
            fieldbackground=COLOR_ENTRY_BG,
        )

        style.configure("TFrame", background=COLOR_BG)
        style.configure("Card.TFrame", background=COLOR_CARD_BG, relief="solid", borderwidth=1)
        style.map("Card.TFrame", background=[("active", COLOR_CARD_BG)])

        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_LABEL, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground=COLOR_MUTED, background=COLOR_BG, font=("Segoe UI", 9))

        style.configure(
            "Accent.TButton",
            background=COLOR_ACCENT,
            foreground="#111827",
            padding=8,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", COLOR_ACCENT_DARK), ("pressed", COLOR_ACCENT_DARK)],
        )

        style.configure(
            "TButton",
            background="#1F2937",
            foreground=COLOR_LABEL,
            padding=6,
            relief="flat",
            font=("Segoe UI", 10),
        )
        style.map(
            "TButton",
            background=[("active", "#374151"), ("pressed", "#374151")],
        )

        style.configure(
            "TEntry",
            fieldbackground=COLOR_ENTRY_BG,
            foreground=COLOR_LABEL,
            padding=4,
            bordercolor=COLOR_ENTRY_BORDER,
            lightcolor=COLOR_ENTRY_BORDER,
            darkcolor=COLOR_ENTRY_BORDER,
            insertcolor=COLOR_LABEL,
        )

        style.configure(
            "TNotebook",
            background=COLOR_BG,
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background="#020617",
            foreground=COLOR_LABEL,
            padding=(16, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#111827"), ("!selected", "#020617")],
            foreground=[("selected", COLOR_LABEL)],
        )

        style.configure(
            "Treeview",
            background=COLOR_TABLE_BG,
            fieldbackground=COLOR_TABLE_BG,
            foreground=COLOR_LABEL,
            rowheight=26,
            bordercolor=COLOR_TABLE_BORDER,
        )
        style.configure(
            "Treeview.Heading",
            background=COLOR_TABLE_HEADER_BG,
            foreground=COLOR_TABLE_HEADER_FG,
            font=("Segoe UI", 9, "bold"),
        )

    # ---------- Вкладка "Выставление счёта" ----------

    def _build_main_tab(self):
        frame = self.frame_main

        left = ttk.Frame(frame, style="Card.TFrame", padding=16)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8), pady=0)

        right = ttk.Frame(frame, style="Card.TFrame", padding=16)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=0)

        # Левая часть — ввод заказа и позиций
        lbl_title = ttk.Label(left, text="Новый счёт на оплату", font=("Segoe UI Semibold", 14))
        lbl_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(left, text="Номер заказа:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.order_entry = ttk.Entry(left, width=20)
        self.order_entry.grid(row=1, column=1, sticky="we", pady=4)
        left.grid_columnconfigure(1, weight=1)

        btn_load = ttk.Button(
            left,
            text="Загрузить услуги из программы",
            command=self.load_order_from_db,
        )
        btn_load.grid(row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(left, text="Описание / услуги:").grid(row=2, column=0, sticky="ne", padx=(0, 8), pady=4)
        self.services_text = tk.Text(
            left,
            width=50,
            height=4,
            bg=COLOR_ENTRY_BG,
            fg=COLOR_LABEL,
            relief="flat",
            insertbackground=COLOR_LABEL,
            padx=6,
            pady=6,
        )
        self.services_text.grid(row=2, column=1, columnspan=2, sticky="we", pady=4)

        ttk.Label(left, text="Сумма к оплате, руб:").grid(row=3, column=0, sticky="e", padx=(0, 8), pady=4)
        self.amount_entry = ttk.Entry(left, width=20)
        self.amount_entry.grid(row=3, column=1, sticky="w", pady=4)

        # Позиции
        items_frame = ttk.LabelFrame(left, text="Позиции чека", padding=8)
        items_frame.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(12, 0))
        left.grid_rowconfigure(4, weight=1)

        self.items_listbox = tk.Listbox(
            items_frame,
            bg=COLOR_ENTRY_BG,
            fg=COLOR_LABEL,
            selectbackground=COLOR_ACCENT,
            selectforeground="#020617",
            relief="flat",
            activestyle="none",
            highlightthickness=0,
        )
        self.items_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(items_frame, orient=tk.VERTICAL, command=self.items_listbox.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.items_listbox.config(yscrollcommand=sb.set)

        btn_col = ttk.Frame(items_frame)
        btn_col.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        ttk.Button(btn_col, text="Добавить позицию", command=self.add_item_dialog).pack(fill=tk.X, pady=2)
        ttk.Button(btn_col, text="Изменить позицию", command=self.edit_selected_item).pack(fill=tk.X, pady=2)
        ttk.Button(btn_col, text="Удалить позицию", command=self.delete_selected_item).pack(fill=tk.X, pady=2)

        # Кнопка создания счёта
        btn_create = ttk.Button(
            left,
            text="Сформировать ссылку и QR для оплаты",
            style="Accent.TButton",
            command=self.generate_payment,
        )
        btn_create.grid(row=5, column=0, columnspan=3, sticky="we", pady=(12, 0))

        # Правая часть — проверка статуса, подсказки
        right.grid_columnconfigure(0, weight=1)

        ttk.Label(right, text="Проверка статуса оплаты", font=("Segoe UI Semibold", 12)).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        block = ttk.Frame(right)
        block.grid(row=1, column=0, sticky="we")
        block.grid_columnconfigure(1, weight=1)

        ttk.Label(block, text="Номер заказа:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.check_order_entry = ttk.Entry(block, width=20)
        self.check_order_entry.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Button(
            block,
            text="Проверить статус оплаты онлайн",
            command=self.check_online_status,
        ).grid(row=0, column=2, padx=(8, 0), pady=4)

        hint = ttk.Label(
            right,
            text="После успешной оплаты Robokassa автоматически обновит статус.\n"
                 "Здесь можно запросить онлайн-статус по номеру заказа\n"
                 "(проверяются последние платежи по этому заказу).",
            style="Muted.TLabel",
            justify="left",
        )
        hint.grid(row=2, column=0, sticky="w", pady=(12, 0))

    # ---------- Работа с позициями ----------

    def update_items_listbox(self):
        self.items_listbox.delete(0, tk.END)
        for item in self.items:
            name = item.get("name", "")
            price = float(item.get("price", 0.0))
            qty = float(item.get("qty", 1))
            total = price * qty
            self.items_listbox.insert(
                tk.END,
                f"{name} — {qty:g} × {price:.2f} = {total:.2f} руб.",
            )

        base_total = sum(float(i.get("price", 0.0)) * float(i.get("qty", 1)) for i in self.items)
        self.base_total = base_total
        if not self.amount_entry.get().strip():
            self.amount_entry.delete(0, tk.END)
            self.amount_entry.insert(0, f"{base_total:.2f}")

        if self.items and not self.services_text.get("1.0", tk.END).strip():
            self.services_text.delete("1.0", tk.END)
            self.services_text.insert("1.0", "\n".join(i["name"] for i in self.items))

    def add_item_dialog(self):
        self._open_item_dialog()

    def edit_selected_item(self):
        selection = self.items_listbox.curselection()
        if not selection:
            messagebox.showinfo("Позиции", "Выберите позицию для изменения.")
            return
        index = selection[0]
        item = self.items[index]
        self._open_item_dialog(existing=item, index=index)

    def delete_selected_item(self):
        selection = self.items_listbox.curselection()
        if not selection:
            messagebox.showinfo("Позиции", "Выберите позицию для удаления.")
            return
        index = selection[0]
        del self.items[index]
        self.update_items_listbox()

    def _open_item_dialog(self, existing: dict | None = None, index: int | None = None):
        win = tk.Toplevel(self)
        win.title("Позиция чека")
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Название:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        name_entry = ttk.Entry(frm, width=40)
        name_entry.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(frm, text="Количество:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        qty_entry = ttk.Entry(frm, width=10)
        qty_entry.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(frm, text="Цена за единицу:").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        price_entry = ttk.Entry(frm, width=10)
        price_entry.grid(row=2, column=1, sticky="w", pady=4)

        frm.grid_columnconfigure(1, weight=1)

        if existing:
            name_entry.insert(0, existing.get("name", ""))
            qty_entry.insert(0, str(existing.get("qty", 1)))
            price_entry.insert(0, f"{existing.get('price', 0.0):.2f}")

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, pady=(12, 0), sticky="e")

        def on_save():
            name = name_entry.get().strip()
            qty_raw = qty_entry.get().strip()
            price_raw = price_entry.get().strip()

            if not name or not qty_raw or not price_raw:
                messagebox.showwarning("Позиция", "Заполните все поля.")
                return

            try:
                qty = float(qty_raw.replace(",", "."))
                price = float(price_raw.replace(",", "."))
            except Exception:
                messagebox.showerror("Позиция", "Некорректное количество или цена.")
                return

            if qty <= 0 or price <= 0:
                messagebox.showerror("Позиция", "Количество и цена должны быть больше 0.")
                return

            new_item = {
                "name": name[:128],
                "qty": qty,
                "price": price,
            }

            if existing is not None and index is not None:
                self.items[index] = new_item
            else:
                self.items.append(new_item)

            self.update_items_listbox()
            win.destroy()

        save_btn = ttk.Button(btns, text="Сохранить", command=on_save)
        save_btn.pack(side=tk.RIGHT, padx=(5, 0))

        cancel_btn = ttk.Button(btns, text="Отмена", command=win.destroy)
        cancel_btn.pack(side=tk.RIGHT)

        win.wait_window()

    # ---------- Firebird ----------

    def load_order_from_db(self):
        order_number = self.order_entry.get().strip()
        if not order_number:
            messagebox.showwarning("Номер заказа", "Сначала введите номер заказа.")
            return

        db_path = APP_CONFIG.get("fb_db_path", "").strip()
        db_user = APP_CONFIG.get("fb_user", "").strip()
        db_password = APP_CONFIG.get("fb_password", "").strip()

        if not db_path or not db_user:
            messagebox.showwarning(
                "База данных",
                "Не указан путь к .fdb или логин в настройках.\n"
                "Откройте скрытые настройки (Ctrl+Alt+S) и заполните раздел Firebird.",
            )
            return

        try:
            import fdb  # type: ignore
        except ImportError:
            messagebox.showerror(
                "Firebird",
                "Не установлен драйвер Firebird для Python.\n\n"
                "Установите пакет:\n"
                "    pip install fdb",
            )
            return

        conn = None
        try:
            conn = fdb.connect(
                dsn=db_path,
                user=db_user,
                password=db_password,
                charset="WIN1251",
            )
            cur = conn.cursor()

            # Объединённый запрос: услуги + строки заказа, без истории/контрагента,
            # чтобы не было дублей
            sql = """
                SELECT
                    t1.name,
                    s.kredit
                FROM docs_order o1
                    INNER JOIN doc_order_services s
                        ON o1.id = s.doc_order_id
                    INNER JOIN tovars_tbl t1
                        ON s.tovar_id = t1.tovar_id
                    INNER JOIN docs d1
                        ON o1.doc_id = d1.doc_id
                WHERE d1.doc_num = ?

                UNION ALL

                SELECT
                    t2.name,
                    l.kredit
                FROM doc_order_lines l
                    INNER JOIN docs_order o2
                        ON l.doc_order_id = o2.id
                    INNER JOIN docs d2
                        ON o2.doc_id = d2.doc_id
                    INNER JOIN tovars_tbl t2
                        ON l.tovar_id = t2.tovar_id
                WHERE d2.doc_num = ?
            """
            cur.execute(sql, (order_number, order_number))
            rows = cur.fetchall()

            if not rows:
                messagebox.showinfo(
                    "Загрузка данных",
                    f"Заказ с номером {order_number} не найден в базе.",
                )
                return

            self.items = []
            for name, kredit in rows:
                try:
                    amount = float(kredit)
                except Exception:
                    continue
                item = {"name": str(name)[:128], "price": amount, "qty": 1}
                self.items.append(item)

            self.update_items_listbox()
            messagebox.showinfo(
                "Загрузка данных",
                f"Данные заказа {order_number} успешно загружены из базы.",
            )

        except Exception as e:
            messagebox.showerror("Firebird", f"Ошибка при обращении к базе:\n{e}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    # ---------- Генерация платежа ----------

    def _get_current_amount(self) -> float:
        text = self.amount_entry.get().strip()
        if not text:
            return round(getattr(self, "base_total", 0.0), 2)
        raw = text.replace(",", ".")
        try:
            amount = float(raw)
        except Exception:
            raise ValueError("Сумма к оплате указана некорректно.")
        if amount <= 0:
            raise ValueError("Сумма к оплате должна быть больше 0.")
        return round(amount, 2)

    def generate_payment(self):
        order_number = self.order_entry.get().strip()
        if not order_number:
            messagebox.showwarning("Номер заказа", "Введите номер заказа.")
            return

        services = self.services_text.get("1.0", tk.END).strip()
        if not services:
            services = f"Оплата заказа {order_number}"

        try:
            amount = self._get_current_amount()
        except ValueError as e:
            messagebox.showerror("Сумма", str(e))
            return

        # Телеграм клиента/ID не спрашиваем — используем дефолт из настроек
        tg_username = ""
        tg_user_id = APP_CONFIG.get("user_chat_id") or 0

        try:
            payment_url, invoice_id = create_invoice_and_get_link(
                description=f"Заказ №{order_number}",
                amount=amount,
                item_name=services[:100],
            )
        except Exception as e:
            messagebox.showerror(
                "Создание счёта",
                f"Ошибка при создании счёта через Invoice API:\n{e}",
            )
            return

        try:
            insert_payment(
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                order_number=order_number,
                services=services,
                amount=amount,
                payment_url=payment_url,
                status="created",
                invoice_id=invoice_id if invoice_id is not None else None,
            )
        except Exception as e:
            messagebox.showerror(
                "База данных",
                f"Не удалось записать платёж в локальную базу:\n{e}",
            )
            return

        try:
            qr_bytes = build_qr_image_bytes(payment_url)
            send_qr_to_telegram(qr_bytes, payment_url, order_number)
        except Exception as e:
            print("[QR/TELEGRAM] Ошибка при отправке QR:", e)

        messagebox.showinfo(
            "Счёт создан",
            "Ссылка и QR-код успешно сформированы.\n"
            "QR-код и ссылка отправлены в Telegram.",
        )

    # ---------- Локальная проверка (оставлена как вспомогательная, без кнопки) ----------

    def check_payment_status(self):
        order_number = getattr(self, "check_order_entry", None)
        if order_number is None:
            messagebox.showerror("Статус оплаты", "Поле для ввода номера заказа не найдено.")
            return

        order_number = self.check_order_entry.get().strip()
        if not order_number:
            messagebox.showwarning(
                "Номер заказа", "Введите номер заказа для проверки."
            )
            return

        try:
            row = get_last_payment(order_number)
        except Exception as e:
            messagebox.showerror(
                "Статус оплаты", f"Не удалось обратиться к базе данных:\n{e}"
            )
            return

        if row is None:
            messagebox.showinfo(
                "Статус оплаты",
                f"Заказ {order_number} не найден в базе.",
            )
            return

        msg = (
            f"ID записи: {row['id']}\n"
            f"Создан: {row['created_at']}\n"
            f"Сумма: {row['amount']:.2f} руб.\n"
            f"Статус: {row['status']}\n"
            f"Покупатель: @{row['tg_username']}"
        )
        messagebox.showinfo("Статус оплаты", msg)

    # ---------- Онлайн-статус (OpStateExt, до 3 платежей) ----------

    def check_online_status(self):
        """Онлайн-статус платежа через Robokassa OpStateExt по последним 3 платежам заказа."""
        order_number = self.check_order_entry.get().strip()
        if not order_number:
            messagebox.showwarning(
                "Статус оплаты",
                "Введите номер заказа для проверки."
            )
            return

        # 1. Берём до 3 последних записей из локальной БД
        try:
            rows = get_recent_payments_for_order(order_number, limit=3)
        except Exception as e:
            messagebox.showerror(
                "Статус оплаты",
                f"Не удалось обратиться к базе данных:\n{e}",
            )
            return

        if not rows:
            messagebox.showinfo(
                "Статус оплаты",
                f"Заказ {order_number} не найден в локальной базе.",
            )
            return

        # Справочник кодов в человеко-читаемый статус
        state_map = {
            "5": "ожидает оплаты",
            "10": "отменён, деньги не получены",
            "20": "средства заморожены (HOLD)",
            "50": "деньги получены, зачисляются",
            "60": "отказ в зачислении / возврат",
            "80": "исполнение приостановлено",
            "100": "успешно оплачено",
        }

        def format_dt(dt_str: str | None) -> str:
            if not dt_str:
                return ""
            dt_str = dt_str.strip()
            # пробуем ISO-формат
            try:
                # отрезаем лишние микросекунды/зону, если что
                if dt_str.endswith("Z"):
                    dt_str_local = dt_str.replace("Z", "+00:00")
                else:
                    dt_str_local = dt_str
                dt = datetime.fromisoformat(dt_str_local)
                return dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                # пробуем формат локальной БД
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    return dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    return dt_str

        lines: list[str] = []
        lines.append(f"Заказ №{order_number}")
        lines.append("")

        any_online = False

        for idx, row in enumerate(rows, start=1):
            invoice_id = row["invoice_id"]
            local_created = row["created_at"] or ""
            local_amount = row["amount"] or 0.0

            if not invoice_id:
                status_text = "нет данных об онлайн-статусе (InvId не сохранён)"
                dt_text = format_dt(local_created)
            else:
                try:
                    info = get_payment_state_by_inv_id(int(invoice_id))
                    state_code = info.get("StateCode")
                    state_text = state_map.get(state_code or "", "статус не определён")
                    dt_text = format_dt(info.get("StateDate") or local_created)
                    status_text = state_text
                    any_online = True
                except Exception as e:
                    dt_text = format_dt(local_created)
                    status_text = f"ошибка при запросе статуса: {e}"

            amount_text = f"{float(local_amount):.2f} руб."
            dt_part = dt_text if dt_text else "дата не указана"

            lines.append(
                f"{idx}. Платёж: {dt_part} — {amount_text} — {status_text}"
            )

        if not any_online:
            lines.append("")
            lines.append("Онлайн-данные Robokassa недоступны (нет InvId или запрос завершился ошибкой).")

        messagebox.showinfo(
            "Статус оплаты",
            "\n".join(lines),
        )

    # ---------- Вкладка "Платежи" ----------

    def _build_payments_tab(self):
        frame = self.frame_payments

        top = ttk.Frame(frame)
        top.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top, text="Фильтр по номеру заказа:").pack(side=tk.LEFT)
        self.filter_entry = ttk.Entry(top, width=20)
        self.filter_entry.pack(side=tk.LEFT, padx=(8, 8))

        ttk.Button(
            top,
            text="Применить фильтр",
            command=self.refresh_payments,
        ).pack(side=tk.LEFT)

        ttk.Button(
            top,
            text="Экспортировать в CSV",
            command=self.export_payments_csv,
        ).pack(side=tk.RIGHT)

        columns = ("id", "created_at", "order_number", "amount", "status", "tg_username")

        self.tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            height=18,
        )
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.tree.heading("id", text="ID")
        self.tree.heading("created_at", text="Создан")
        self.tree.heading("order_number", text="Заказ")
        self.tree.heading("amount", text="Сумма")
        self.tree.heading("status", text="Статус")
        self.tree.heading("tg_username", text="Покупатель")

        self.tree.column("id", width=50, anchor="center")
        self.tree.column("created_at", width=140, anchor="center")
        self.tree.column("order_number", width=100, anchor="w")
        self.tree.column("amount", width=100, anchor="e")
        self.tree.column("status", width=120, anchor="center")
        self.tree.column("tg_username", width=140, anchor="w")

        self.refresh_payments()

    def refresh_payments(self):
        flt = self.filter_entry.get().strip()

        for item in self.tree.get_children():
            self.tree.delete(item)

        rows = get_payments(flt)
        for row in rows:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    row["id"],
                    row["created_at"],
                    row["order_number"],
                    f"{row['amount']:.2f}",
                    row["status"],
                    row["tg_username"],
                ),
            )

    def export_payments_csv(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV файлы", "*.csv"), ("Все файлы", "*.*")],
            title="Сохранить платежи в CSV",
        )
        if not filename:
            return

        rows = get_payments("")
        import csv

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(
                    [
                        "ID",
                        "Создан",
                        "Номер заказа",
                        "Услуги",
                        "Сумма",
                        "Статус",
                        "TG username",
                        "TG user id",
                        "Ссылка на оплату",
                        "InvoiceID",
                    ]
                )
                for row in rows:
                    writer.writerow(
                        [
                            row["id"],
                            row["created_at"],
                            row["order_number"],
                            row["services"],
                            f"{row['amount']:.2f}",
                            row["status"],
                            row["tg_username"],
                            row["tg_user_id"],
                            row["payment_url"],
                            row["invoice_id"] if row["invoice_id"] is not None else "",
                        ]
                    )
            messagebox.showinfo("Экспорт", "Платежи успешно сохранены в CSV.")
        except Exception as e:
            messagebox.showerror("Экспорт", f"Ошибка при сохранении CSV:\n{e}")

    # ---------- Настройки (скрытое окно, вызывается по Ctrl+Alt+S) ----------

    def open_settings_window(self, event=None):
        # если уже открыто — поднимаем окно
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            return

        win = tk.Toplevel(self)
        win.title("Настройки")
        win.geometry("800x600")
        win.configure(bg=COLOR_BG)
        self._settings_window = win

        self.frame_settings = ttk.Frame(win, padding=16)
        self.frame_settings.pack(fill=tk.BOTH, expand=True)

        self._build_settings_tab()

        def on_close():
            self._settings_window = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

    def _build_settings_tab(self):
        frame = self.frame_settings

        lbl_title = ttk.Label(frame, text="Настройки", font=("Segoe UI Semibold", 14))
        lbl_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        # Robokassa
        roboframe = ttk.LabelFrame(frame, text="Robokassa", padding=12)
        roboframe.grid(row=1, column=0, columnspan=3, sticky="we", pady=(0, 12))
        roboframe.grid_columnconfigure(1, weight=1)

        ttk.Label(roboframe, text="MerchantLogin:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.merchant_entry = ttk.Entry(roboframe, width=30)
        self.merchant_entry.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="Password1:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.password1_entry = ttk.Entry(roboframe, width=30, show="*")
        self.password1_entry.grid(row=1, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="Password2:").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.password2_entry = ttk.Entry(roboframe, width=30, show="*")
        self.password2_entry.grid(row=2, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="Система налогообложения (SNO):").grid(
            row=3, column=0, sticky="e", padx=(0, 8), pady=4
        )
        self.sno_entry = ttk.Entry(roboframe, width=30)
        self.sno_entry.grid(row=3, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="НДС (Tax):").grid(row=4, column=0, sticky="e", padx=(0, 8), pady=4)
        self.tax_entry = ttk.Entry(roboframe, width=30)
        self.tax_entry.grid(row=4, column=1, sticky="we", pady=4)

        ttk.Label(roboframe, text="Email покупателя по умолчанию:").grid(
            row=5, column=0, sticky="e", padx=(0, 8), pady=4
        )
        self.email_entry = ttk.Entry(roboframe, width=30)
        self.email_entry.grid(row=5, column=1, sticky="we", pady=4)

        self.is_test_var = tk.IntVar(value=IS_TEST)
        ttk.Checkbutton(
            roboframe,
            text="Тестовый режим (для старых ссылок Robokassa)",
            variable=self.is_test_var,
        ).grid(row=6, column=1, sticky="w", pady=4)

        # Telegram
        tgframe = ttk.LabelFrame(frame, text="Telegram", padding=12)
        tgframe.grid(row=2, column=0, columnspan=3, sticky="we", pady=(0, 12))
        tgframe.grid_columnconfigure(1, weight=1)

        ttk.Label(tgframe, text="Bot Token:").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.bot_token_entry = ttk.Entry(tgframe, width=40)
        self.bot_token_entry.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(tgframe, text="Admin Telegram ID:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.admin_id_entry = ttk.Entry(tgframe, width=20)
        self.admin_id_entry.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(tgframe, text="Default user chat ID:").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.user_chat_id_entry = ttk.Entry(tgframe, width=20)
        self.user_chat_id_entry.grid(row=2, column=1, sticky="w", pady=4)

        # ResultURL
        resframe = ttk.LabelFrame(frame, text="ResultURL-сервер", padding=12)
        resframe.grid(row=3, column=0, columnspan=3, sticky="we", pady=(0, 12))
        resframe.grid_columnconfigure(1, weight=1)

        ttk.Label(resframe, text="Порт ResultURL-сервера:").grid(
            row=0, column=0, sticky="e", padx=(0, 8), pady=4
        )
        self.result_port_entry = ttk.Entry(resframe, width=10)
        self.result_port_entry.grid(row=0, column=1, sticky="w", pady=4)

        # Firebird
        fbframe = ttk.LabelFrame(frame, text="Firebird (.fdb)", padding=12)
        fbframe.grid(row=4, column=0, columnspan=3, sticky="we", pady=(0, 12))
        fbframe.grid_columnconfigure(1, weight=1)

        ttk.Label(fbframe, text="Путь к базе (.fdb):").grid(row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.fb_path_entry = ttk.Entry(fbframe, width=40)
        self.fb_path_entry.grid(row=0, column=1, sticky="we", pady=4)

        def browse_fdb():
            path = filedialog.askopenfilename(
                title="Выберите базу Firebird",
                filetypes=[("Firebird DB", "*.fdb"), ("All files", "*.*")],
            )
            if path:
                self.fb_path_entry.delete(0, tk.END)
                self.fb_path_entry.insert(0, path)

        ttk.Button(fbframe, text="Обзор", command=browse_fdb).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(fbframe, text="Firebird user:").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.fb_user_entry = ttk.Entry(fbframe, width=30)
        self.fb_user_entry.grid(row=1, column=1, sticky="we", pady=4)

        ttk.Label(fbframe, text="Firebird password:").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=4)
        self.fb_password_entry = ttk.Entry(fbframe, width=30, show="*")
        self.fb_password_entry.grid(row=2, column=1, sticky="we", pady=4)

        # Кнопка сохранения
        btn_save = ttk.Button(
            frame,
            text="Сохранить настройки",
            style="Accent.TButton",
            command=self.save_settings,
        )
        btn_save.grid(row=5, column=0, columnspan=3, sticky="e", pady=(8, 0))

        frame.grid_columnconfigure(0, weight=1)

        self._load_settings_into_form()

    def _load_settings_into_form(self):
        self.merchant_entry.delete(0, tk.END)
        self.merchant_entry.insert(0, MERCHANT_LOGIN)

        self.password1_entry.delete(0, tk.END)
        self.password1_entry.insert(0, PASSWORD1)

        self.password2_entry.delete(0, tk.END)
        self.password2_entry.insert(0, PASSWORD2)

        self.sno_entry.delete(0, tk.END)
        self.sno_entry.insert(0, SHOP_SNO)

        self.tax_entry.delete(0, tk.END)
        self.tax_entry.insert(0, TAX)

        self.email_entry.delete(0, tk.END)
        self.email_entry.insert(0, CUSTOMER_EMAIL)

        self.is_test_var.set(IS_TEST)

        self.bot_token_entry.delete(0, tk.END)
        self.bot_token_entry.insert(0, BOT_TOKEN)

        self.admin_id_entry.delete(0, tk.END)
        if ADMIN_ID:
            self.admin_id_entry.insert(0, str(ADMIN_ID))

        self.user_chat_id_entry.delete(0, tk.END)
        if USER_CHAT_ID:
            self.user_chat_id_entry.insert(0, str(USER_CHAT_ID))

        self.result_port_entry.delete(0, tk.END)
        self.result_port_entry.insert(0, str(RESULT_PORT))

        self.fb_path_entry.delete(0, tk.END)
        self.fb_path_entry.insert(0, APP_CONFIG.get("fb_db_path", ""))

        self.fb_user_entry.delete(0, tk.END)
        self.fb_user_entry.insert(0, APP_CONFIG.get("fb_user", ""))

        self.fb_password_entry.delete(0, tk.END)
        self.fb_password_entry.insert(0, APP_CONFIG.get("fb_password", ""))

    def save_settings(self):
        cfg = {
            "merchant_login": self.merchant_entry.get().strip(),
            "password1": self.password1_entry.get().strip(),
            "password2": self.password2_entry.get().strip(),
            "shop_sno": self.sno_entry.get().strip() or "patent",
            "tax": self.tax_entry.get().strip() or "none",
            "customer_email": self.email_entry.get().strip() or "example@example.com",
            "is_test": int(self.is_test_var.get() or 0),
            "telegram_token": self.bot_token_entry.get().strip(),
            "admin_id": self.admin_id_entry.get().strip(),
            "user_chat_id": self.user_chat_id_entry.get().strip(),
            "result_port": self.result_port_entry.get().strip(),
            "fb_db_path": self.fb_path_entry.get().strip(),
            "fb_user": self.fb_user_entry.get().strip(),
            "fb_password": self.fb_password_entry.get().strip(),
        }

        save_config(cfg)
        messagebox.showinfo("Настройки", "Настройки сохранены.")

# ---------- Splash и запуск ----------

def show_splash(app_cls):
    splash = tk.Tk()
    splash.title("Запуск BONJOUR")
    splash.overrideredirect(True)

    frame = tk.Frame(splash, bg=COLOR_PRIMARY, padx=24, pady=24)
    frame.pack(fill=tk.BOTH, expand=True)

    lbl = tk.Label(
        frame,
        text="BONJOUR — Robokassa Desktop",
        font=("Segoe UI Semibold", 14),
        fg="#F9FAFB",
        bg=COLOR_PRIMARY,
    )
    lbl.pack()

    sub = tk.Label(
        frame,
        text="Загрузка терминала Robokassa…",
        font=("Segoe UI", 9),
        fg="#E5E7EB",
        bg=COLOR_PRIMARY,
    )
    sub.pack(pady=(10, 0))

    splash.update_idletasks()
    w = splash.winfo_width()
    h = splash.winfo_height()
    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    splash.geometry(f"{w}x{h}+{x}+{y}")

    def start_app():
        splash.destroy()
        app = App(APP_CONFIG)
        app.mainloop()

    splash.after(800, start_app)
    splash.mainloop()


def main():
    global APP_CONFIG
    init_db()
    APP_CONFIG = load_or_init_config()
    # стартуем ResultURL-сервер в фоне
    start_result_server_in_background()
    show_splash(App)


if __name__ == "__main__":
    main()
