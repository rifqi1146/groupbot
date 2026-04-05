import os
import html
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID
from database.groups_db import _db_init, _load_groups

async def groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    bot = context.bot

    if not msg or not user or user.id not in OWNER_ID:
        return

    group_ids = _load_groups()
    if not group_ids:
        return await msg.reply_text("📭 <b>No groups recorded yet.</b>", parse_mode="HTML")

    total = len(group_ids)
    lines = [f"📋 <b>Current Bot Groups</b> — <b>{total}</b>\n"]

    for gid in group_ids:
        try:
            chat = await bot.get_chat(gid)
            title = html.escape(chat.title or "Unknown")
            username = getattr(chat, "username", None)

            if username:
                link = f"https://t.me/{html.escape(username)}"
                lines.append(f"• 🔗 <a href=\"{link}\">{title}</a> <code>{gid}</code>")
            else:
                lines.append(f"• 🏷️ {title} <code>{gid}</code>")

        except Exception:
            lines.append(f"• ⚠️ <code>{gid}</code>")

    await msg.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


try:
    _db_init()
except Exception:
    pass