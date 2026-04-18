import os
import time
import uuid
import logging
import mimetypes
import aiohttp
import aiofiles
from urllib.parse import urlparse, unquote

from utils.http import get_http_session
from .constants import TMP_DIR
from .utils import sanitize_filename, progress_bar
from .instagram_scrape import (
    igdl_download_for_fallback,
    send_instagram_fallback_result,
    cleanup_instagram_fallback_result,
)

INSTAGRAM_API_URL = "https://api.sonzaix.indevs.in/sosmed/instagram"

log = logging.getLogger(__name__)


def is_instagram_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
        return host == "instagram.com" or host.endswith(".instagram.com") or host == "instagr.am"
    except Exception as e:
        text = (url or "").lower()
        log.warning("Failed to parse Instagram URL host | url=%s err=%s", url, e)
        return "instagram.com" in text or "instagr.am" in text


def _guess_ext_from_url(url: str) -> str:
    try:
        path = unquote(urlparse(url).path or "")
        ext = os.path.splitext(path)[1].lower()
        if ext in (".mp4", ".mov", ".m4v", ".jpg", ".jpeg", ".png", ".webp"):
            return ext
    except Exception as e:
        log.warning("Failed to guess extension from media URL | url=%s err=%s", url, e)
    return ""


def _guess_ext(content_type: str, media_type: str, media_url: str) -> str:
    ext = _guess_ext_from_url(media_url)
    if ext:
        return ext

    ctype = (content_type or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(ctype) or ""
    if guessed:
        return guessed

    if media_type == "video":
        return ".mp4"
    return ".jpg"


def _build_title(data: dict, media_type: str) -> str:
    nickname = (data.get("nickname") or "").strip()
    username = (data.get("username") or "").strip()
    description = (data.get("description") or "").strip()

    if nickname and username:
        base = f"{nickname} (@{username})"
    elif nickname:
        base = nickname
    elif username:
        base = f"@{username}"
    else:
        base = "Instagram Media"

    if description:
        short_desc = description[:80].strip()
        return f"{base} - {short_desc}"

    if media_type == "video":
        return f"{base} - Instagram Video"

    return f"{base} - Instagram Image"


def _extract_media_candidates(data: dict) -> list[tuple[str, str]]:
    out = []

    def add_candidate(kind: str, url: str):
        u = (url or "").strip()
        if not u:
            return
        item = (kind, u)
        if item not in out:
            out.append(item)

    add_candidate("video", data.get("video_url"))
    add_candidate("photo", data.get("image_url"))
    add_candidate("photo", data.get("photo_url"))
    add_candidate("photo", data.get("image"))
    add_candidate("photo", data.get("thumbnail"))

    for key in ("images", "image_urls", "photos"):
        items = data.get(key) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    add_candidate("photo", item)
                elif isinstance(item, dict):
                    add_candidate("photo", item.get("url") or item.get("image") or item.get("src"))

    for key in ("videos", "video_urls"):
        items = data.get(key) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    add_candidate("video", item)
                elif isinstance(item, dict):
                    add_candidate("video", item.get("url") or item.get("video") or item.get("src"))

    for key in ("media", "medias", "items", "carousel", "carousel_media"):
        items = data.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, str):
                add_candidate("photo", item)
                continue
            if not isinstance(item, dict):
                continue

            media_type = str(
                item.get("type")
                or item.get("media_type")
                or item.get("kind")
                or ""
            ).lower()

            media_url = (
                item.get("url")
                or item.get("download_url")
                or item.get("media_url")
                or item.get("video_url")
                or item.get("image_url")
                or item.get("src")
            )

            if not media_url:
                continue

            if "video" in media_type or media_type in ("2", "clip", "reel"):
                add_candidate("video", media_url)
            else:
                add_candidate("photo", media_url)

    return out


def _pick_media_for_format(candidates: list[tuple[str, str]], fmt_key: str) -> tuple[str, str] | None:
    if not candidates:
        return None

    if fmt_key == "mp3":
        for kind, url in candidates:
            if kind == "video":
                return kind, url
        return None

    for kind, url in candidates:
        if kind == "video":
            return kind, url

    return candidates[0]


async def _safe_edit_status(bot, chat_id, message_id, text: str):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning(
            "Failed to edit Instagram status message | chat_id=%s message_id=%s err=%s",
            chat_id,
            message_id,
            e,
        )


async def instagram_api_download(
    raw_url: str,
    fmt_key: str,
    bot,
    chat_id,
    status_msg_id,
):
    session = await get_http_session()
    out_path = None

    await _safe_edit_status(
        bot=bot,
        chat_id=chat_id,
        message_id=status_msg_id,
        text="<b>Fetching Instagram media...</b>",
    )

    try:
        async with session.get(
            INSTAGRAM_API_URL,
            params={"url": raw_url},
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Instagram API request failed: HTTP {resp.status}")

            data = await resp.json(content_type=None)

        if not isinstance(data, dict):
            raise RuntimeError("Instagram API returned invalid response")

        if str(data.get("status") or "").lower() != "success":
            raise RuntimeError(data.get("message") or "Instagram API request failed")

        candidates = _extract_media_candidates(data)
        picked = _pick_media_for_format(candidates, fmt_key)

        if not picked:
            if fmt_key == "mp3":
                raise RuntimeError("Instagram image post does not contain audio")
            raise RuntimeError("No downloadable Instagram media found")

        media_type, media_url = picked
        title = _build_title(data, media_type)

        async with session.get(
            media_url,
            timeout=aiohttp.ClientTimeout(total=180),
        ) as media_resp:
            if media_resp.status >= 400:
                raise RuntimeError(f"Failed to download media: HTTP {media_resp.status}")

            total = int(media_resp.headers.get("Content-Length", 0))
            content_type = media_resp.headers.get("Content-Type", "")
            ext = _guess_ext(content_type, media_type, media_url)

            safe_title = sanitize_filename(title)
            out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{safe_title}{ext}")

            downloaded = 0
            last = 0.0

            async with aiofiles.open(out_path, "wb") as f:
                async for chunk in media_resp.content.iter_chunked(64 * 1024):
                    await f.write(chunk)
                    downloaded += len(chunk)

                    if total and time.time() - last >= 1.0:
                        pct = downloaded / total * 100
                        await _safe_edit_status(
                            bot=bot,
                            chat_id=chat_id,
                            message_id=status_msg_id,
                            text=(
                                "<b>Download use sonzai api...</b>\n\n"
                                f"<code>{progress_bar(pct)}</code>"
                            ),
                        )
                        last = time.time()

        return {
            "path": out_path,
            "title": title,
        }

    except Exception as e:
        log.warning(
            "Instagram Sonzai API download failed, falling back to Indown | url=%s fmt=%s err=%r",
            raw_url,
            fmt_key,
            e,
        )

        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception as cleanup_err:
                log.warning(
                    "Failed to remove partial Instagram API file | path=%s err=%s",
                    out_path,
                    cleanup_err,
                )

    await _safe_edit_status(
        bot=bot,
        chat_id=chat_id,
        message_id=status_msg_id,
        text="<b>Sonzai failed, fallback to Indown...</b>",
    )

    return await igdl_download_for_fallback(
        bot=bot,
        chat_id=chat_id,
        reply_to=None,
        status_msg_id=status_msg_id,
        url=raw_url,
    )


async def send_instagram_result(bot, chat_id: int, reply_to: int, result: dict):
    if result.get("items"):
        await send_instagram_fallback_result(
            bot=bot,
            chat_id=chat_id,
            reply_to=reply_to,
            result=result,
        )
        return

    path = result.get("path")
    title = result.get("title") or "Instagram Media"

    if not path or not os.path.exists(path):
        raise RuntimeError("Instagram media file not found")

    with open(path, "rb") as f:
        if path.lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
            await bot.send_video(
                chat_id=chat_id,
                video=f,
                caption=title,
                reply_to_message_id=reply_to,
                supports_streaming=True,
            )
        else:
            await bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=title,
                reply_to_message_id=reply_to,
            )


async def cleanup_instagram_result(result: dict):
    await cleanup_instagram_fallback_result(result)
    