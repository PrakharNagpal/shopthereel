"""Independent web-session quote and checkout ownership, persisted in this clone's DB."""
import json
import sqlite3
from app.config import settings


def connect():
    c = sqlite3.connect(settings.db_path)
    c.execute('CREATE TABLE IF NOT EXISTS web_quotes (id TEXT PRIMARY KEY, owner TEXT, payload TEXT, checkout TEXT)')
    c.commit()
    return c


def save_quote(uid: str, quote: dict) -> None:
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO web_quotes VALUES (?,?,?,NULL)', (quote['id'], uid, json.dumps(quote)))


def get_quote(uid: str, qid: str):
    with connect() as c:
        row = c.execute('SELECT payload,checkout FROM web_quotes WHERE id=? AND owner=?', (qid, uid)).fetchone()
    return (json.loads(row[0]), row[1]) if row else None


def save_checkout(uid: str, qid: str, cid: str):
    with connect() as c:
        c.execute('UPDATE web_quotes SET checkout=? WHERE id=? AND owner=?', (cid, qid, uid))


def owns_checkout(uid: str, cid: str):
    with connect() as c:
        return c.execute('SELECT 1 FROM web_quotes WHERE owner=? AND checkout=?', (uid, cid)).fetchone() is not None


def save_handoff(result: dict) -> str:
    import secrets,time
    token=secrets.token_urlsafe(24)
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS web_handoffs (id TEXT PRIMARY KEY, payload TEXT, expires REAL)')
        c.execute('DELETE FROM web_handoffs WHERE expires < ?', (time.time(),))
        c.execute('INSERT INTO web_handoffs VALUES (?,?,?)',(token,json.dumps(result),time.time()+86400))
    return token


def get_handoff(token: str):
    import time
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS web_handoffs (id TEXT PRIMARY KEY, payload TEXT, expires REAL)')
        row=c.execute('SELECT payload FROM web_handoffs WHERE id=? AND expires>?',(token,time.time())).fetchone()
    return json.loads(row[0]) if row else None
