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

from desktop_app.config import APP_CONFIG, load_or_init_config
from desktop_app.database import init_db
from desktop_app.gui import App, show_splash
from desktop_app.result_server import start_result_server_in_background


def main():
    global APP_CONFIG
    init_db()
    APP_CONFIG = load_or_init_config()
    start_result_server_in_background(APP_CONFIG)
    show_splash(App)


if __name__ == "__main__":
    main()
