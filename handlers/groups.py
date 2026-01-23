from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID
from utils.storage import load_groups

async def groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user

    if not user or user.id not in OWNER_ID:
        return await msg.reply_text("❌ Owner only.")

    groups = load_groups()

    if not groups:
        return await msg.reply_text("📭 Bot belum ada di grup manapun.")

    lines = ["📋 <b>Bot ada di grup berikut:</b>\n"]

    for g in groups.values():
        lines.append(f"• {g['title']}")

    await msg.reply_text(
        "\n".join(lines),
        parse_mode="HTML"
    )