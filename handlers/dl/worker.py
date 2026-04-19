import os
import uuid
import html
import logging
import subprocess
import asyncio
from .constants import TMP_DIR, MAX_TG_SIZE
from .utils import detect_media_type
from .ytdlp import ytdlp_download
from telegram import InputMediaPhoto, InputMediaVideo
from telegram.error import RetryAfter
from .instagram_api import is_instagram_url, instagram_api_download
from .youtube_api import is_youtube_url, sonzai_youtube_download

log = logging.getLogger(__name__)

def reencode_mp3(src_path: str) -> str:
    fixed_path = f"{TMP_DIR}/{uuid.uuid4().hex}_fixed.mp3"
    result = subprocess.run(["ffmpeg","-y","-i",src_path,"-vn","-acodec","libmp3lame","-ab","192k","-ar","44100",fixed_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg re-encode failed with exit code {result.returncode}")
    if not os.path.exists(fixed_path):
        raise RuntimeError("FFmpeg re-encode failed")
    return fixed_path

def _clean_caption_from_path(path: str) -> str:
    raw_name = os.path.splitext(os.path.basename(path))[0]
    parts = raw_name.split("_", 1)
    if len(parts) == 2 and len(parts[0]) >= 10 and all(c in "0123456789abcdef" for c in parts[0].lower()):
        text = parts[1]
    else:
        text = raw_name
    return text.strip() or "Media"

def _build_safe_caption(title: str, bot_name: str, max_len: int = 1024) -> str:
    clean_title = (title or "Media").strip()
    safe_bot = html.escape(bot_name or "Bot")
    suffix = f"\n\n🪄 <i>Powered by {safe_bot}</i>"
    prefix = "<blockquote expandable>🎬 "
    closing = "</blockquote>"
    full = f"{prefix}{html.escape(clean_title)}{closing}{suffix}"
    if len(full) <= max_len:
        return full
    allowed = max_len - len(prefix) - len(closing) - len(suffix) - 3
    if allowed < 1:
        allowed = 1
    short_title = clean_title[:allowed].rstrip() + "..."
    return f"{prefix}{html.escape(short_title)}{closing}{suffix}"

def _build_safe_photo_caption(title: str, bot_name: str, max_len: int = 1024) -> str:
    clean_title = (title or "Image").strip()
    safe_bot = html.escape(bot_name or "Bot")
    suffix = f"\n\n🪄 <i>Powered by {safe_bot}</i>"
    prefix = "<blockquote expandable>🖼️ "
    closing = "</blockquote>"
    full = f"{prefix}{html.escape(clean_title)}{closing}{suffix}"
    if len(full) <= max_len:
        return full
    allowed = max_len - len(prefix) - len(closing) - len(suffix) - 3
    if allowed < 1:
        allowed = 1
    short_title = clean_title[:allowed].rstrip() + "..."
    return f"{prefix}{html.escape(short_title)}{closing}{suffix}"

def _is_reply_not_found_error(exc: Exception) -> bool:
    text = (str(exc) or "").lower()
    keys = ("replied message not found","message to be replied not found","reply message not found","reply_to_message_id")
    return any(k in text for k in keys)

async def _safe_edit_status(bot, chat_id, message_id, text: str):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" in (str(e) or "").lower():
            return
        log.warning("Failed to edit status message | chat_id=%s message_id=%s err=%s", chat_id, message_id, e)

async def _set_uploading_status(bot, chat_id, status_msg_id, kind: str):
    label = {
        "audio": "🎵 <b>Uploading audio...</b>",
        "video": "🎬 <b>Uploading video...</b>",
        "photo": "🖼️ <b>Uploading photo...</b>",
        "album": "🖼️ <b>Uploading album...</b>",
    }.get(kind, "<b>Uploading...</b>")
    action = {
        "audio": "upload_audio",
        "video": "upload_video",
        "photo": "upload_photo",
        "album": "upload_photo",
    }.get(kind, "typing")
    await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text=label)
    try:
        await bot.send_chat_action(chat_id=chat_id, action=action)
    except Exception as e:
        log.warning("Failed to send chat action | chat_id=%s action=%s err=%s", chat_id, action, e)

async def _send_media_group_with_fallback(bot, chat_id, media, reply_to=None, message_thread_id=None):
    while True:
        try:
            return await bot.send_media_group(chat_id=chat_id, media=media, reply_to_message_id=reply_to, message_thread_id=message_thread_id)
        except RetryAfter as e:
            wait_time = int(getattr(e, "retry_after", 3)) + 1
            log.warning("RetryAfter while sending media group | chat_id=%s wait=%s", chat_id, wait_time)
            await asyncio.sleep(wait_time)
        except Exception as e:
            if reply_to and _is_reply_not_found_error(e):
                reply_to = None
                continue
            raise

async def _send_photo_with_fallback(bot, chat_id, photo, caption, reply_to=None, message_thread_id=None):
    try:
        return await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to, message_thread_id=message_thread_id, disable_notification=True)
    except Exception as e:
        if reply_to and _is_reply_not_found_error(e):
            return await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, parse_mode="HTML", message_thread_id=message_thread_id, disable_notification=True)
        raise

async def _send_video_with_fallback(bot, chat_id, video, caption, reply_to=None, message_thread_id=None, supports_streaming=False):
    try:
        return await bot.send_video(chat_id=chat_id, video=video, caption=caption, parse_mode="HTML", supports_streaming=supports_streaming, reply_to_message_id=reply_to, message_thread_id=message_thread_id, disable_notification=True)
    except Exception as e:
        if reply_to and _is_reply_not_found_error(e):
            return await bot.send_video(chat_id=chat_id, video=video, caption=caption, parse_mode="HTML", supports_streaming=supports_streaming, message_thread_id=message_thread_id, disable_notification=True)
        raise

async def _send_audio_with_fallback(bot, chat_id, audio, title, performer, filename, reply_to=None, message_thread_id=None):
    try:
        return await bot.send_audio(chat_id=chat_id, audio=audio, title=title, performer=performer, filename=filename, reply_to_message_id=reply_to, message_thread_id=message_thread_id, disable_notification=True)
    except Exception as e:
        if reply_to and _is_reply_not_found_error(e):
            return await bot.send_audio(chat_id=chat_id, audio=audio, title=title, performer=performer, filename=filename, message_thread_id=message_thread_id, disable_notification=True)
        raise

async def _send_media_group_result(bot, chat_id, reply_to, result: dict, message_thread_id=None):
    items = result.get("items") or []
    if not items:
        raise RuntimeError("Album result kosong")
    title = (result.get("title") or "Media").strip() or "Media"
    bot_name = (await bot.get_me()).first_name or "Bot"
    caption = _build_safe_photo_caption(title, bot_name)
    chunk_size = 10
    cooldown = 3
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    for idx, chunk in enumerate(chunks):
        media = []
        handles = []
        try:
            for i, item in enumerate(chunk):
                file_path = item.get("path")
                if not file_path or not os.path.exists(file_path):
                    log.warning("Skipping media group item because file is missing | chat_id=%s path=%s", chat_id, file_path)
                    continue
                media_type = detect_media_type(file_path)
                fh = open(file_path, "rb")
                handles.append(fh)
                is_first = idx == 0 and i == 0
                item_caption = caption if is_first else None
                item_parse_mode = "HTML" if is_first else None
                if media_type == "video":
                    media.append(InputMediaVideo(media=fh, caption=item_caption, parse_mode=item_parse_mode, supports_streaming=True))
                else:
                    media.append(InputMediaPhoto(media=fh, caption=item_caption, parse_mode=item_parse_mode))
            if not media:
                log.warning("No valid media items to send in chunk | chat_id=%s chunk_index=%s", chat_id, idx)
                continue
            await _send_media_group_with_fallback(bot=bot, chat_id=chat_id, media=media, reply_to=reply_to if idx == 0 else None, message_thread_id=message_thread_id)
            if idx < len(chunks) - 1:
                await asyncio.sleep(cooldown)
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception as e:
                    log.warning("Failed to close media file handle | chat_id=%s err=%s", chat_id, e)

async def send_downloaded_media(bot, chat_id, reply_to, status_msg_id, path, fmt_key, message_thread_id=None):
    if isinstance(path, dict) and path.get("items"):
        items = path.get("items") or []
        first_path = items[0].get("path") if items else None
        first_type = detect_media_type(first_path) if first_path and os.path.exists(first_path) else "photo"
        await _set_uploading_status(bot, chat_id, status_msg_id, "album" if len(items) > 1 else ("video" if first_type == "video" else "photo"))
        await _send_media_group_result(bot=bot, chat_id=chat_id, reply_to=reply_to, result=path, message_thread_id=message_thread_id)
        return
    meta = path if isinstance(path, dict) else {"path": path, "title": None}
    file_path = meta.get("path")
    original_title = (meta.get("title") or "").strip()
    if not file_path or not os.path.exists(file_path):
        raise RuntimeError("Download gagal")
    if os.path.getsize(file_path) > MAX_TG_SIZE:
        raise RuntimeError("File exceeds 2GB. Please choose a lower resolution.")
    bot_name = (await bot.get_me()).first_name or "Bot"
    caption_text = original_title or _clean_caption_from_path(file_path)
    media_type = detect_media_type(file_path)
    if fmt_key == "mp3":
        fixed_audio = None
        try:
            await _set_uploading_status(bot, chat_id, status_msg_id, "audio")
            fixed_audio = reencode_mp3(file_path)
            await _send_audio_with_fallback(bot=bot, chat_id=chat_id, audio=fixed_audio, title=caption_text[:64], performer=bot_name, filename=f"{caption_text[:50]}.mp3", reply_to=reply_to, message_thread_id=message_thread_id)
            return
        finally:
            if fixed_audio and os.path.exists(fixed_audio):
                try:
                    os.remove(fixed_audio)
                except Exception as e:
                    log.warning("Failed to remove temporary re-encoded mp3 | path=%s err=%s", fixed_audio, e)
    if media_type == "photo":
        await _set_uploading_status(bot, chat_id, status_msg_id, "photo")
        await _send_photo_with_fallback(bot=bot, chat_id=chat_id, photo=file_path, caption=_build_safe_photo_caption(caption_text, bot_name), reply_to=reply_to, message_thread_id=message_thread_id)
        return
    if media_type == "video":
        await _set_uploading_status(bot, chat_id, status_msg_id, "video")
        await _send_video_with_fallback(bot=bot, chat_id=chat_id, video=file_path, caption=_build_safe_caption(caption_text, bot_name), reply_to=reply_to, message_thread_id=message_thread_id, supports_streaming=False)
        return
    raise RuntimeError("Media tidak didukung")

async def download_non_tiktok(raw_url, fmt_key, bot, chat_id, status_msg_id, format_id: str | None, has_audio: bool, engine: str | None = None):
    if is_instagram_url(raw_url):
        try:
            return await instagram_api_download(raw_url=raw_url, fmt_key=fmt_key, bot=bot, chat_id=chat_id, status_msg_id=status_msg_id)
        except Exception as e:
            log.warning("Instagram API download failed, falling back to yt-dlp | url=%s err=%r", raw_url, e)
    if is_youtube_url(raw_url):
        chosen_engine = (engine or "").strip().lower()
        if chosen_engine == "sonzai":
            return await sonzai_youtube_download(raw_url=raw_url, fmt_key=fmt_key, bot=bot, chat_id=chat_id, status_msg_id=status_msg_id, format_id=format_id)
        if chosen_engine == "ytdlp":
            return await ytdlp_download(raw_url, fmt_key, bot, chat_id, status_msg_id, format_id=format_id, has_audio=has_audio)
        yt_error = None
        try:
            await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>Trying yt-dlp...</b>")
            result = await ytdlp_download(raw_url, fmt_key, bot, chat_id, status_msg_id, format_id=format_id, has_audio=has_audio)
            file_path = result.get("path") if isinstance(result, dict) else result
            if not file_path:
                raise RuntimeError("yt-dlp returned no file")
            return result
        except Exception as e:
            yt_error = str(e) or repr(e)
            log.warning("yt-dlp YouTube download failed, falling back to Sonzai | url=%s err=%r", raw_url, e)
            await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>yt-dlp failed</b>\n\n<i>Fallback to Sonzai API...</i>")
            try:
                result = await sonzai_youtube_download(raw_url=raw_url, fmt_key=fmt_key, bot=bot, chat_id=chat_id, status_msg_id=status_msg_id, format_id=format_id)
                file_path = result.get("path") if isinstance(result, dict) else result
                if not file_path:
                    raise RuntimeError("Sonzai returned no file")
                return result
            except Exception as fallback_error:
                log.warning("Sonzai YouTube fallback failed | url=%s err=%r", raw_url, fallback_error)
                raise RuntimeError(f"yt-dlp: {yt_error}\nSonzai: {fallback_error}") from fallback_error
    return await ytdlp_download(raw_url, fmt_key, bot, chat_id, status_msg_id, format_id=format_id, has_audio=has_audio)
    