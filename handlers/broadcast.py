import json
import os
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import RetryAfter
from utils.config import OWNER_ID

BROADCAST_FILE = "data/broadcast_chats.json"


def _load():
    if not os.path.exists(BROADCAST_FILE):
        return {"users": [], "groups": []}
    with open(BROADCAST_FILE, "r") as f:
        return json.load(f)


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    msg = update.message
    if not msg or not msg.text:
        return

    raw_text = msg.text
    text = raw_text[len("/broadcast"):].lstrip() if raw_text.startswith("/broadcast") else raw_text

    if not text:
        return await msg.reply_text("❌ Message is empty.")

    data = _load()
    sent = 0
    failed = 0

    status = await msg.reply_text("📣 Broadcasting...")

    targets = data["users"] + data["groups"]

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
        "✅ <b>Broadcast finished</b>\n\n"
        f"📨 Sent: <b>{sent}</b>\n"
        f"❌ Failed: <b>{failed}</b>",
        parse_mode="HTML"
    )