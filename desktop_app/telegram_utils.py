from io import BytesIO

import requests

from .config import APP_CONFIG


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
