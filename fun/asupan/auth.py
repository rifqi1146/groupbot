from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID


async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return False

    if user.id in OWNER_ID:
        return True

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False