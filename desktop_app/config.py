import json
from typing import Any

from .paths import CONFIG_PATH

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

APP_CONFIG: dict[str, Any] = {}


def get_default_config() -> dict[str, Any]:
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


def apply_config_to_globals(cfg: dict[str, Any]) -> None:
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


def load_or_init_config() -> dict[str, Any]:
    cfg = get_default_config()
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                cfg.update(stored)
        except Exception:
            pass

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


def save_config(cfg: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    apply_config_to_globals(cfg)
