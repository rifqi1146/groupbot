import os
import time
import sqlite3

BROADCAST_DB = "data/broadcast.sqlite3"

def _db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(BROADCAST_DB)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_users (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_groups (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            )
        """)
        con.commit()
    finally:
        con.close()


def _load_groups() -> list[int]:
    _db_init()
    con = sqlite3.connect(BROADCAST_DB)
    try:
        rows = con.execute(
            "SELECT chat_id FROM broadcast_groups WHERE enabled=1"
        ).fetchall()
        return [int(r[0]) for r in rows if r and r[0] is not None]
    finally:
        con.close()