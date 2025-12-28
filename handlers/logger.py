from telegram import Update
from telegram.ext import ContextTypes

from utils.config import ASUPAN_STARTUP_CHAT_ID

import html

#log terminal
async def log_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    is_slash = text.startswith("/")
    is_dollar = text.startswith("$")
    if not (is_slash or is_dollar):
        return

    raw = text[1:].split()[0].lower()
    bot_cmds = set(_DOLLAR_CMD_MAP.keys())

    if is_slash and raw not in bot_cmds:
        return

    if is_dollar and raw not in bot_cmds:
        return

    user = msg.from_user
    name = user.first_name if user else "Unknown"
    uid = user.id if user else "—"

    chat = update.effective_chat
    chat_type = chat.type.upper()
    chat_name = chat.title if chat.title else "Private"

    args = text[len(raw) + 1:].strip()

    log_text = (
        f"👀 <b>Command LOG</b>\n"
        f"👤 <b>Nama</b> : {name}\n"
        f"🆔 <b>ID</b> : <code>{uid}</code>\n"
        f"🏷 <b>Chat</b> : {chat_type} | {chat_name}\n"
        f"⌨️ <b>Command</b> : <code>{text}</code>"
    )

    try:
        await context.bot.send_message(
            chat_id=ASUPAN_STARTUP_CHAT_ID,
            text=log_text,
            parse_mode="HTML",
            disable_notification=True
        )
    except Exception:
        pass
        
