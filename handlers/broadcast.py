import json
import os
from telegram import Update
from telegram.ext import ContextTypes
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

    if not context.args:
        return await update.message.reply_text(
            "Usage:\n/broadcast <message>"
        )

    text = " ".join(context.args)
    data = _load()

    sent = 0
    failed = 0

    status = await update.message.reply_text("📣 Broadcasting...")

    for cid in data["users"] + data["groups"]:
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

    await status.edit_text(
        "✅ <b>Broadcast finished</b>\n\n"
        f"📨 Sent: <b>{sent}</b>\n"
        f"❌ Failed: <b>{failed}</b>",
        parse_mode="HTML"
    )