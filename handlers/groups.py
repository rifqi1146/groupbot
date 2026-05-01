import html
import logging
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID
from database.groups_db import _db_init, _load_groups

log = logging.getLogger(__name__)
_MAX_MSG_LEN = 3800

def _chat_sort_key(item):
    return (item.get("title") or "").lower()

def _is_supergroup_id(chat_id):
    return str(chat_id).startswith("-100")

def _unique_supergroup_ids(group_ids):
    seen = set()
    result = []
    for gid in group_ids:
        if not _is_supergroup_id(gid) or gid in seen:
            continue
        seen.add(gid)
        result.append(gid)
    return result

async def _reply_chunks(msg, lines):
    chunk = []
    size = 0
    for line in lines:
        add_size = len(line) + (1 if chunk else 0)
        if chunk and size + add_size > _MAX_MSG_LEN:
            await msg.reply_text("\n".join(chunk), parse_mode="HTML", disable_web_page_preview=True)
            chunk = [line]
            size = len(line)
        else:
            chunk.append(line)
            size += add_size
    if chunk:
        await msg.reply_text("\n".join(chunk), parse_mode="HTML", disable_web_page_preview=True)

async def groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    bot = context.bot
    if not msg or not user or user.id not in OWNER_ID:
        return
    group_ids = _unique_supergroup_ids(_load_groups())
    if not group_ids:
        return await msg.reply_text("📭 <b>No groups recorded yet.</b>", parse_mode="HTML")
    public_groups = []
    private_groups = []
    for gid in group_ids:
        try:
            chat = await bot.get_chat(gid)
            title = html.escape((chat.title or "Unknown").strip() or "Unknown")
            username = (getattr(chat, "username", None) or "").strip()
            item = {"id": gid, "title": title, "username": username}
            if username:
                public_groups.append(item)
            else:
                private_groups.append(item)
        except Exception as e:
            log.warning("Failed to fetch group info | group_id=%s error=%s", gid, e)
    public_groups.sort(key=_chat_sort_key)
    private_groups.sort(key=_chat_sort_key)
    total_valid = len(public_groups) + len(private_groups)
    if total_valid == 0:
        return await msg.reply_text(
            "📭 <b>No active groups found.</b>\n\n<i>Saved entries exist, but the bot can no longer access them.</i>",
            parse_mode="HTML"
        )
    lines = [
        "👥 <b>Current Bot Groups</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>Total Active:</b> <code>{total_valid}</code>",
        f"🔗 <b>Public:</b> <code>{len(public_groups)}</code>",
        f"🔒 <b>Private / Hidden:</b> <code>{len(private_groups)}</code>"
    ]
    if public_groups:
        lines += ["", "🔗 <b>Public Groups</b>", "━━━━━━━━━━━━━━━━━━━━"]
        for i, item in enumerate(public_groups, 1):
            link = f"https://t.me/{html.escape(item['username'], quote=True)}"
            lines.append(f"{i}. 🌐 <a href=\"{link}\">{item['title']}</a>\n   🆔 <code>{item['id']}</code>")
    if private_groups:
        lines += ["", "🔒 <b>Private / Hidden Groups</b>", "━━━━━━━━━━━━━━━━━━━━"]
        for i, item in enumerate(private_groups, 1):
            lines.append(f"{i}. 🏷️ <b>{item['title']}</b>\n   🆔 <code>{item['id']}</code>")
    await _reply_chunks(msg, lines)

try:
    _db_init()
except Exception:
    log.exception("Failed to initialize groups database")