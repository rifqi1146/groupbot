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
        con.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_user_cache (
                username TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
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


def cache_username(user_id: int, username: str | None):
    u = (username or "").strip().lstrip("@").lower()
    if not u:
        return
    con = _db()
    try:
        now = float(time.time())
        con.execute("BEGIN")
        con.execute(
            """
            INSERT INTO broadcast_user_cache (username, user_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
              user_id=excluded.user_id,
              updated_at=excluded.updated_at
            """,
            (u, int(user_id), now),
        )
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
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

    u = update.effective_user
    if u and getattr(u, "id", None):
        cache_username(int(u.id), getattr(u, "username", None))

    msg = update.message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        ru = msg.reply_to_message.from_user
        cache_username(int(ru.id), getattr(ru, "username", None))


try:
    _db_init()
except Exception:
    pass