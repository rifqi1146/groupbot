import os
import time
import sqlite3

CACA_DB_PATH = "data/caca.sqlite3"

def _db():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(CACA_DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def init_premium_db():
    con = _db()
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id INTEGER PRIMARY KEY,
                added_at REAL NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()

def premium_add(user_id: int):
    init_premium_db()
    con = _db()
    try:
        con.execute(
            "INSERT OR REPLACE INTO premium_users (user_id, added_at) VALUES (?, ?)",
            (int(user_id), float(time.time())),
        )
        con.commit()
    finally:
        con.close()

def premium_del(user_id: int):
    init_premium_db()
    con = _db()
    try:
        con.execute("DELETE FROM premium_users WHERE user_id=?", (int(user_id),))
        con.commit()
    finally:
        con.close()

def premium_list() -> list[int]:
    init_premium_db()
    con = _db()
    try:
        cur = con.execute("SELECT user_id FROM premium_users ORDER BY added_at DESC")
        rows = cur.fetchall()
        return [int(r[0]) for r in rows if r and r[0] is not None]
    finally:
        con.close()

def premium_load_set() -> set[int]:
    init_premium_db()
    con = _db()
    try:
        cur = con.execute("SELECT user_id FROM premium_users")
        rows = cur.fetchall()
        return {int(r[0]) for r in rows if r and r[0] is not None}
    finally:
        con.close()

def is_premium(user_id: int, cache: set[int] | None = None) -> bool:
    uid = int(user_id)
    if cache is not None:
        return uid in cache
    init_premium_db()
    con = _db()
    try:
        cur = con.execute("SELECT 1 FROM premium_users WHERE user_id=? LIMIT 1", (uid,))
        return cur.fetchone() is not None
    finally:
        con.close()
