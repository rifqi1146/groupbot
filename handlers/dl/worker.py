import os
import uuid
import html
import subprocess
from .constants import TMP_DIR, MAX_TG_SIZE
from .utils import detect_media_type
from .ytdlp import ytdlp_download


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


async def send_downloaded_media(
    bot,
    chat_id,
    reply_to,
    status_msg_id,
    path,
    fmt_key,
):
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
    return await ytdlp_download(
        raw_url,
        fmt_key,
        bot,
        chat_id,
        status_msg_id,
        format_id=format_id,
        has_audio=has_audio,
    )