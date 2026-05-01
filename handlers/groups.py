import asyncio
import html
import logging
from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import ContextTypes
from utils.config import OWNER_ID
from database.groups_db import _db_init, _load_groups

log = logging.getLogger(__name__)
_MAX_MSG_LEN = 3800
_GET_CHAT_DELAY = 0.25
_GET_CHAT_RETRIES = 3

def _chat_sort_key(item):
    return (item.get("title") or "").lower()

def _normalize_chat_id(chat_id):
    try:
        return int(str(chat_id).strip())
    except (TypeError, ValueError):
        return None

def _is_legacy_private_group_id(chat_id):
    return str(chat_id).strip().startswith("-5")

def _unique_group_ids(group_ids):
    seen = set()
    result = []
    for raw_gid in group_ids:
        gid = _normalize_chat_id(raw_gid)
        if gid is None:
            log.warning("Invalid group id skipped | raw_group_id=%r", raw_gid)
            continue
        if _is_legacy_private_group_id(gid):
            log.info("Legacy private group id skipped | group_id=%s", gid)
            continue
        if gid in seen:
            continue
        seen.add(gid)
        result.append(gid)
    return result

async def _safe_get_chat(bot, gid):
    for attempt in range(1, _GET_CHAT_RETRIES + 1):
        try:
            chat = await bot.get_chat(gid)
            await asyncio.sleep(_GET_CHAT_DELAY)
            return chat
        except RetryAfter as e:
            wait_time = int(getattr(e, "retry_after", 1)) + 1
            log.warning("Get chat rate limited | group_id=%s wait=%ss attempt=%s/%s", gid, wait_time, attempt, _GET_CHAT_RETRIES)
            await asyncio.sleep(wait_time)
        except Exception as e:
            log.warning("Failed to fetch group info | group_id=%s error=%s", gid, e)
            return None
    log.warning("Failed to fetch group info after retries | group_id=%s", gid)
    return None

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
    group_ids = _unique_group_ids(_load_groups())
    if not group_ids:
        return await msg.reply_text("📭 <b>No groups recorded yet.</b>", parse_mode="HTML")
    public_groups = []
    private_groups = []
    for gid in group_ids:
        chat = await _safe_get_chat(bot, gid)
        if not chat:
            continue
        title = html.escape((chat.title or "Unknown").strip() or "Unknown")
        username = (getattr(chat, "username", None) or "").strip()
        item = {"id": gid, "title": title, "username": username}
        if username:
            public_groups.append(item)
        else:
            private_groups.append(item)
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