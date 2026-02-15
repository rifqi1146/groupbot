import os
import sqlite3
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID

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


async def groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    bot = context.bot

    if not msg or not user or user.id not in OWNER_ID:
        return

    group_ids = _load_groups()
    if not group_ids:
        return await msg.reply_text("The bot is not registered in any groups.")

    lines = ["<b>Current Bot Groups</b>\n"]

    for gid in group_ids:
        try:
            chat = await bot.get_chat(gid)
            title = chat.title or "Unknown"
            lines.append(f"• {title} <code>{gid}</code>")
        except Exception:
            lines.append(f"• <code>{gid}</code>")

    await msg.reply_text("\n".join(lines), parse_mode="HTML")


try:
    _db_init()
except Exception:
    pass