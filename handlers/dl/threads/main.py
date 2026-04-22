import os
import re
import time
import uuid
import html
import shutil
import asyncio
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

def progress_bar(pct: float, width: int = 10) -> str:
    try:
        pct = max(0.0, min(float(pct), 100.0))
    except Exception:
        pct = 0.0
    filled = int(round((pct / 100.0) * width))
    filled = max(0, min(filled, width))
    return "█" * filled + "░" * (width - filled) + f" {pct:.1f}%"

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
    except Exception as e:
        log.debug("Threads status edit ignored | chat_id=%s msg_id=%s err=%r", chat_id, status_msg_id, e)

def _format_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 B"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"

def _format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec <= 0:
        return "0 B/s"
    value = float(bytes_per_sec)
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1024 or unit == "GB/s":
            return f"{int(value)} {unit}" if unit == "B/s" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB/s"

def _format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

async def _safe_edit_progress(bot, chat_id, status_msg_id, title: str, downloaded: int, total: int = 0, speed_bps: float = 0.0, eta_seconds: float | None = None):
    if total > 0:
        pct = min(downloaded * 100 / total, 100.0)
    else:
        pct = 0.0
    lines = [f"<b>{html.escape(title)}</b>", ""]
    if total > 0:
        lines.append(f"<code>{progress_bar(pct)}</code>")
        lines.append(f"<code>{html.escape(_format_size(downloaded))}/{html.escape(_format_size(total))} downloaded</code>")
    else:
        lines.append(f"<code>{html.escape(_format_size(downloaded))} downloaded</code>")
    if speed_bps > 0:
        lines.append(f"<code>Speed: {html.escape(_format_speed(speed_bps))}</code>")
    if eta_seconds is not None and eta_seconds >= 0 and total > 0 and speed_bps > 0:
        lines.append(f"<code>ETA: {html.escape(_format_eta(eta_seconds))}</code>")
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text="\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.debug("Threads progress edit ignored | chat_id=%s msg_id=%s err=%r", chat_id, status_msg_id, e)

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
    _dbg("parse embed done | caption=%s items=%s", bool(result["caption"]), len(result["items"]))
    if not result["items"]:
        raise RuntimeError("no media found in threads embed")
    return result

async def _probe_total_bytes(session, url: str, headers: dict | None = None) -> int:
    total = 0
    try:
        async with session.head(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
    except Exception:
        total = 0
    if total > 0:
        return total
    try:
        h = dict(headers or {})
        h["Range"] = "bytes=0-0"
        async with session.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            content_range = resp.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)$", content_range)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 0

async def _aria2c_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, headers: dict | None = None):
    aria2 = shutil.which("aria2c")
    if not aria2:
        raise RuntimeError("aria2c not found in PATH")
    total = await _probe_total_bytes(session, media_url, headers=headers)
    out_dir = os.path.dirname(out_path) or "."
    out_name = os.path.basename(out_path)
    cmd = [
        aria2,
        "--dir", out_dir,
        "--out", out_name,
        "--file-allocation=none",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--continue=true",
        "--max-connection-per-server=8",
        "--split=8",
        "--min-split-size=1M",
        "--summary-interval=0",
        "--download-result=hide",
        "--console-log-level=warn",
    ]
    for k, v in (headers or {}).items():
        if v:
            cmd.extend(["--header", f"{k}: {v}"])
    cmd.append(media_url)
    log.info("Threads aria2c start | url=%s out=%s", media_url, out_path)
    log.debug("Threads aria2c cmd | %s", " ".join(cmd))
    _dbg("aria2c start | out=%s url=%s", out_path, _clip(media_url, 200))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    last_edit = -10.0
    last_sample_size = 0
    last_sample_ts = time.time()
    while proc.returncode is None:
        await asyncio.sleep(0.7)
        if not os.path.exists(out_path):
            continue
        try:
            downloaded = os.path.getsize(out_path)
        except Exception:
            continue
        if downloaded <= 0:
            continue
        now = time.time()
        elapsed = max(now - last_sample_ts, 0.001)
        speed_bps = max(downloaded - last_sample_size, 0) / elapsed
        eta_seconds = ((total - downloaded) / speed_bps) if total > 0 and speed_bps > 0 and downloaded <= total else None
        if now - last_edit < 2 and last_edit >= 0:
            continue
        await _safe_edit_progress(bot, chat_id, status_msg_id, title_text, downloaded, total, speed_bps, eta_seconds)
        last_edit = now
        last_sample_size = downloaded
        last_sample_ts = now
    _, stderr = await proc.communicate()
    stderr_text = stderr.decode(errors="ignore").strip() if stderr else ""
    if stderr_text:
        log.debug("Threads aria2c stderr | %s", stderr_text)
    if proc.returncode != 0:
        _dbg("aria2c failed | code=%s err=%s", proc.returncode, _clip(stderr_text, 500))
        raise RuntimeError(stderr_text or f"aria2c exited with code {proc.returncode}")
    log.info("Threads aria2c success | out=%s", out_path)
    _dbg("aria2c success | out=%s", out_path)

async def _aiohttp_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, headers: dict | None = None):
    _dbg("aiohttp fallback start | out=%s url=%s", out_path, _clip(media_url, 200))
    async with session.get(media_url, headers=headers, timeout=aiohttp.ClientTimeout(total=600), allow_redirects=True) as r:
        _dbg("aiohttp fallback response | status=%s final=%s", r.status, str(r.url))
        if r.status >= 400:
            raise RuntimeError(f"Download failed: HTTP {r.status}")
        total = int(r.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        last_edit = -10.0
        last_sample_size = 0
        last_sample_ts = time.time()
        async with aiofiles.open(out_path, "wb") as f:
            async for chunk in r.content.iter_chunked(64 * 1024):
                if not chunk:
                    continue
                await f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                elapsed = max(now - last_sample_ts, 0.001)
                speed_bps = max(downloaded - last_sample_size, 0) / elapsed
                eta_seconds = ((total - downloaded) / speed_bps) if total > 0 and speed_bps > 0 and downloaded <= total else None
                if now - last_edit < 2 and last_edit >= 0:
                    continue
                await _safe_edit_progress(bot, chat_id, status_msg_id, title_text, downloaded, total, speed_bps, eta_seconds)
                last_edit = now
                last_sample_size = downloaded
                last_sample_ts = now
    _dbg("aiohttp fallback success | out=%s", out_path)

async def _download_one_media(session, item: dict, bot, chat_id, status_msg_id, idx: int, total: int) -> dict:
    media_type = str(item.get("type") or "").strip().lower()
    media_url = str(item.get("url") or "").strip()
    if not media_url:
        raise RuntimeError("media url kosong")
    ext = ".mp4" if media_type == "video" else ".jpg"
    filename = f"{uuid.uuid4().hex}_{sanitize_filename(media_type or 'media')}{ext}"
    out_path = os.path.join(TMP_DIR, filename)
    headers = {
        "User-Agent": THREADS_HEADERS["User-Agent"],
        "Referer": "https://www.threads.net/",
    }
    title_text = f"Downloading Threads {'video' if media_type == 'video' else 'image'}... ({idx}/{total})"
    try:
        await _aria2c_download_with_progress(
            session=session,
            media_url=media_url,
            out_path=out_path,
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            title_text=title_text,
            headers=headers,
        )
    except Exception as e:
        log.warning("Threads aria2c failed, fallback aiohttp | idx=%s url=%s err=%r", idx, media_url, e)
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        await _aiohttp_download_with_progress(
            session=session,
            media_url=media_url,
            out_path=out_path,
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            title_text=title_text,
            headers=headers,
        )
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
        downloaded = await _download_one_media(
            session=session,
            item=item,
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            idx=idx,
            total=total,
        )
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