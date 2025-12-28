from telegram import Update
from telegram.ext import ContextTypes
import html

from utils.config import ASUPAN_STARTUP_CHAT_ID
from utils.commands import BOT_COMMANDS


async def log_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    if not (text.startswith("/") or text.startswith("$")):
        return

    cmd = text[1:].split()[0].lower()
    if cmd not in BOT_COMMANDS:
        return

    user = msg.from_user
    name = user.first_name if user else "Unknown"
    uid = user.id if user else "—"

    chat = update.effective_chat
    chat_type = chat.type.upper()
    chat_name = chat.title or "Private"

    log_text = (
        f"👀 <b>Command LOG</b>\n"
        f"👤 <b>Nama</b> : {html.escape(name)}\n"
        f"🆔 <b>ID</b> : <code>{uid}</code>\n"
        f"🏷 <b>Chat</b> : {chat_type} | {html.escape(chat_name)}\n"
        f"⌨️ <b>Command</b> : <code>{html.escape(text)}</code>"
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
