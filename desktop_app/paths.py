from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
LOGO_PATH = APP_DIR / "logo.png"

DB_PATH = APP_DIR / "data"
DB_PATH.mkdir(exist_ok=True)
DB_FILE = DB_PATH / "payments.sqlite3"

INVOICE_DEBUG_LOG = APP_DIR / "invoice_debug.log"
