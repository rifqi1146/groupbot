import os
import re
import uuid
import html
import aiohttp
import aiofiles
import logging
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR
from handlers.dl.utils import sanitize_filename
from handlers.dl.ytdlp import ytdlp_download

log = logging.getLogger(__name__)

THREADS_URL_RE = re.compile(
    r"https?://(?:www\.)?threads\.(?:com|net)/(?:@[^/?#]+/)?(?:p|post)/([A-Za-z0-9_-]+)",
    re.I,
)

THREADS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "max-age=0",
    "Dnt": "1",
    "Priority": "u=0, i",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": "macOS",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

DEBUG_THREADS = True

def _dbg(msg: str, *args):
    if DEBUG_THREADS:
        log.warning("THREADSDBG | " + msg, *args)

def _clip(text: str, limit: int = 300) -> str:
    text = str(text or "").replace("\n", "\\n").replace("\r", "\\r")
    if len(text) <= limit:
        return text
    return text[:limit] + "...<cut>"

def is_threads_url(url: str) -> bool:
    return bool(THREADS_URL_RE.search((url or "").strip()))

def _extract_threads_post_id(url: str) -> str:
    m = THREADS_URL_RE.search((url or "").strip())
    return (m.group(1) or "").strip() if m else ""

async def _safe_edit_status(bot, chat_id, status_msg_id, text: str):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        pass

async def _fetch_threads_embed_html(post_id: str) -> bytes:
    embed_url = f"https://www.threads.net/@_/post/{post_id}/embed"
    session = await get_http_session()
    _dbg("fetch embed start | post_id=%s url=%s", post_id, embed_url)
    async with session.get(
        embed_url,
        headers=THREADS_HEADERS,
        timeout=aiohttp.ClientTimeout(total=30),
        allow_redirects=True,
    ) as resp:
        body = await resp.read()
        _dbg("fetch embed done | status=%s final=%s body_len=%s", resp.status, str(resp.url), len(body))
        if resp.status != 200:
            raise RuntimeError(f"failed to get embed media: HTTP {resp.status}")
        return body

def _normalize_media_url(src: str) -> str:
    src = (src or "").strip()
    if not src:
        return ""
    if src.startswith("//"):
        return "https:" + src
    return src

def _parse_threads_embed_media(body: bytes) -> dict:
    if b"Thread not available" in body:
        raise RuntimeError("Thread not available")

    soup = BeautifulSoup(body, "html.parser")
    result = {
        "caption": "",
        "items": [],
    }

    caption_el = soup.select_one(".BodyTextContainer")
    if caption_el:
        caption = caption_el.get_text(" ", strip=True)
        result["caption"] = html.unescape(caption or "").strip()

    seen = set()
    for container in soup.select(".MediaContainer, .SoloMediaContainer"):
        for vid in container.select("video"):
            source = vid.select_one("source")
            if not source:
                continue
            src = _normalize_media_url(source.get("src", ""))
            if not src or src in seen:
                continue
            seen.add(src)
            result["items"].append({
                "type": "video",
                "url": src,
            })

        for img in container.select("img"):
            src = _normalize_media_url(img.get("src", ""))
            if not src or src in seen:
                continue
            seen.add(src)
            result["items"].append({
                "type": "photo",
                "url": src,
            })

    _dbg(
        "parse embed done | caption=%s items=%s",
        bool(result["caption"]),
        len(result["items"]),
    )

    if not result["items"]:
        raise RuntimeError("no media found in threads embed")

    return result

async def _download_one_media(session, item: dict, headers: dict | None = None) -> dict:
    media_type = str(item.get("type") or "").strip().lower()
    media_url = str(item.get("url") or "").strip()
    if not media_url:
        raise RuntimeError("media url kosong")

    ext = ".mp4" if media_type == "video" else ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    out_path = os.path.join(TMP_DIR, filename)

    async with session.get(
        media_url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=600),
        allow_redirects=True,
    ) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"media download failed: HTTP {resp.status}")
        async with aiofiles.open(out_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(64 * 1024):
                if chunk:
                    await f.write(chunk)

    return {
        "type": media_type if media_type in {"video", "photo"} else "photo",
        "path": out_path,
        "url": media_url,
    }

async def _download_threads_items(parsed: dict, bot, chat_id, status_msg_id) -> dict | str:
    items = parsed.get("items") or []
    caption = (parsed.get("caption") or "").strip()
    title = caption or "Threads Post"

    session = await get_http_session()
    headers = {
        "User-Agent": THREADS_HEADERS["User-Agent"],
        "Referer": "https://www.threads.net/",
    }

    downloaded_items = []
    total = len(items)

    for idx, item in enumerate(items, start=1):
        label = "video" if item.get("type") == "video" else "image"
        await _safe_edit_status(
            bot,
            chat_id,
            status_msg_id,
            f"<b>Downloading Threads {label}...</b>\n\n<code>{idx}/{total}</code>",
        )
        downloaded = await _download_one_media(session, item, headers=headers)
        downloaded_items.append(downloaded)

    if len(downloaded_items) == 1:
        only = downloaded_items[0]
        return {
            "path": only["path"],
            "title": title,
        }

    return {
        "items": downloaded_items,
        "title": title,
        "desc": caption,
    }

async def threads_scrape_download(
    raw_url: str,
    fmt_key: str,
    bot,
    chat_id,
    status_msg_id,
    format_id: str | None = None,
    has_audio: bool = False,
):
    del fmt_key, format_id, has_audio

    await _safe_edit_status(bot, chat_id, status_msg_id, "<b>Scraping Threads post...</b>")

    post_id = _extract_threads_post_id(raw_url)
    _dbg("threads scrape start | url=%s post_id=%s", raw_url, post_id)
    if not post_id:
        raise RuntimeError("failed to extract threads post id")

    body = await _fetch_threads_embed_html(post_id)
    parsed = _parse_threads_embed_media(body)
    _dbg("threads parsed | items=%s caption=%s", len(parsed.get("items") or []), bool(parsed.get("caption")))

    result = await _download_threads_items(parsed, bot, chat_id, status_msg_id)
    _dbg("threads scrape success | result_type=%s", "album" if isinstance(result, dict) and result.get("items") else "single")
    return result

async def threads_download(
    raw_url: str,
    fmt_key: str,
    bot,
    chat_id,
    status_msg_id,
    format_id: str | None = None,
    has_audio: bool = False,
):
    try:
        return await threads_scrape_download(
            raw_url=raw_url,
            fmt_key=fmt_key,
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            format_id=format_id,
            has_audio=has_audio,
        )
    except Exception as e:
        log.exception("Threads scraping failed, fallback to yt-dlp | url=%s err=%r", raw_url, e)
        await _safe_edit_status(
            bot,
            chat_id,
            status_msg_id,
            "<b>Threads scraping failed</b>\n\n<i>Fallback to yt-dlp...</i>",
        )
        return await ytdlp_download(
            raw_url,
            fmt_key,
            bot,
            chat_id,
            status_msg_id,
            format_id=format_id,
            has_audio=has_audio,
        )