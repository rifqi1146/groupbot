import os
import sqlite3
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import RetryAfter
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


def _get_targets() -> list[int]:
    _db_init()
    con = sqlite3.connect(BROADCAST_DB)
    try:
        users = con.execute(
            "SELECT chat_id FROM broadcast_users WHERE enabled=1"
        ).fetchall()
        groups = con.execute(
            "SELECT chat_id FROM broadcast_groups WHERE enabled=1"
        ).fetchall()
        out = []
        out.extend(int(r[0]) for r in users if r and r[0] is not None)
        out.extend(int(r[0]) for r in groups if r and r[0] is not None)
        return out
    finally:
        con.close()


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_ID:
        return

    msg = update.message
    if not msg or not msg.text:
        return

    raw_text = msg.text
    text = raw_text[len("/broadcast"):].lstrip() if raw_text.startswith("/broadcast") else raw_text

    if not text:
        return await msg.reply_text("Message is empty.")

    sent = 0
    failed = 0

    status = await msg.reply_text("Broadcasting...")

    targets = _get_targets()

    for cid in targets:
        try:
            await context.bot.send_message(
                chat_id=cid,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            sent += 1
            await asyncio.sleep(0.7)

        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await context.bot.send_message(
                    chat_id=cid,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                sent += 1
            except Exception:
                failed += 1

        except Exception:
            failed += 1
            await asyncio.sleep(0.7)

    await status.edit_text(
        "<b>Broadcast finished</b>\n\n"
        f"Sent: <b>{sent}</b>\n"
        f"Failed: <b>{failed}</b>",
        parse_mode="HTML"
    )


try:
    _db_init()
except Exception:
    pass