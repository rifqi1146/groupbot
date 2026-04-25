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
_PROGRESS_LOCKS = {}
_SESSION_NAME = os.getenv("MTPROTO_SESSION", "data/mtproto_bot")
_ENABLED = os.getenv("MTPROTO_UPLOAD", "1").lower() not in ("0", "false", "off", "no")
_PROGRESS_MIN_BYTES = int(os.getenv("MTPROTO_PROGRESS_MIN_BYTES", str(5 * 1024 * 1024)))
_PROGRESS_SMALL_LIMIT = int(os.getenv("MTPROTO_PROGRESS_SMALL_LIMIT", str(100 * 1024 * 1024)))
_PROGRESS_SMALL_INTERVAL = float(os.getenv("MTPROTO_PROGRESS_SMALL_INTERVAL", "3.0"))
_PROGRESS_LARGE_INTERVAL = float(os.getenv("MTPROTO_PROGRESS_LARGE_INTERVAL", "10.0"))
_PROGRESS_STEP = float(os.getenv("MTPROTO_PROGRESS_STEP", "5"))
_PART_SIZE_KB = max(32, min(int(os.getenv("MTPROTO_PART_SIZE_KB", "512")), 512))

def _format_size(num: int | float) -> str:
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"

def _progress_interval(file_size: int) -> float:
    return _PROGRESS_SMALL_INTERVAL if file_size < _PROGRESS_SMALL_LIMIT else _PROGRESS_LARGE_INTERVAL

def _get_progress_lock(key):
    lock = _PROGRESS_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _PROGRESS_LOCKS[key] = lock
    return lock

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
        log.info("MTProto uploader ready | session=%s part_size=%sKB", _SESSION_NAME, _PART_SIZE_KB)
        return _CLIENT

async def warmup_mtproto_uploader(app=None):
    if not _ENABLED:
        log.info("MTProto uploader warmup skipped | disabled")
        return
    try:
        await _get_client()
        log.info("MTProto uploader warmup done")
    except Exception as e:
        log.warning("MTProto uploader warmup failed | err=%r", e)

async def shutdown_mtproto_uploader(app=None):
    global _CLIENT
    try:
        if _CLIENT and _CLIENT.is_connected():
            await _CLIENT.disconnect()
            log.info("MTProto uploader disconnected")
    except Exception as e:
        log.warning("MTProto uploader disconnect failed | err=%r", e)

async def _safe_edit_upload(bot, chat_id, message_id, current, total, started):
    key = (int(chat_id), int(message_id))
    lock = _get_progress_lock(key)
    async with lock:
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
            log.info("MTProto upload progress | chat_id=%s %.1f%% %s/%s speed=%s/s", chat_id, percent, _format_size(current), _format_size(total), _format_size(speed))
        except RetryAfter as e:
            wait = int(getattr(e, "retry_after", 1))
            log.warning("MTProto progress RetryAfter | chat_id=%s wait=%s", chat_id, wait)
            await asyncio.sleep(wait + 1)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                log.warning("MTProto upload progress edit failed | chat_id=%s err=%r", chat_id, e)

async def try_send_video_via_mtproto(bot, chat_id, status_msg_id, file_path, caption, reply_to=None, message_thread_id=None, duration=None, width=None, height=None, thumb_path=None):
    if not _ENABLED:
        return False
    if not file_path or not os.path.exists(file_path):
        return False
    file_size = os.path.getsize(file_path)
    show_progress = file_size >= _PROGRESS_MIN_BYTES
    interval = _progress_interval(file_size)
    started = time.monotonic()
    last_progress_task = None

    try:
        client = await _get_client()
        attrs = []
        if DocumentAttributeVideo and duration and width and height:
            attrs.append(DocumentAttributeVideo(duration=int(duration), w=int(width), h=int(height), supports_streaming=True))

        progress_state = {"last_ts": 0.0, "last_pct": -1.0}
        loop = asyncio.get_running_loop()

        def progress_callback(current, total):
            nonlocal last_progress_task
            if not show_progress or not total:
                return
            if total < file_size * 0.8:
                return
            now = time.monotonic()
            pct = current / total * 100
            if pct < 100 and now - progress_state["last_ts"] < interval:
                return
            if pct < 100 and progress_state["last_pct"] >= 0 and pct - progress_state["last_pct"] < _PROGRESS_STEP:
                return
            if last_progress_task and not last_progress_task.done():
                return
            progress_state["last_ts"] = now
            progress_state["last_pct"] = pct
            last_progress_task = loop.create_task(_safe_edit_upload(bot, chat_id, status_msg_id, current, total, started))

        log.info("MTProto upload start | chat_id=%s file=%s size=%s progress=%s interval=%.1fs part_size=%sKB", chat_id, os.path.basename(file_path), _format_size(file_size), show_progress, interval, _PART_SIZE_KB)

        await client.send_file(
            entity=chat_id,
            file=file_path,
            caption=caption,
            parse_mode="html",
            force_document=False,
            supports_streaming=True,
            attributes=attrs or None,
            thumb=thumb_path if thumb_path and os.path.exists(thumb_path) else None,
            reply_to=reply_to,
            progress_callback=progress_callback,
            part_size_kb=_PART_SIZE_KB,
        )

        if last_progress_task:
            await asyncio.gather(last_progress_task, return_exceptions=True)

        elapsed = time.monotonic() - started
        speed = file_size / max(elapsed, 0.001)
        log.info("Telegram MTProto send done | chat_id=%s file=%s size=%s elapsed=%.2fs avg_speed=%s/s", chat_id, os.path.basename(file_path), _format_size(file_size), elapsed, _format_size(speed))
        return True
    except Exception as e:
        log.warning("MTProto upload failed, fallback to PTB | chat_id=%s file=%s err=%r", chat_id, os.path.basename(file_path), e)
        return False