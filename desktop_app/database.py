import sqlite3
from datetime import datetime

from .paths import DB_FILE

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


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(CREATE_TABLE_SQL)
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
            """,
        )

    rows = cur.fetchall()
    conn.close()
    return rows
