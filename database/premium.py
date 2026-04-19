import os
import time
import sqlite3

CACA_DB_PATH = "data/caca.sqlite3"
_PREMIUM_USERS = set()
_INITIALIZED = False

def _db():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(CACA_DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def init():
    global _PREMIUM_USERS, _INITIALIZED
    con = _db()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id INTEGER PRIMARY KEY,
                added_at REAL NOT NULL
            )
        """)
        con.commit()
        cur = con.execute("SELECT user_id FROM premium_users")
        rows = cur.fetchall()
        _PREMIUM_USERS = {int(r[0]) for r in rows if r and r[0] is not None}
        _INITIALIZED = True
    finally:
        con.close()

def init_if_needed():
    if not _INITIALIZED:
        init()

def add(uid: int):
    global _PREMIUM_USERS
    uid = int(uid)
    init_if_needed()
    con = _db()
    try:
        con.execute("INSERT OR REPLACE INTO premium_users (user_id, added_at) VALUES (?, ?)", (uid, float(time.time())))
        con.commit()
        _PREMIUM_USERS.add(uid)
    finally:
        con.close()

def remove(uid: int):
    global _PREMIUM_USERS
    uid = int(uid)
    init_if_needed()
    con = _db()
    try:
        con.execute("DELETE FROM premium_users WHERE user_id=?", (uid,))
        con.commit()
        _PREMIUM_USERS.discard(uid)
    finally:
        con.close()

def list_users() -> list[int]:
    init_if_needed()
    con = _db()
    try:
        cur = con.execute("SELECT user_id FROM premium_users ORDER BY added_at DESC")
        rows = cur.fetchall()
        return [int(r[0]) for r in rows if r and r[0] is not None]
    finally:
        con.close()

def check(uid: int) -> bool:
    init_if_needed()
    return int(uid) in _PREMIUM_USERS

def cache_set() -> set[int]:
    init_if_needed()
    return set(_PREMIUM_USERS)

def load_set() -> set[int]:
    init_if_needed()
    con = _db()
    try:
        cur = con.execute("SELECT user_id FROM premium_users")
        rows = cur.fetchall()
        return {int(r[0]) for r in rows if r and r[0] is not None}
    finally:
        con.close()