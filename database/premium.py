import os
import time
import sqlite3
from utils.config import OWNER_ID

CACA_DB_PATH = "data/caca.sqlite3"
_PREMIUM_USERS = set()

def _db():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(CACA_DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def init():
    global _PREMIUM_USERS
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
    finally:
        con.close()

def init_if_needed():
    if not _PREMIUM_USERS and not _table_exists():
        init()
    elif not _PREMIUM_USERS:
        init()

def _table_exists() -> bool:
    con = _db()
    try:
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='premium_users' LIMIT 1")
        return cur.fetchone() is not None
    finally:
        con.close()

def add(uid: int):
    global _PREMIUM_USERS
    uid = int(uid)
    init_if_needed()
    if uid in OWNER_ID:
        return
    con = _db()
    try:
        con.execute(
            "INSERT OR REPLACE INTO premium_users (user_id, added_at) VALUES (?, ?)",
            (uid, float(time.time())),
        )
        con.commit()
        _PREMIUM_USERS.add(uid)
    finally:
        con.close()

def remove(uid: int):
    global _PREMIUM_USERS
    uid = int(uid)
    init_if_needed()
    if uid in OWNER_ID:
        return
    con = _db()
    try:
        con.execute("DELETE FROM premium_users WHERE user_id=?", (uid,))
        con.commit()
        _PREMIUM_USERS.discard(uid)
    finally:
        con.close()

def list_users() -> list[int]:
    init_if_needed()
    db_ids = []
    con = _db()
    try:
        cur = con.execute("SELECT user_id FROM premium_users ORDER BY added_at DESC")
        rows = cur.fetchall()
        db_ids = [int(r[0]) for r in rows if r and r[0] is not None and int(r[0]) not in OWNER_ID]
    finally:
        con.close()
    return list(dict.fromkeys([*OWNER_ID, *db_ids]))

def check(uid: int) -> bool:
    init_if_needed()
    uid = int(uid)
    return uid in OWNER_ID or uid in _PREMIUM_USERS

def cache_set() -> set[int]:
    init_if_needed()
    return set(_PREMIUM_USERS) | {int(x) for x in OWNER_ID}

def load_set() -> set[int]:
    init_if_needed()
    con = _db()
    try:
        cur = con.execute("SELECT user_id FROM premium_users")
        rows = cur.fetchall()
        db_ids = {int(r[0]) for r in rows if r and r[0] is not None}
        return db_ids | {int(x) for x in OWNER_ID}
    finally:
        con.close()