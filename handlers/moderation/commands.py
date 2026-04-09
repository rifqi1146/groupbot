from telegram import Update
from telegram.ext import ContextTypes

from database.moderation_db import moderation_is_enabled, moderation_set
from .auth import is_admin_or_owner
from .helpers import reply_in_topic


async def moderation_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat

    if not msg or not chat:
        return

    if chat.type not in ("group", "supergroup"):
        return await reply_in_topic(msg, "This command can only be used in groups.")

    if not await is_admin_or_owner(update, context):
        return await reply_in_topic(msg, "You are not an admin.")

    arg = (context.args[0].lower().strip() if context.args else "")

    if arg == "enable":
        moderation_set(chat.id, True)
        return await reply_in_topic(
            msg,
            "Moderation is now <b>ENABLED</b> in this group.",
            parse_mode="HTML",
        )

    if arg == "disable":
        moderation_set(chat.id, False)
        return await reply_in_topic(
            msg,
            "Moderation is now <b>DISABLED</b> in this group.",
            parse_mode="HTML",
        )

    if arg == "status":
        status = "ENABLED" if moderation_is_enabled(chat.id) else "DISABLED"
        return await reply_in_topic(
            msg,
            f"Moderation status: <b>{status}</b>",
            parse_mode="HTML",
        )

    return await reply_in_topic(
        msg,
        "<b>Moderation</b>\n\n"
        "<code>/moderation enable</code>\n"
        "<code>/moderation disable</code>\n"
        "<code>/moderation status</code>\n\n"
        "<b>Actions</b>\n"
        "<code>/ban @username/id 7d [reason]</code>\n"
        "<code>/unban @username/id</code>\n"
        "<code>/mute @username/id 7d [reason]</code>\n"
        "<code>/unmute @username/id </code>\n"
        "<code>/kick @username/id [reason]</code>\n\n"
        "<b>Owner</b>\n"
        "<code>/addsudo @username/id</code>\n"
        "<code>/rmsudo @username/id</code>\n"
        "<code>/sudolist show all sudo</code>",
        parse_mode="HTML",
    )