from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID

from database.moderation_db import sudo_add, sudo_remove, sudo_list
from .auth import is_owner
from .helpers import (
    mention_html,
    display_name,
    display_name_from_token,
    extract_target_reason,
    resolve_target_user_id,
    resolve_target_user_obj_for_display,
    resolve_user_obj_for_display_by_id,
    reply_in_topic,
)


async def _resolve_target_display(update: Update, context: ContextTypes.DEFAULT_TYPE, target_token: str | None):
    target_id = await resolve_target_user_id(update, context, target_token)
    if not target_id:
        return None, None

    obj = await resolve_target_user_obj_for_display(update, context, target_token)
    if not obj:
        obj = await resolve_user_obj_for_display_by_id(update, context, int(target_id))

    name = display_name(obj) or display_name_from_token(target_token)
    who = mention_html(int(target_id), name)
    return int(target_id), who


async def addsudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if not msg or not update.effective_user:
        return

    if not is_owner(update.effective_user.id):
        return

    has_reply = bool(msg.reply_to_message and msg.reply_to_message.from_user)
    target_token, _ = extract_target_reason(context.args or [], has_reply)

    target_id, who = await _resolve_target_display(update, context, target_token)
    if not target_id:
        return await reply_in_topic(
            msg,
            "Reply to a user or use: <code>/addsudo user_id</code> / <code>/addsudo @username</code>",
            parse_mode="HTML",
        )

    sudo_add(int(target_id))

    return await reply_in_topic(
        msg,
        "<b>Added sudo</b>\n"
        f"<b>User:</b> {who}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def rmsudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if not msg or not update.effective_user:
        return

    if not is_owner(update.effective_user.id):
        return

    has_reply = bool(msg.reply_to_message and msg.reply_to_message.from_user)
    target_token, _ = extract_target_reason(context.args or [], has_reply)

    target_id, who = await _resolve_target_display(update, context, target_token)
    if not target_id:
        return await reply_in_topic(
            msg,
            "Reply to a user or use: <code>/rmsudo user_id</code> / <code>/rmsudo @username</code>",
            parse_mode="HTML",
        )

    if int(target_id) in OWNER_ID:
        return await reply_in_topic(msg, "Cannot remove owner from sudo/owner privileges.")

    sudo_remove(int(target_id))

    return await reply_in_topic(
        msg,
        "<b>Removed sudo</b>\n"
        f"<b>User:</b> {who}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def sudolist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if not msg or not update.effective_user:
        return

    if not is_owner(update.effective_user.id):
        return

    ids = sudo_list()
    if not ids:
        return await reply_in_topic(
            msg,
            "<b>Sudo users:</b>\n<code>(empty)</code>",
            parse_mode="HTML",
        )

    lines = ["<b>Sudo users:</b>"]
    for uid in ids:
        obj = await resolve_user_obj_for_display_by_id(update, context, int(uid))
        name = display_name(obj) or f"User {uid}"
        who = mention_html(int(uid), name)
        lines.append(f"• {who} — <code>{uid}</code>")

    return await reply_in_topic(
        msg,
        "\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )