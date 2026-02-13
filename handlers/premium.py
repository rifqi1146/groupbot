import asyncio
import html
from telegram import Update
from telegram.ext import ContextTypes

from utils.config import OWNER_ID
from utils import premium_service
from utils import caca_db
from utils import caca_memory


async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    if not msg or not user or user.id not in OWNER_ID:
        return

    if not context.args:
        return await msg.reply_text(
            "<b>👑 Premium Control</b>\n\n"
            "<code>/premium add &lt;user_id&gt;</code>\n"
            "<code>/premium del &lt;user_id&gt;</code>\n"
            "<code>/premium list</code>",
            parse_mode="HTML"
        )

    cmd = context.args[0].lower()

    if cmd == "add" and len(context.args) > 1:
        uid = int(context.args[1])
        premium_service.add(uid)
        return await msg.reply_text(
            f"✅ Premium ditambah: <code>{uid}</code>",
            parse_mode="HTML"
        )

    if cmd == "del" and len(context.args) > 1:
        uid = int(context.args[1])
        premium_service.remove(uid)
        caca_db.remove_mode(uid)
        await caca_memory.clear(uid)
        await caca_memory.clear_last_message_id(uid)
        return await msg.reply_text(
            f"❎ Premium dihapus: <code>{uid}</code>",
            parse_mode="HTML"
        )

    if cmd == "list":
        ids = premium_service.list_users()
        if not ids:
            return await msg.reply_text("Belum ada user premium.")
        lines = []
        for uid in ids[:200]:
            try:
                u = await context.bot.get_chat(uid)
                name = html.escape(u.full_name)
            except Exception:
                name = "Unknown User"
            lines.append(f"• <a href=\"tg://user?id={uid}\">{name}</a> <code>{uid}</code>")

        return await msg.reply_text(
            "👑 <b>User Premium:</b>\n" + "\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True
        )