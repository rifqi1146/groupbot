import os
import time
import asyncio
import logging
from utils.config import BOT_TOKEN
from telegram.error import RetryAfter
from .utils import progress_bar
log = logging.getLogger(__name__)

try:
    from telethon import TelegramClient
    from telethon.tl.types import DocumentAttributeVideo
except Exception:
    TelegramClient = None
    DocumentAttributeVideo = None

_CLIENT = None
_CLIENT_LOCK = asyncio.Lock()
_SESSION_NAME = os.getenv("MTPROTO_SESSION", "data/mtproto_bot")
_ENABLED = os.getenv("MTPROTO_UPLOAD", "1").lower() not in ("0", "false", "off", "no")

def _format_size(num: int) -> str:
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"

async def _get_client():
    global _CLIENT
    if not _ENABLED:
        raise RuntimeError("MTProto upload disabled")
    if TelegramClient is None:
        raise RuntimeError("Telethon is not installed")
    api_id = os.getenv("TG_API_ID") or os.getenv("API_ID")
    api_hash = os.getenv("TG_API_HASH") or os.getenv("API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("TG_API_ID/TG_API_HASH is not configured")
    async with _CLIENT_LOCK:
        if _CLIENT and _CLIENT.is_connected():
            return _CLIENT
        os.makedirs(os.path.dirname(_SESSION_NAME) or ".", exist_ok=True)
        _CLIENT = TelegramClient(_SESSION_NAME, int(api_id), api_hash)
        await _CLIENT.start(bot_token=BOT_TOKEN)
        log.info("MTProto uploader ready | session=%s", _SESSION_NAME)
        return _CLIENT

async def _safe_edit_upload(bot, chat_id, message_id, current, total, started):
    try:
        percent = (current / total * 100) if total else 0
        elapsed = max(time.monotonic() - started, 0.001)
        speed = current / elapsed
        text = (
            "<b>Uploading video...</b>\n\n"
            f"<code>{progress_bar(percent)}</code>\n"
            f"<code>{_format_size(current)}/{_format_size(total)}</code>\n"
            f"<code>Speed: {_format_size(speed)}/s</code>"
        )
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML")
    except RetryAfter as e:
        await asyncio.sleep(int(getattr(e, "retry_after", 1)) + 1)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            log.debug("MTProto upload progress edit ignored | err=%s", e)

async def try_send_video_via_mtproto(bot, chat_id, status_msg_id, file_path, caption, reply_to=None, message_thread_id=None, duration=None, width=None, height=None, thumb_path=None):
    if not _ENABLED:
        return False
    if not file_path or not os.path.exists(file_path):
        return False
    started = time.monotonic()
    try:
        client = await _get_client()
        attrs = []
        if DocumentAttributeVideo and duration and width and height:
            attrs.append(DocumentAttributeVideo(duration=int(duration), w=int(width), h=int(height), supports_streaming=True))
        progress_state = {"last_ts": 0.0, "last_pct": -1.0}
        loop = asyncio.get_running_loop()
        def progress_callback(current, total):
            if not total:
                return
            now = time.monotonic()
            pct = current / total * 100
            if pct < 100 and now - progress_state["last_ts"] < 1.5 and pct - progress_state["last_pct"] < 4:
                return
            progress_state["last_ts"] = now
            progress_state["last_pct"] = pct
            loop.create_task(_safe_edit_upload(bot, chat_id, status_msg_id, current, total, started))
        await client.send_file(
            entity=chat_id,
            file=file_path,
            caption=caption,
            parse_mode="html",
            force_document=False,
            supports_streaming=True,
            attributes=attrs or None,
            thumb=thumb_path if thumb_path and os.path.exists(thumb_path) else None,
            reply_to=reply_to or message_thread_id,
            progress_callback=progress_callback,
        )
        log.info("Telegram MTProto send done | chat_id=%s file=%s elapsed=%.2fs", chat_id, os.path.basename(file_path), time.monotonic() - started)
        return True
    except Exception as e:
        log.warning("MTProto upload failed, fallback to PTB | chat_id=%s file=%s err=%r", chat_id, os.path.basename(file_path), e)
        return False