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


async def _tikwm_fetch(url: str, timeout_total: int):
    session = await get_http_session()
    async with session.post(
        "https://www.tikwm.com/api/",
        data={"url": url},
        timeout=aiohttp.ClientTimeout(total=timeout_total),
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"tikwm http {r.status}")
        data = await r.json()

    if not isinstance(data, dict):
        raise RuntimeError("tikwm invalid response")

    if data.get("code") != 0:
        raise RuntimeError(f"tikwm error code: {data.get('code')}")

    info = data.get("data") or {}
    if not isinstance(info, dict) or not info:
        raise RuntimeError("tikwm empty data")

    return info


async def _ytdlp_download_fallback(
    url: str,
    fmt_key: str,
    bot,
    chat_id: int,
    status_msg_id: int,
):
    from handlers.dl.ytdlp import ytdlp_download

    return await ytdlp_download(
        url=url,
        fmt_key=fmt_key,
        bot=bot,
        chat_id=chat_id,
        status_msg_id=status_msg_id,
        format_id=None,
        has_audio=False,
    )


async def douyin_download(url, bot, chat_id, status_msg_id):
    session = await get_http_session()

    try:
        info = await _tikwm_fetch(url, timeout_total=20)
        video_url = info.get("play")
        if not video_url:
            raise RuntimeError("tikwm play url missing")

        title = info.get("title") or "TikTok Video"
        safe_title = sanitize_filename(title)
        out_path = f"{TMP_DIR}/{safe_title}.mp4"

        async with session.get(
            video_url,
            timeout=aiohttp.ClientTimeout(total=120),
            allow_redirects=True,
        ) as r:
            if r.status != 200:
                raise RuntimeError(f"tikwm media http {r.status}")

            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            last = 0

            with open(out_path, "wb") as f:
                async for chunk in r.content.iter_chunked(64 * 1024):
                    if not chunk:
                        continue
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
                        except Exception:
                            pass
                        last = time.time()

        if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
            raise RuntimeError("tikwm downloaded file missing")

        return out_path

    except Exception:
        path = await _ytdlp_download_fallback(
            url=url,
            fmt_key="video",
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
        )
        return path


async def tiktok_fallback_send(
    bot,
    chat_id,
    reply_to,
    status_msg_id,
    url,
    fmt_key,
):
    session = await get_http_session()

    try:
        info = await _tikwm_fetch(url, timeout_total=15)

        if fmt_key == "mp3":
            music_url = (
                info.get("music")
                or (info.get("music_info") or {}).get("play")
            )

            if not music_url:
                raise RuntimeError("Slideshow audio not found")

            tmp_audio = f"{TMP_DIR}/{uuid.uuid4().hex}.mp3"

            async with session.get(
                music_url,
                timeout=aiohttp.ClientTimeout(total=120),
                allow_redirects=True,
            ) as r:
                if r.status != 200:
                    raise RuntimeError(f"tikwm audio http {r.status}")
                with open(tmp_audio, "wb") as f:
                    async for chunk in r.content.iter_chunked(64 * 1024):
                        if chunk:
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

            try:
                os.remove(tmp_audio)
            except Exception:
                pass
            try:
                os.remove(fixed_audio)
            except Exception:
                pass

            return True

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text="🖼️ Slideshow detected, sending album...",
            parse_mode="HTML",
        )

        images = info.get("images") or []
        if not images:
            raise RuntimeError("Slideshow images not found")

        CHUNK_SIZE = 10
        chunks = [images[i: i + CHUNK_SIZE] for i in range(0, len(images), CHUNK_SIZE)]

        bot_name = (await bot.get_me()).first_name or "Bot"
        title = (
            info.get("title")
            or info.get("desc")
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

    except Exception:
        if fmt_key == "mp3":
            path = await _ytdlp_download_fallback(
                url=url,
                fmt_key="mp3",
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
            )
            if not path or not os.path.exists(path):
                raise RuntimeError("yt-dlp fallback failed")

            await bot.send_chat_action(chat_id=chat_id, action="upload_audio")

            await bot.send_audio(
                chat_id=chat_id,
                audio=open(path, "rb"),
                title="TikTok Audio",
                performer=(await bot.get_me()).first_name or "Bot",
                filename=os.path.basename(path),
                reply_to_message_id=reply_to,
                disable_notification=True,
            )

            try:
                await bot.delete_message(chat_id, status_msg_id)
            except Exception:
                pass

            try:
                os.remove(path)
            except Exception:
                pass

            return True

        path = await _ytdlp_download_fallback(
            url=url,
            fmt_key="video",
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
        )
        if not path or not os.path.exists(path):
            raise RuntimeError("yt-dlp fallback failed")

        ext = os.path.splitext(path.lower())[1]

        try:
            if ext in (".jpg", ".jpeg", ".png", ".webp"):
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=open(path, "rb"),
                    reply_to_message_id=reply_to,
                )
            else:
                if ext in (".mp4", ".mkv", ".webm") and not is_invalid_video(path):
                    await bot.send_video(
                        chat_id=chat_id,
                        video=open(path, "rb"),
                        reply_to_message_id=reply_to,
                        supports_streaming=True,
                    )
                else:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=open(path, "rb"),
                        reply_to_message_id=reply_to,
                    )
        finally:
            try:
                await bot.delete_message(chat_id, status_msg_id)
            except Exception:
                pass
            try:
                os.remove(path)
            except Exception:
                pass

        return True