import os
import uuid
import html
import aiohttp
import asyncio
import aiofiles
from telegram import InputMediaPhoto
from utils.http import get_http_session
from .constants import TMP_DIR
from .utils import sanitize_filename, progress_bar, is_invalid_video
from .worker import reencode_mp3
from telegram.error import RetryAfter

def is_tiktok(url: str) -> bool:
    return any(x in (url or "") for x in ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com"))


def _truncate_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return "." * limit
    return text[:limit - 3].rstrip() + "..."


def _build_safe_caption(title: str, desc: str, bot_name: str, max_len: int = 1024) -> str:
    clean_title = (title or "TikTok Video").strip() or "TikTok Video"
    clean_desc = (desc or "").strip()
    clean_bot = (bot_name or "Bot").strip() or "Bot"

    if clean_desc == clean_title:
        clean_desc = ""

    footer_plain = f"🪄 Powered by {clean_bot}"

    def plain_len(t: str, d: str) -> int:
        if d:
            return len(f"🎬 {t}\n\n{d}\n\n{footer_plain}")
        return len(f"🎬 {t}\n\n{footer_plain}")

    short_title = clean_title
    short_desc = clean_desc

    if short_desc:
        allowed_desc = max_len - len(f"🎬 {short_title}\n\n\n\n{footer_plain}")
        short_desc = _truncate_text(short_desc, allowed_desc)

    if plain_len(short_title, short_desc) > max_len:
        if short_desc:
            allowed_title = max_len - len(f"🎬 \n\n{short_desc}\n\n{footer_plain}")
        else:
            allowed_title = max_len - len(f"🎬 \n\n{footer_plain}")
        short_title = _truncate_text(short_title, allowed_title)

    if short_desc and plain_len(short_title, short_desc) > max_len:
        allowed_desc = max_len - len(f"🎬 {short_title}\n\n\n\n{footer_plain}")
        short_desc = _truncate_text(short_desc, allowed_desc)

    if not short_title:
        short_title = "TikTok Video"

    if short_desc:
        return (
            f"<blockquote expandable>🎬 {html.escape(short_title)}</blockquote>\n\n"
            f"{html.escape(short_desc)}\n\n"
            f"🪄 <i>Powered by {html.escape(clean_bot)}</i>"
        )

    return (
        f"<blockquote expandable>🎬 {html.escape(short_title)}</blockquote>\n\n"
        f"🪄 <i>Powered by {html.escape(clean_bot)}</i>"
    )


def _build_safe_album_caption(title: str, bot_name: str, max_len: int = 1024) -> str:
    clean_title = (title or "TikTok Slideshow").strip() or "TikTok Slideshow"
    clean_bot = (bot_name or "Bot").strip() or "Bot"

    footer_plain = f"🪄 Powered by {clean_bot}"
    allowed_title = max_len - len(f"🖼️ \n\n{footer_plain}")

    short_title = _truncate_text(clean_title, allowed_title)
    if not short_title:
        short_title = "TikTok Slideshow"

    return (
        f"<blockquote expandable>🖼️ {html.escape(short_title)}</blockquote>\n\n"
        f"🪄 <i>Powered by {html.escape(clean_bot)}</i>"
    )


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

    title = info.get("title") or info.get("desc") or "TikTok Video"
    safe_title = sanitize_filename(title)
    uid = uuid.uuid4().hex
    out_path = f"{TMP_DIR}/{uid}_{safe_title}.mp4"

    async with session.get(video_url) as r:
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        last = 0

        async with aiofiles.open(out_path, "wb") as f:
            async for chunk in r.content.iter_chunked(64 * 1024):
                await f.write(chunk)
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

    return {
        "path": out_path,
        "title": title.strip() or "TikTok Video",
    }


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
        except Exception as e:
            if "Message is not modified" in str(e):
                return
            raise

    async def _set_uploading(kind: str):
        label = {
            "audio": "🎵 <b>Uploading audio...</b>",
            "video": "🎬 <b>Uploading video...</b>",
            "album": "🖼️ <b>Uploading slideshow...</b>",
        }.get(kind, "<b>Uploading...</b>")

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=label,
                parse_mode="HTML",
            )
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
            async with aiofiles.open(tmp_audio, "wb") as f:
                async for chunk in r.content.iter_chunked(64 * 1024):
                    await f.write(chunk)

        title = (
            info.get("title")
            or info.get("desc")
            or "TikTok Audio"
        )

        bot_name = (await bot.get_me()).first_name or "Bot"
        fixed_audio = reencode_mp3(tmp_audio)

        await _set_uploading("audio")
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

    images = info.get("images") or []
    if images:
        CHUNK_SIZE = 10
        ALBUM_COOLDOWN = 3
        chunks = [images[i:i + CHUNK_SIZE] for i in range(0, len(images), CHUNK_SIZE)]

        bot_name = (await bot.get_me()).first_name or "Bot"
        title = (info.get("title") or info.get("desc") or "TikTok Slideshow").strip()
        caption_text = _build_safe_album_caption(title, bot_name)

        await _set_uploading("album")

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

            while True:
                try:
                    await bot.send_media_group(
                        chat_id=chat_id,
                        media=media,
                        reply_to_message_id=reply_to if idx == 0 else None,
                    )
                    break
                except RetryAfter as e:
                    wait_time = int(getattr(e, "retry_after", ALBUM_COOLDOWN)) + 1
                    await asyncio.sleep(wait_time)

            if idx < len(chunks) - 1:
                await asyncio.sleep(ALBUM_COOLDOWN)

        await bot.delete_message(chat_id, status_msg_id)
        return True

    video_url = info.get("play") or info.get("wmplay") or info.get("hdplay")
    if video_url:
        title = info.get("title") or info.get("desc") or "TikTok Video"
        desc = info.get("desc") or info.get("title") or ""
        safe_title = sanitize_filename(title)
        uid = uuid.uuid4().hex
        out_path = f"{TMP_DIR}/{uid}_{safe_title}.mp4"

        async with session.get(video_url) as r:
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            last = 0.0

            async with aiofiles.open(out_path, "wb") as f:
                async for chunk in r.content.iter_chunked(64 * 1024):
                    await f.write(chunk)
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
                            if "Message is not modified" in str(e):
                                pass
                        last = time.time()

        await _set_uploading("video")
        await bot.send_chat_action(chat_id=chat_id, action="upload_video")

        bot_name = (await bot.get_me()).first_name or "Bot"
        caption = _build_safe_caption(title, desc, bot_name)

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

    raise RuntimeError("TikTok download failed (no video/images from API)")