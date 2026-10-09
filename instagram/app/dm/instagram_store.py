import json
import sqlite3
from app.config import settings


def db():
    c=sqlite3.connect(settings.db_path)
    c.execute('CREATE TABLE IF NOT EXISTS instagram_sessions (uid TEXT PRIMARY KEY, data TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS instagram_notified (checkout TEXT PRIMARY KEY)')
    c.commit()
    return c


def get(uid):
    with db() as c:row=c.execute('SELECT data FROM instagram_sessions WHERE uid=?',(uid,)).fetchone()
    return json.loads(row[0]) if row else {}


def save(uid,data):
    with db() as c:c.execute('INSERT OR REPLACE INTO instagram_sessions VALUES (?,?)',(uid,json.dumps(data)))


def first_notice(checkout):
    with db() as c:return c.execute('INSERT OR IGNORE INTO instagram_notified VALUES (?)',(checkout,)).rowcount==1


def pending():
    with db() as c:rows=c.execute('SELECT uid,data FROM instagram_sessions').fetchall()
    return [(uid,json.loads(data)) for uid,data in rows if json.loads(data).get('phase') in ('payment','card')]
