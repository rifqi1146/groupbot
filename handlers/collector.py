import os
import time
import sqlite3
from telegram import Update
from telegram.ext import ContextTypes

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


def _db():
    _db_init()
    return sqlite3.connect(BROADCAST_DB)


def _add_user(chat_id: int):
    con = _db()
    try:
        now = time.time()
        con.execute("""
            INSERT INTO broadcast_users (chat_id, enabled, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
              enabled=1,
              updated_at=excluded.updated_at
        """, (int(chat_id), float(now)))
        con.commit()
    finally:
        con.close()


def _add_group(chat_id: int):
    con = _db()
    try:
        now = time.time()
        con.execute("""
            INSERT INTO broadcast_groups (chat_id, enabled, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
              enabled=1,
              updated_at=excluded.updated_at
        """, (int(chat_id), float(now)))
        con.commit()
    finally:
        con.close()


async def collect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return

    if chat.type == "private":
        _add_user(chat.id)
    else:
        _add_group(chat.id)


try:
    _db_init()
except Exception:
    pass