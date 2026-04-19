import asyncio
import html
from telegram import Update
from telegram.ext import ContextTypes

from utils.config import OWNER_ID
from database import premium
from database import caca_db
from utils import caca_memory

def extract_user_id_from_args(args: list[str]) -> int | None:
    if not args:
        return None
    raw = (args[0] or "").strip()
    if not raw:
        return None
    if raw.startswith("@"):
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits:
        try:
            return int(digits)
        except Exception:
            return None
    return None

async def resolve_target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    msg = update.message
    if not msg:
        return None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        try:
            return int(msg.reply_to_message.from_user.id)
        except Exception:
            pass
    if len(context.args) >= 2:
        target = (context.args[1] or "").strip()
        if target.startswith("@"):
            uname = target[1:]
            try:
                chat = await context.bot.get_chat(f"@{uname}")
                if chat and getattr(chat, "id", None):
                    return int(chat.id)
            except Exception:
                return None
        uid = extract_user_id_from_args([target])
        if uid:
            return uid
    return None

async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    if not msg or not user or user.id not in OWNER_ID:
        return

    if not context.args:
        return await msg.reply_text(
            "<b>Premium Control</b>\n\n"
            "<code>/premium add &lt;user_id | @username&gt;</code>\n"
            "<code>/premium del &lt;user_id | @username&gt;</code>\n"
            "<code>/premium list</code>",
            parse_mode="HTML"
        )

    cmd = (context.args[0] or "").lower().strip()

    if cmd in ("add", "del"):
        uid = await resolve_target_user_id(update, context)
        if not uid:
            return await msg.reply_text(
                "<b>Target user not found.</b>\n\n"
                "Use:\n"
                "• <code>/premium add 123456</code>\n"
                "• <code>/premium add @username</code>\n"
                "• Or reply to their message with <code>/premium add</code>",
                parse_mode="HTML"
            )

        if cmd == "add":
            if uid in OWNER_ID:
                return await msg.reply_text(
                    f"<b>User is owner.</b>\n<code>{uid}</code> is always premium automatically.",
                    parse_mode="HTML"
                )
            premium.add(uid)
            return await msg.reply_text(
                f"<b>Premium added</b>: <code>{uid}</code>",
                parse_mode="HTML"
            )

        if uid in OWNER_ID:
            return await msg.reply_text(
                f"<b>Cannot remove owner premium.</b>\n<code>{uid}</code> is always premium automatically.",
                parse_mode="HTML"
            )

        premium.remove(uid)
        caca_db.remove_mode(uid)
        await caca_memory.clear(uid)
        await caca_memory.clear_last_message_id(uid)
        return await msg.reply_text(
            f"<b>Premium removed</b>: <code>{uid}</code>",
            parse_mode="HTML"
        )

    if cmd == "list":
        ids = premium.list_users()
        if not ids:
            return await msg.reply_text("No premium users yet.", parse_mode="HTML")

        owner_lines = []
        premium_lines = []

        for uid in ids[:200]:
            try:
                u = await context.bot.get_chat(uid)
                name = html.escape(getattr(u, "full_name", None) or getattr(u, "first_name", None) or "Unknown User")
            except Exception:
                name = "Unknown User"

            line = f"• <a href=\"tg://user?id={uid}\">{name}</a> <code>{uid}</code>"
            if uid in OWNER_ID:
                owner_lines.append(f"{line} <b>[OWNER]</b>")
            else:
                premium_lines.append(line)

        text = ["👑 <b>Premium Users</b>"]
        if owner_lines:
            text.append("\n<b>Owner</b>")
            text.extend(owner_lines)
        if premium_lines:
            text.append("\n<b>Additional Premium</b>")
            text.extend(premium_lines)

        return await msg.reply_text(
            "\n".join(text),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    return await msg.reply_text(
        "<b>Unknown command.</b>\n\n"
        "Use:\n"
        "<code>/premium add</code>\n"
        "<code>/premium del</code>\n"
        "<code>/premium list</code>",
        parse_mode="HTML"
    )