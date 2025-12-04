import asyncio
import threading
import sqlite3
from typing import Any

import requests

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:  # pragma: no cover - fallback for missing dependency
    web = None
    AIOHTTP_AVAILABLE = False

from .database import get_last_payment, update_payment_status


class ResultHandler:
    def __init__(self, cfg: dict[str, Any]):
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


def start_result_server_in_background(cfg: dict[str, Any]):
    if not AIOHTTP_AVAILABLE:
        print("[RESULT] aiohttp не установлен, ResultURL-сервер не запущен")
        return

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
