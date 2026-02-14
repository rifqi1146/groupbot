import json
import os
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID

BROADCAST_FILE = "data/broadcast_chats.json"


def _load_groups():
    if not os.path.exists(BROADCAST_FILE):
        return []
    with open(BROADCAST_FILE, "r") as f:
        data = json.load(f)
    return data.get("groups", [])


async def groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    bot = context.bot

    if not user or user.id not in OWNER_ID:
        return

    group_ids = _load_groups()
    if not group_ids:
        return await msg.reply_text("📭 The bot is not registered in any groups.")

    lines = ["<b>📋 Current Bot Groups</b>\n"]

    for gid in group_ids:
        try:
            chat = await bot.get_chat(gid)
            title = chat.title or "Unknown"
            lines.append(f"• {title}")
        except Exception:
            continue

    await msg.reply_text(
        "\n".join(lines),
        parse_mode="HTML"
    )