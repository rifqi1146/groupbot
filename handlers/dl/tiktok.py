import os
import uuid
import html
import aiohttp
from telegram import InputMediaPhoto
from utils.http import get_http_session
from .constants import TMP_DIR
from .utils import sanitize_filename, progress_bar, is_invalid_video
from .worker import reencode_mp3

def is_tiktok(url: str) -> bool:
    return any(x in (url or "") for x in ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com"))

async def douyin_download(url, bot, chat_id, status_msg_id):
    session = await get_http_session()

    async with session.post(
        "https://www.tikwm.com/api/",
        data={"url": url},
        timeout=aiohttp.ClientTimeout(total=20),
    ) as r:
        data = await r.json()

    if data.get("code") != 0:
        raise RuntimeError("Douyin API error")

    info = data.get("data") or {}
    video_url = info.get("play")
    if not video_url:
        raise RuntimeError("Video URL kosong")

    title = info.get("title") or "TikTok Video"
    safe_title = sanitize_filename(title)
    out_path = f"{TMP_DIR}/{safe_title}.mp4"

    async with session.get(video_url) as r:
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        last = 0

        with open(out_path, "wb") as f:
            async for chunk in r.content.iter_chunked(64 * 1024):
                f.write(chunk)
                downloaded += len(chunk)

                import time
                if total and time.time() - last >= 1.2:
                    pct = downloaded / total * 100
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=(
                            "<b>Downloading...</b>\n\n"
                            f"<code>{progress_bar(pct)} {pct:.1f}%</code>"
                        ),
                        parse_mode="HTML",
                    )
                    last = time.time()

    return out_path

async def tiktok_fallback_send(
    bot,
    chat_id,
    reply_to,
    status_msg_id,
    url,
    fmt_key,
):
    session = await get_http_session()
    async with session.post(
        "https://www.tikwm.com/api/",
        data={"url": url},
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        data = await r.json()

    if fmt_key == "mp3":
        music_url = (
            data.get("data", {}).get("music")
            or data.get("data", {}).get("music_info", {}).get("play")
        )

        if not music_url:
            raise RuntimeError("Slideshow audio not found")

        tmp_audio = f"{TMP_DIR}/{uuid.uuid4().hex}.mp3"

        async with session.get(music_url) as r:
            with open(tmp_audio, "wb") as f:
                async for chunk in r.content.iter_chunked(64 * 1024):
                    f.write(chunk)

        title = (
            data.get("data", {}).get("title")
            or data.get("data", {}).get("desc")
            or "TikTok Audio"
        )

        bot_name = (await bot.get_me()).first_name or "Bot"
        fixed_audio = reencode_mp3(tmp_audio)

        await bot.send_chat_action(chat_id=chat_id, action="upload_audio")

        await bot.send_audio(
            chat_id=chat_id,
            audio=fixed_audio,
            title=title[:64],
            performer=bot_name,
            filename=f"{title[:50]}.mp3",
            reply_to_message_id=reply_to,
            disable_notification=True,
        )

        await bot.delete_message(chat_id, status_msg_id)
        os.remove(tmp_audio)
        os.remove(fixed_audio)
        return True

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=status_msg_id,
        text="🖼️ Slideshow detected, sending album...",
        parse_mode="HTML",
    )

    images = data.get("data", {}).get("images") or []
    if not images:
        raise RuntimeError("Slideshow images not found")

    CHUNK_SIZE = 10
    chunks = [images[i : i + CHUNK_SIZE] for i in range(0, len(images), CHUNK_SIZE)]

    bot_name = (await bot.get_me()).first_name or "Bot"
    title = (
        data.get("data", {}).get("title")
        or data.get("data", {}).get("desc")
        or "TikTok Slideshow"
    )
    title = html.escape(title.strip())

    caption_text = f"🖼️ <b>{title}</b>\n\n🪄 <i>Powered by {html.escape(bot_name)}</i>"

    for idx, chunk in enumerate(chunks):
        media = []
        for i, img in enumerate(chunk):
            media.append(
                InputMediaPhoto(
                    media=img,
                    caption=caption_text if idx == 0 and i == 0 else None,
                    parse_mode="HTML" if idx == 0 and i == 0 else None,
                )
            )

        await bot.send_media_group(
            chat_id=chat_id,
            media=media,
            reply_to_message_id=reply_to if idx == 0 else None,
        )

    await bot.delete_message(chat_id, status_msg_id)
    return True