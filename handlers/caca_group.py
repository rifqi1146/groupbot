import html
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID
from utils import caca_db


async def _is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
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


async def cacaa_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not chat:
        return

    if not await _is_admin_or_owner(update, context):
        return

    groups = caca_db.load_groups()
    cmd = (context.args[0].lower() if context.args else "")

    if not cmd:
        return await msg.reply_text(
            "<b>⚙️ Caca Group Control</b>\n\n"
            "<code>/cacaa enable</code> — enable in this group\n"
            "<code>/cacaa disable</code> — disable in this group\n"
            "<code>/cacaa status</code> — check status",
            parse_mode="HTML"
        )

    if cmd == "enable":
        if chat.type == "private":
            return await msg.reply_text("<b>Group only.</b>", parse_mode="HTML")
        groups.add(chat.id)
        caca_db.save_groups(groups)
        return await msg.reply_text("<b>Caca has been enabled in this group.</b>", parse_mode="HTML")

    if cmd == "disable":
        groups.discard(chat.id)
        caca_db.save_groups(groups)
        return await msg.reply_text("<b>Caca has been disabled in this group.</b>", parse_mode="HTML")

    if cmd == "status":
        if chat.id in groups:
            return await msg.reply_text("<b>Caca status in this group: ENABLED</b>", parse_mode="HTML")
        return await msg.reply_text("<b>Caca status in this group: DISABLED</b>", parse_mode="HTML")

    if cmd == "list":
        if user.id not in OWNER_ID:
            return

        if not groups:
            return await msg.reply_text("<b>No active groups yet.</b>", parse_mode="HTML")

        text = ["<b>Active Caca Groups:</b>\n"]
        for gid in groups:
            try:
                c = await context.bot.get_chat(gid)
                text.append(f"• <b>{html.escape(c.title or str(gid))}</b>")
            except Exception:
                text.append(f"• <b>{gid}</b>")

        return await msg.reply_text("\n".join(text), parse_mode="HTML")

    return