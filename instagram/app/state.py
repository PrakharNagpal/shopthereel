import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from app.config import settings

USER_COLUMNS = (
    "enrollment_id",
    "budget_per_order",
    "budget_currency",
    "budget_monthly",
    "max_orders_per_day",
    "confirm_above",
    "buying_paused",
    "awaiting",
    "pending_quote_amount",
    "pending_product_name",
    "enrollment_link_sent_at",
    "shipping_json",
    "pending_product_id",
    "pending_option_ids",
    "pending_variant_id",
    "pending_quote_id",
    "pending_checkout_id",
)

NEW_COLUMNS = (
    ("budget_monthly", "REAL"),
    ("max_orders_per_day", "INTEGER"),
    ("confirm_above", "REAL"),
    ("buying_paused", "INTEGER"),
    ("awaiting", "TEXT"),
    ("pending_quote_amount", "REAL"),
    ("pending_product_name", "TEXT"),
    ("enrollment_link_sent_at", "TEXT"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    igsid TEXT PRIMARY KEY,
    enrollment_id TEXT,
    budget_per_order REAL,
    budget_currency TEXT,
    budget_monthly REAL,
    max_orders_per_day INTEGER,
    confirm_above REAL,
    buying_paused INTEGER,
    awaiting TEXT,
    pending_quote_amount REAL,
    pending_product_name TEXT,
    enrollment_link_sent_at TEXT,
    shipping_json TEXT,
    pending_product_id TEXT,
    pending_option_ids TEXT,
    pending_variant_id TEXT,
    pending_quote_id TEXT,
    pending_checkout_id TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS recognitions (reel_id TEXT PRIMARY KEY, result_json TEXT);
CREATE TABLE IF NOT EXISTS orders (
    checkout_id TEXT PRIMARY KEY, igsid TEXT, order_id TEXT,
    final_amount REAL, currency TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS seen_messages (mid TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS callbacks (id TEXT PRIMARY KEY, payload TEXT);
"""


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for col, typ in NEW_COLUMNS:  # bring older DB files up to date
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # column already exists
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_user(igsid: str) -> dict:
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE igsid=?", (igsid,)).fetchone()
    return dict(row) if row else {"igsid": igsid}


def update_user(igsid: str, **fields) -> None:
    bad = set(fields) - set(USER_COLUMNS)
    if bad:
        raise ValueError(f"unknown user columns: {bad}")
    with _db() as c:
        c.execute("INSERT OR IGNORE INTO users (igsid) VALUES (?)", (igsid,))
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(
                f"UPDATE users SET {sets}, updated_at=? WHERE igsid=?",
                (*fields.values(), _now(), igsid),
            )


def get_recognition(reel_id: str) -> Optional[dict]:
    with _db() as c:
        row = c.execute(
            "SELECT result_json FROM recognitions WHERE reel_id=?", (reel_id,)
        ).fetchone()
    return json.loads(row["result_json"]) if row else None


def save_recognition(reel_id: str, result: dict) -> None:
    with _db() as c:
        c.execute(
            "INSERT OR REPLACE INTO recognitions VALUES (?, ?)", (reel_id, json.dumps(result))
        )


def save_order(checkout_id: str, igsid: str, order_id, amount, currency) -> None:
    with _db() as c:
        c.execute(
            "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?)",
            (checkout_id, igsid, order_id, amount, currency, _now()),
        )


def first_time_seen(mid: str) -> bool:
    """True the first time a message id is seen; False for webhook retries."""
    with _db() as c:
        cur = c.execute("INSERT OR IGNORE INTO seen_messages VALUES (?)", (mid,))
        return cur.rowcount == 1


def month_spent(igsid: str) -> float:
    """Total of this user's completed orders since the start of the current UTC month."""
    start = datetime.now(timezone.utc).strftime("%Y-%m-01")
    with _db() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(final_amount), 0) FROM orders WHERE igsid=? AND created_at>=?",
            (igsid, start),
        ).fetchone()
    return float(row[0])


def orders_today(igsid: str) -> int:
    start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _db() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM orders WHERE igsid=? AND created_at>=?", (igsid, start)
        ).fetchone()
    return int(row[0])


def put_callback(payload: str) -> str:
    """Telegram callback_data is capped at 64 bytes, our payloads are longer: store, send an id."""
    import hashlib

    cid = hashlib.sha1(payload.encode()).hexdigest()[:16]
    with _db() as c:
        c.execute("INSERT OR IGNORE INTO callbacks VALUES (?, ?)", (cid, payload))
    return cid


def get_callback(cid: str) -> Optional[str]:
    with _db() as c:
        row = c.execute("SELECT payload FROM callbacks WHERE id=?", (cid,)).fetchone()
    return row["payload"] if row else None
