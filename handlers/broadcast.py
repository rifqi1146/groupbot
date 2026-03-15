import os
import time
import uuid
import sqlite3
import asyncio

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import RetryAfter
from utils.config import OWNER_ID

BROADCAST_DB = "data/broadcast.sqlite3"
BROADCAST_PENDING = {}


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


def _broadcast_keyboard(bid: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Send", callback_data=f"broadcast:send:{bid}"),
            InlineKeyboardButton("Cancel", callback_data=f"broadcast:cancel:{bid}"),
        ]
    ])


def _cleanup_pending(max_age: int = 3600):
    now = time.time()
    expired = [
        key for key, value in BROADCAST_PENDING.items()
        if now - float(value.get("ts", 0)) > max_age
    ]
    for key in expired:
        BROADCAST_PENDING.pop(key, None)


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message

    if not user or user.id not in OWNER_ID:
        return

    if not msg or not msg.text:
        return

    raw_text = msg.text
    text = raw_text[len("/broadcast"):].lstrip() if raw_text.startswith("/broadcast") else raw_text

    if not text:
        return await msg.reply_text("Message is empty.")

    _cleanup_pending()

    bid = uuid.uuid4().hex[:10]
    BROADCAST_PENDING[bid] = {
        "owner_id": user.id,
        "text": text,
        "ts": time.time(),
    }

    preview = (
        "<b>Broadcast Preview</b>\n\n"
        f"{text}\n\n"
        "<i>This message has not been sent yet.</i>"
    )

    await msg.reply_text(
        preview,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=_broadcast_keyboard(bid),
    )


async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return

    parts = q.data.split(":", 2)
    if len(parts) != 3 or parts[0] != "broadcast":
        return

    _, action, bid = parts
    user = q.from_user

    data = BROADCAST_PENDING.get(bid)
    if not data:
        await q.answer("Broadcast request expired.", show_alert=True)
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    if not user or user.id != data["owner_id"] or user.id not in OWNER_ID:
        return await q.answer("This is not your broadcast.", show_alert=True)

    if action == "cancel":
        BROADCAST_PENDING.pop(bid, None)
        await q.answer("Broadcast cancelled.")
        return await q.edit_message_text(
            "<b>Broadcast cancelled</b>",
            parse_mode="HTML",
        )

    if action != "send":
        return await q.answer()

    await q.answer("Starting broadcast...")
    text = data["text"]

    await q.edit_message_text(
        "<b>Broadcast started...</b>\n\n"
        f"{text}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    sent = 0
    failed = 0
    targets = _get_targets()

    for cid in targets:
        try:
            await context.bot.send_message(
                chat_id=cid,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            sent += 1
            await asyncio.sleep(0.7)

        except RetryAfter as e:
            await asyncio.sleep(float(getattr(e, "retry_after", 1)) + 1)
            try:
                await context.bot.send_message(
                    chat_id=cid,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                sent += 1
            except Exception:
                failed += 1

        except Exception:
            failed += 1
            await asyncio.sleep(0.7)

    BROADCAST_PENDING.pop(bid, None)

    await q.edit_message_text(
        "<b>Broadcast finished</b>\n\n"
        f"Sent: <b>{sent}</b>\n"
        f"Failed: <b>{failed}</b>\n\n"
        "<b>Message:</b>\n"
        f"{text}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


try:
    _db_init()
except Exception:
    pass