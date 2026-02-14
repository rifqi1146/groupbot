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

async def send_downloaded_media(
    bot,
    chat_id,
    reply_to,
    status_msg_id,
    path,
    fmt_key,
):
    if not path or not os.path.exists(path):
        raise RuntimeError("Download gagal")

    if os.path.exists(path) and os.path.getsize(path) > MAX_TG_SIZE:
        raise RuntimeError("File exceeds 2GB. Please choose a lower resolution.")

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=status_msg_id,
        text="<b>Uploading...</b>",
        parse_mode="HTML",
    )

    bot_name = (await bot.get_me()).first_name or "Bot"
    caption = os.path.splitext(os.path.basename(path))[0]
    media_type = detect_media_type(path)

    if fmt_key == "mp3":
        fixed_audio = reencode_mp3(path)
        await bot.send_audio(
            chat_id=chat_id,
            audio=fixed_audio,
            title=caption[:64],
            performer=bot_name,
            filename=f"{caption[:50]}.mp3",
            reply_to_message_id=reply_to,
            disable_notification=True,
        )
        os.remove(fixed_audio)
        return

    if media_type == "photo":
        await bot.send_photo(
            chat_id=chat_id,
            photo=path,
            caption=(
                f"🖼️ <b>{html.escape(caption)}</b>\n\n"
                f"🪄 <i>Powered by {html.escape(bot_name)}</i>"
            ),
            parse_mode="HTML",
            reply_to_message_id=reply_to,
            disable_notification=True,
        )
        return

    if media_type == "video":
        await bot.send_video(
            chat_id=chat_id,
            video=path,
            caption=(
                f"🎬 <b>{html.escape(caption)}</b>\n\n"
                f"🪄 <i>Powered by {html.escape(bot_name)}</i>"
            ),
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