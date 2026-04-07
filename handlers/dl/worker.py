import os
import uuid
import html
import subprocess
import asyncio

from .constants import TMP_DIR, MAX_TG_SIZE
from .utils import detect_media_type
from .ytdlp import ytdlp_download
from telegram import InputMediaPhoto, InputMediaVideo
from telegram.error import RetryAfter
from .instagram_api import is_instagram_url, instagram_api_download
from .youtube_api import is_youtube_url, sonzai_youtube_download

def reencode_mp3(src_path: str) -> str:
    fixed_path = f"{TMP_DIR}/{uuid.uuid4().hex}_fixed.mp3"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            src_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ab",
            "192k",
            "-ar",
            "44100",
            fixed_path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

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

async def _send_media_group_result(
    bot,
    chat_id,
    reply_to,
    result: dict,
):
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
                    continue

                media_type = detect_media_type(file_path)
                fh = open(file_path, "rb")
                handles.append(fh)

                is_first = idx == 0 and i == 0
                item_caption = caption if is_first else None
                item_parse_mode = "HTML" if is_first else None

                if media_type == "video":
                    media.append(
                        InputMediaVideo(
                            media=fh,
                            caption=item_caption,
                            parse_mode=item_parse_mode,
                            supports_streaming=True,
                        )
                    )
                else:
                    media.append(
                        InputMediaPhoto(
                            media=fh,
                            caption=item_caption,
                            parse_mode=item_parse_mode,
                        )
                    )

            if not media:
                continue

            while True:
                try:
                    await bot.send_media_group(
                        chat_id=chat_id,
                        media=media,
                        reply_to_message_id=reply_to if idx == 0 else None,
                    )
                    break
                except RetryAfter as e:
                    wait_time = int(getattr(e, "retry_after", cooldown)) + 1
                    await asyncio.sleep(wait_time)

            if idx < len(chunks) - 1:
                await asyncio.sleep(cooldown)

        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass
                    
async def send_downloaded_media(
    bot,
    chat_id,
    reply_to,
    status_msg_id,
    path,
    fmt_key,
):
    if isinstance(path, dict) and path.get("items"):
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text="<b>Uploading...</b>",
            parse_mode="HTML",
        )

        await _send_media_group_result(
            bot=bot,
            chat_id=chat_id,
            reply_to=reply_to,
            result=path,
        )
        return

    meta = path if isinstance(path, dict) else {"path": path, "title": None}
    file_path = meta.get("path")
    original_title = (meta.get("title") or "").strip()

    if not file_path or not os.path.exists(file_path):
        raise RuntimeError("Download gagal")

    if os.path.exists(file_path) and os.path.getsize(file_path) > MAX_TG_SIZE:
        raise RuntimeError("File exceeds 2GB. Please choose a lower resolution.")

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=status_msg_id,
        text="<b>Uploading...</b>",
        parse_mode="HTML",
    )

    bot_name = (await bot.get_me()).first_name or "Bot"
    caption_text = original_title or _clean_caption_from_path(file_path)
    media_type = detect_media_type(file_path)

    if fmt_key == "mp3":
        fixed_audio = reencode_mp3(file_path)
        await bot.send_audio(
            chat_id=chat_id,
            audio=fixed_audio,
            title=caption_text[:64],
            performer=bot_name,
            filename=f"{caption_text[:50]}.mp3",
            reply_to_message_id=reply_to,
            disable_notification=True,
        )
        os.remove(fixed_audio)
        return

    if media_type == "photo":
        await bot.send_photo(
            chat_id=chat_id,
            photo=file_path,
            caption=_build_safe_photo_caption(caption_text, bot_name),
            parse_mode="HTML",
            reply_to_message_id=reply_to,
            disable_notification=True,
        )
        return

    if media_type == "video":
        await bot.send_video(
            chat_id=chat_id,
            video=file_path,
            caption=_build_safe_caption(caption_text, bot_name),
            parse_mode="HTML",
            supports_streaming=False,
            reply_to_message_id=reply_to,
            disable_notification=True,
        )
        return

    raise RuntimeError("Media tidak didukung")

async def download_non_tiktok(
    raw_url,
    fmt_key,
    bot,
    chat_id,
    status_msg_id,
    format_id: str | None,
    has_audio: bool,
):
    if is_instagram_url(raw_url):
        try:
            return await instagram_api_download(
                raw_url=raw_url,
                fmt_key=fmt_key,
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
            )
        except Exception as e:
            print("[INSTAGRAM API FALLBACK TO YTDLP]", repr(e))

    if is_youtube_url(raw_url):
        yt_error = None

        try:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text="<b>Trying yt-dlp...</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

            result = await ytdlp_download(
                raw_url,
                fmt_key,
                bot,
                chat_id,
                status_msg_id,
                format_id=format_id,
                has_audio=has_audio,
            )

            file_path = result.get("path") if isinstance(result, dict) else result
            if not file_path:
                raise RuntimeError("yt-dlp returned no file")

            return result

        except Exception as e:
            yt_error = str(e) or repr(e)
            print("[YTDLP YOUTUBE FAILED, FALLBACK TO SONZAI]", repr(e))

            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=(
                        "<b>yt-dlp failed</b>\n\n"
                        "<i>Fallback to Sonzai API...</i>"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

            try:
                result = await sonzai_youtube_download(
                    raw_url=raw_url,
                    fmt_key=fmt_key,
                    bot=bot,
                    chat_id=chat_id,
                    status_msg_id=status_msg_id,
                    format_id=format_id,
                )

                file_path = result.get("path") if isinstance(result, dict) else result
                if not file_path:
                    raise RuntimeError("Sonzai returned no file")

                return result

            except Exception as fallback_error:
                raise RuntimeError(
                    f"yt-dlp: {yt_error}\nSonzai: {fallback_error}"
                ) from fallback_error

    return await ytdlp_download(
        raw_url,
        fmt_key,
        bot,
        chat_id,
        status_msg_id,
        format_id=format_id,
        has_audio=has_audio,
    )