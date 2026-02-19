import os
import time
import uuid
import html
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from .constants import MAX_TG_SIZE
from handlers.join import require_join_or_block
from utils.config import OWNER_ID
from utils.premium import init_premium_db

from .constants import (
    TMP_DIR,
    DL_FORMATS,
    PREMIUM_ONLY_DOMAINS,
    AUTO_DOWNLOAD_DOMAINS,
)
from .state import DL_CACHE
from .db import load_auto_dl, save_auto_dl, is_premium_user, is_premium_required
from .utils import normalize_url, is_invalid_video
from .keyboards import dl_keyboard, res_keyboard, autodl_detect_keyboard
from .probe import get_resolutions
from .tiktok import is_tiktok, douyin_download, tiktok_fallback_send
from .worker import download_non_tiktok, send_downloaded_media

os.makedirs(TMP_DIR, exist_ok=True)

TIKTOK_LOCK = asyncio.Lock()

def is_youtube(url: str) -> bool:
    return any(x in (url or "") for x in ("youtube.com", "youtu.be", "music.youtube.com"))

from urllib.parse import urlparse

def _host(url: str) -> str:
    try:
        u = urlparse((url or "").strip())
        h = (u.hostname or "").lower()
        return h
    except Exception:
        return ""

def _host_match(host: str, domain: str) -> bool:
    host = (host or "").lower()
    domain = (domain or "").lower()
    return host == domain or host.endswith("." + domain)

def is_supported_platform(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    return any(_host_match(host, d) for d in AUTO_DOWNLOAD_DOMAINS)

def is_youtube(url: str) -> bool:
    host = _host(url)
    return any(_host_match(host, d) for d in ("youtube.com", "youtu.be", "music.youtube.com"))

async def _is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if user and user.id in OWNER_ID:
        return True

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def autodl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.message
    user_id = msg.from_user.id

    if chat.type == "private":
        return

    if not await _is_admin_or_owner(update, context):
        return await msg.reply_text("<b>You are not an admin</b>", parse_mode="HTML")

    groups = load_auto_dl()
    arg = context.args[0].lower() if context.args else ""

    if arg == "enable":
        groups.add(chat.id)
        save_auto_dl(groups)
        return await msg.reply_text(
            "Auto-detect link <b>ENABLED</b> in this group.",
            parse_mode="HTML",
        )

    if arg == "disable":
        groups.discard(chat.id)
        save_auto_dl(groups)
        return await msg.reply_text(
            "Auto-detect link <b>DISABLED</b> in this group.",
            parse_mode="HTML",
        )

    if arg == "status":
        if chat.id in groups:
            return await msg.reply_text("Auto-detect Status: <b>ENABLED</b>", parse_mode="HTML")
        return await msg.reply_text("Auto-detect Status: <b>DISABLED</b>", parse_mode="HTML")

    if arg == "list":
        if user_id not in OWNER_ID:
            return

        if not groups:
            return await msg.reply_text("No groups with auto-detect enabled.", parse_mode="HTML")

        lines = ["📋 <b>Groups with Auto-detect Enabled:</b>\n"]
        for gid in groups:
            try:
                c = await context.bot.get_chat(gid)
                title = html.escape(c.title or str(gid))
                lines.append(f"• {title}")
            except Exception:
                lines.append(f"• <code>{gid}</code>")

        return await msg.reply_text("\n".join(lines), parse_mode="HTML")

    return await msg.reply_text(
        "⚙️ <b>Usage:</b>\n"
        "<code>/autodl enable</code>\n"
        "<code>/autodl disable</code>\n"
        "<code>/autodl status</code>\n"
        "<code>/autodl list</code>",
        parse_mode="HTML",
    )


async def auto_dl_detect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    chat = update.effective_chat
    text = normalize_url(msg.text)

    if text.startswith("/"):
        return

    if not is_supported_platform(text):
        return

    if chat.type in ("group", "supergroup"):
        groups = load_auto_dl()
        if chat.id not in groups:
            return

    if not await require_join_or_block(update, context):
        return

    if is_premium_required(text, PREMIUM_ONLY_DOMAINS) and not is_premium_user(update.effective_user.id):
        return await msg.reply_text("🔞 This link can only be downloaded by premium users.")

    dl_id = uuid.uuid4().hex[:8]

    DL_CACHE[dl_id] = {
        "url": text,
        "user": update.effective_user.id,
        "reply_to": msg.message_id,
        "ts": time.time(),
    }

    await msg.reply_text(
        "👀 <b>Link detected</b>\n\nDo you want me to download it?",
        reply_markup=autodl_detect_keyboard(dl_id),
        parse_mode="HTML",
    )


async def dlask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

    q = update.callback_query
    await q.answer()

    _, dl_id, action = q.data.split(":", 2)

    data = DL_CACHE.get(dl_id)
    if not data:
        return await q.edit_message_text("Request expired")

    if q.from_user.id != data["user"]:
        return await q.answer("This is not your request", show_alert=True)

    if action == "close":
        DL_CACHE.pop(dl_id, None)
        return await q.message.delete()

    await q.edit_message_text(
        "📥 <b>Select format</b>",
        reply_markup=dl_keyboard(dl_id),
        parse_mode="HTML",
    )


async def _dl_worker(app, chat_id, reply_to, raw_url, fmt_key, status_msg_id, format_id: str | None = None, has_audio: bool = False):
    bot = app.bot
    path = None

    async def _tiktok_fetch() -> tuple[bool, str | None]:
        nonlocal path

        url = raw_url
        try:
            url = await resolve_tiktok_url(raw_url)
        except Exception:
            url = raw_url

        async with TIKTOK_LOCK:
            try:
                path = await douyin_download(url, bot, chat_id, status_msg_id)

                if is_invalid_video(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    raise RuntimeError("Static video")

                return (False, path)

            except Exception:
                ok = await tiktok_fallback_send(
                    bot=bot,
                    chat_id=chat_id,
                    reply_to=reply_to,
                    status_msg_id=status_msg_id,
                    url=url,
                    fmt_key=fmt_key,
                )
                if ok:
                    return (True, None)
                raise

    try:
        if is_tiktok(raw_url):
            sent, _ = await _tiktok_fetch()
            if sent:
                return
        else:
            path = await download_non_tiktok(
                raw_url=raw_url,
                fmt_key=fmt_key,
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
                format_id=format_id,
                has_audio=has_audio,
            )

        await send_downloaded_media(
            bot=bot,
            chat_id=chat_id,
            reply_to=reply_to,
            status_msg_id=status_msg_id,
            path=path,
            fmt_key=fmt_key,
        )

        await bot.delete_message(chat_id, status_msg_id)

    except Exception as e:
        err = str(e)
    
        if "Flood control exceeded" in err and "Retry in" in err:
            try:
                import re
                m = re.search(r"Retry in (\d+)", err)
                wait_time = int(m.group(1)) if m else 5
            except Exception:
                wait_time = 5
    
            await asyncio.sleep(wait_time)
            return await _dl_worker(
                app,
                chat_id,
                reply_to,
                raw_url,
                fmt_key,
                status_msg_id,
                format_id,
                has_audio,
            )
    
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=f"Failed: {e}",
            )
        except Exception:
            pass

    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


async def dl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

    if not context.args:
        return await update.message.reply_text("Send a TikTok link / YT-dlp supported platform link")

    url = context.args[0]

    if is_premium_required(url, PREMIUM_ONLY_DOMAINS):
        if not is_premium_user(update.effective_user.id):
            return await update.message.reply_text("🔞 Download from this website is for premium users only")

    dl_id = uuid.uuid4().hex[:8]
    DL_CACHE[dl_id] = {
        "url": url,
        "user": update.effective_user.id,
        "reply_to": update.message.message_id,
    }

    await update.message.reply_text(
        "📥 <b>Select format</b>",
        reply_markup=dl_keyboard(dl_id),
        parse_mode="HTML",
    )


async def dl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

    q = update.callback_query
    await q.answer()

    _, dl_id, choice = q.data.split(":", 2)

    data = DL_CACHE.get(dl_id)
    if not data:
        return await q.edit_message_text("Data expired")

    if q.from_user.id != data["user"]:
        return await q.answer("This is not your request", show_alert=True)

    if choice == "cancel":
        DL_CACHE.pop(dl_id, None)
        return await q.edit_message_text("Cancelled")

    url = data["url"]

    if choice == "video" and is_youtube(url):
        await q.edit_message_text("🔎 <b>Fetching video formats...</b>", parse_mode="HTML")
        res_list = await get_resolutions(url)

        if not res_list:
            DL_CACHE.pop(dl_id, None)
            return await q.edit_message_text(
                "No valid resolutions available (possibly all exceed Telegram limit).",
                parse_mode="HTML",
            )

        res_map = {}
        for r in res_list:
            h = int(r.get("height") or 0)
            fid = str(r.get("format_id") or "")
            if h and fid:
                res_map[h] = {
                    "format_id": fid,
                    "has_audio": bool(r.get("has_audio")),
                    "filesize": int(r.get("filesize") or 0),
                    "total_size": int(r.get("total_size") or 0),
                }

        DL_CACHE[dl_id]["res_map"] = res_map

        return await q.edit_message_text(
            "<b>Select resolution</b>",
            reply_markup=res_keyboard(dl_id, res_list),
            parse_mode="HTML",
        )

    DL_CACHE.pop(dl_id, None)

    await q.edit_message_text(
        f"<b>Preparing {DL_FORMATS[choice]['label']}...</b>",
        parse_mode="HTML",
    )

    context.application.create_task(
        _dl_worker(
            app=context.application,
            chat_id=q.message.chat.id,
            reply_to=data["reply_to"],
            raw_url=url,
            fmt_key=choice,
            status_msg_id=q.message.message_id,
            format_id=None,
            has_audio=False,
        )
    )


async def dlres_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

    q = update.callback_query
    await q.answer()

    _, dl_id, h = q.data.split(":", 2)

    data = DL_CACHE.get(dl_id)
    if not data:
        return await q.edit_message_text("Data expired")

    if q.from_user.id != data["user"]:
        return await q.answer("This is not your request", show_alert=True)

    try:
        height = int(h)
    except Exception:
        height = 0

    res_map = data.get("res_map") or {}
    pick = res_map.get(height) or {}

    format_id = str(pick.get("format_id") or "")
    has_audio = bool(pick.get("has_audio"))
    total_size = int(pick.get("total_size") or 0)

    if total_size and total_size > MAX_TG_SIZE:
        DL_CACHE.pop(dl_id, None)
        return await q.edit_message_text(
            "<b>File too large</b> (Exceeds Telegram 2GB limit).\n"
            "Please choose a lower resolution.",
            parse_mode="HTML",
        )

    DL_CACHE.pop(dl_id, None)

    label = f"{height}p" if height else "video"
    await q.edit_message_text(
        f"⏳ <b>Preparing 🎥 Video ({html.escape(label)})...</b>",
        parse_mode="HTML",
    )

    context.application.create_task(
        _dl_worker(
            app=context.application,
            chat_id=q.message.chat.id,
            reply_to=data["reply_to"],
            raw_url=data["url"],
            fmt_key="video",
            status_msg_id=q.message.message_id,
            format_id=format_id if format_id else None,
            has_audio=has_audio,
        )
    )


try:
    init_premium_db()
except Exception:
    pass