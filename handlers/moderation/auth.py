import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.config import OWNER_ID
from database.moderation_db import sudo_is

log = logging.getLogger(__name__)


def is_owner(user_id: int | None) -> bool:
    return bool(user_id and user_id in OWNER_ID)


async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return False

    if is_owner(user.id) or sudo_is(user.id):
        return True

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        log.warning(
            "Failed to check moderation admin status | chat_id=%s user_id=%s err=%s",
            getattr(chat, "id", None),
            getattr(user, "id", None),
            e,
        )
        return False