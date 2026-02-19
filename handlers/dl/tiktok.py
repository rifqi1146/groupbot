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

    images = info.get("images") or info.get("image") or []
    if isinstance(images, list) and len(images) > 0:
        raise RuntimeError("SLIDESHOW")

    video_url = (
        info.get("hdplay")
        or info.get("play")
        or info.get("wmplay")
        or info.get("play_url")
    )
    if not video_url:
        raise RuntimeError("Video URL kosong")

    title = info.get("title") or "TikTok Video"
    safe_title = sanitize_filename(title)
    uid = uuid.uuid4().hex
    out_path = f"{TMP_DIR}/{uid}_{safe_title}.mp4"

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
                            f"<code>{progress_bar(pct)}</code>"
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

    async def _safe_edit(text: str):
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return
        except Exception as e:
            if "Message is not modified" in str(e):
                return
            raise

    last_data = None
    for attempt in range(3):
        try:
            async with session.post(
                "https://www.tikwm.com/api/",
                data={"url": url},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                last_data = await r.json()

            if isinstance(last_data, dict) and last_data.get("code") == 0 and last_data.get("data"):
                break
        except Exception:
            last_data = None

        await asyncio.sleep(0.6 * (attempt + 1))

    data = last_data or {}
    info = data.get("data") or {}

    if fmt_key == "mp3":
        music_url = (
            info.get("music")
            or (info.get("music_info") or {}).get("play")
        )

        if not music_url:
            raise RuntimeError("Audio not found")

        tmp_audio = f"{TMP_DIR}/{uuid.uuid4().hex}.mp3"

        async with session.get(music_url) as r:
            with open(tmp_audio, "wb") as f:
                async for chunk in r.content.iter_chunked(64 * 1024):
                    f.write(chunk)

        title = (
            info.get("title")
            or info.get("desc")
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

    video_url = info.get("play") or info.get("wmplay") or info.get("hdplay")
    if video_url:
        title = info.get("title") or info.get("desc") or "TikTok Video"
        safe_title = sanitize_filename(title)
        uid = uuid.uuid4().hex
        out_path = f"{TMP_DIR}/{uid}_{safe_title}.mp4"

        async with session.get(video_url) as r:
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            last = 0.0

            with open(out_path, "wb") as f:
                async for chunk in r.content.iter_chunked(64 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)

                    import time
                    if total and time.time() - last >= 1.2:
                        pct = downloaded / total * 100
                        try:
                            await bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=status_msg_id,
                                text=(
                                    "<b>Downloading...</b>\n\n"
                                    f"<code>{progress_bar(pct)}</code>"
                                ),
                                parse_mode="HTML",
                            )
                        except Exception as e:
                            if "Message is not modified" not in str(e):
                                pass
                        last = time.time()

        await bot.send_chat_action(chat_id=chat_id, action="upload_video")

        bot_name = (await bot.get_me()).first_name or "Bot"
        caption = f"🎬 <b>{html.escape(title.strip() or 'TikTok Video')}</b>\n\n🪄 <i>Powered by {html.escape(bot_name)}</i>"

        await bot.send_video(
            chat_id=chat_id,
            video=open(out_path, "rb"),
            caption=caption,
            parse_mode="HTML",
            supports_streaming=False,
            reply_to_message_id=reply_to,
            disable_notification=True,
        )

        try:
            os.remove(out_path)
        except Exception:
            pass

        await bot.delete_message(chat_id, status_msg_id)
        return True

    images = info.get("images") or []
    if images:
        CHUNK_SIZE = 10
        chunks = [images[i : i + CHUNK_SIZE] for i in range(0, len(images), CHUNK_SIZE)]

        bot_name = (await bot.get_me()).first_name or "Bot"
        title = (info.get("title") or info.get("desc") or "TikTok Slideshow").strip()
        title = html.escape(title)

        caption_text = f"🖼️ <b>{title}</b>\n\n🪄 <i>Powered by {html.escape(bot_name)}</i>"

        await _safe_edit(f"🖼️ <b>Slideshow detected</b>\n\nSending album 1/{len(chunks)}...")

        for idx, chunk in enumerate(chunks):
            if idx > 0:
                await _safe_edit(f"🖼️ <b>Slideshow detected</b>\n\nSending album {idx+1}/{len(chunks)}...")

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

    raise RuntimeError("TikTok download failed (no video/images from API)")