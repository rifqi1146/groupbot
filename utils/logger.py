from telegram import Update
from telegram.ext import ContextTypes
import html

from utils.config import LOG_CHAT_ID
from utils.commands import BOT_COMMANDS


async def log_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.from_user:
        return

    user = msg.from_user
    name = user.first_name or "Unknown"
    uid = user.id

    chat = update.effective_chat
    chat_type = chat.type.upper()
    chat_name = chat.title or "Private"

    text = (msg.text or "").strip()
    is_command = text.startswith("/") or text.startswith("$")

    if is_command:
        cmd = text[1:].split()[0].split("@")[0].lower()
        if cmd not in BOT_COMMANDS:
            return
        title = "<b>Command Log</b>"
        content = f"<code>{html.escape(text)}</code>"

    elif msg.reply_to_message:
        bot = context.bot
        replied = msg.reply_to_message
        if not replied.from_user or replied.from_user.id != bot.id:
            return
        title = "<b>Reply Log</b>"
        content = html.escape(text) if text else "<i>(non-text message)</i>"

    else:
        return

    log_text = (
        f"{title}\n"
        f"<b>Name</b> : {html.escape(name)}\n"
        f"<b>User ID</b> : <code>{uid}</code>\n"
        f"<b>Chat</b> : {chat_type} | {html.escape(chat_name)}\n"
        f"<b>Message</b> : {content}"
    )

    try:
        await context.bot.send_message(
            chat_id=LOG_CHAT_ID,
            text=log_text,
            parse_mode="HTML",
            disable_notification=True
        )
    except Exception:
        pass