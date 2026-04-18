import os
import re
import html
import time
import uuid
import shutil
import logging
import mimetypes
import asyncio
import aiohttp
from urllib.parse import urlparse, unquote

from utils.http import get_http_session
from .constants import TMP_DIR
from .utils import sanitize_filename
from .instagram_scrape import igdl_download_for_fallback, send_instagram_fallback_result, cleanup_instagram_fallback_result

log = logging.getLogger(__name__)

_WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

def is_instagram_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
        return host == "instagram.com" or host.endswith(".instagram.com") or host == "instagr.am"
    except Exception as e:
        text = (url or "").lower()
        log.warning("Failed to parse Instagram URL host | url=%s err=%s", url, e)
        return "instagram.com" in text or "instagr.am" in text

def _normalize_instagram_url(raw_url: str) -> str:
    text = (raw_url or "").strip()
    parsed = urlparse(text)
    if not parsed.scheme:
        text = "https://" + text
        parsed = urlparse(text)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return f"https://www.instagram.com{path}/" if "instagram.com" in (parsed.netloc or "") or "instagr.am" in (parsed.netloc or "") else text

def _clean_escaped_url(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = text.replace("\\u0026", "&").replace("\\/", "/").replace("\\u0025", "%").replace("\\u003D", "=").replace("\\u002F", "/")
    return text.strip()

def _guess_ext_from_url(url: str) -> str:
    try:
        path = unquote(urlparse(url).path or "")
        ext = os.path.splitext(path)[1].lower()
        if ext in (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp"):
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

def _uniq(seq: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in seq:
        val = (item or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out

def _extract_meta(html_text: str, key: str) -> str:
    pats = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for pat in pats:
        m = re.search(pat, html_text, flags=re.I)
        if m:
            return html.unescape((m.group(1) or "").strip())
    return ""

def _extract_caption(html_text: str) -> str:
    for key in ("og:title", "og:description", "description", "twitter:description"):
        val = _extract_meta(html_text, key)
        if val:
            return val
    return ""

def _extract_json_urls(html_text: str) -> tuple[list[str], list[str]]:
    text = html_text or ""
    videos = []
    photos = []
    for m in re.findall(r'"video_url":"([^"]+)"', text):
        videos.append(_clean_escaped_url(m))
    for m in re.findall(r'"display_url":"([^"]+)"', text):
        photos.append(_clean_escaped_url(m))
    for m in re.findall(r'"image_versions2".*?"url":"([^"]+)"', text):
        photos.append(_clean_escaped_url(m))
    for m in re.findall(r'"src":"(https:[^"]+)"', text):
        u = _clean_escaped_url(m)
        ext = _guess_ext_from_url(u)
        if ext in (".mp4", ".mov", ".m4v", ".webm"):
            videos.append(u)
        elif ext in (".jpg", ".jpeg", ".png", ".webp"):
            photos.append(u)
    for m in re.findall(r'https:\\/\\/[^"\']+', text):
        u = _clean_escaped_url(m)
        if "cdninstagram" not in u and "fbcdn.net" not in u and "scontent" not in u:
            continue
        ext = _guess_ext_from_url(u)
        if ext in (".mp4", ".mov", ".m4v", ".webm"):
            videos.append(u)
        elif ext in (".jpg", ".jpeg", ".png", ".webp"):
            photos.append(u)
    return _uniq(videos), _uniq(photos)

def _extract_media_candidates_from_html(html_text: str) -> dict:
    caption = _extract_caption(html_text)
    videos, photos = _extract_json_urls(html_text)
    og_video = _extract_meta(html_text, "og:video") or _extract_meta(html_text, "og:video:secure_url")
    og_image = _extract_meta(html_text, "og:image")
    if og_video:
        videos = _uniq([og_video] + videos)
    if og_image:
        photos = _uniq([og_image] + photos)
    return {"caption": caption, "videos": videos, "photos": photos}

def _build_title(caption: str, media_type: str) -> str:
    text = (caption or "").strip()
    if text:
        return text[:120].strip()
    if media_type == "video":
        return "Instagram Video"
    return "Instagram Image"

def _pick_media_for_format(meta: dict, fmt_key: str) -> list[tuple[str, str]]:
    videos = list(meta.get("videos") or [])
    photos = list(meta.get("photos") or [])
    if fmt_key == "mp3":
        if videos:
            return [("video", videos[0])]
        return []
    if videos:
        return [("video", videos[0])]
    if photos:
        if len(photos) == 1:
            return [("photo", photos[0])]
        return [("photo", x) for x in photos]
    return []

async def _safe_edit_status(bot, chat_id, message_id, text: str):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML")
    except Exception as e:
        log.warning("Failed to edit Instagram status message | chat_id=%s message_id=%s err=%s", chat_id, message_id, e)

def _format_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"

def _format_speed(num_bytes_per_sec: float) -> str:
    if num_bytes_per_sec <= 0:
        return "0 B/s"
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    size = float(num_bytes_per_sec)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"

def _format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

async def _probe_media_meta(session, media_url: str) -> tuple[int, str]:
    total = 0
    content_type = ""
    try:
        async with session.head(media_url, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True, headers=_WEB_HEADERS) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            content_type = resp.headers.get("Content-Type", "") or ""
    except Exception:
        total = 0
        content_type = ""
    if total > 0 or content_type:
        return total, content_type
    try:
        async with session.get(media_url, headers={**_WEB_HEADERS, "Range": "bytes=0-0"}, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            content_range = resp.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)$", content_range)
            if m:
                total = int(m.group(1))
            elif resp.headers.get("Content-Length"):
                total = int(resp.headers.get("Content-Length", 0) or 0)
            content_type = resp.headers.get("Content-Type", "") or ""
    except Exception:
        pass
    return total, content_type

async def _safe_edit_progress(bot, chat_id, status_msg_id, title_text: str, downloaded: int, total: int, speed_bps: float, eta_seconds: float | None):
    pct = 0.0
    if total > 0:
        pct = min((downloaded / total) * 100.0, 100.0)
    lines = [f"<b>{title_text}</b>", ""]
    if total > 0:
        lines.append(f"<code>{_format_size(downloaded)} / {_format_size(total)}</code>")
        lines.append(f"<code>{pct:.1f}%</code>")
    else:
        lines.append(f"<code>{_format_size(downloaded)} downloaded</code>")
    lines.append(f"<code>Speed: {_format_speed(speed_bps)}</code>")
    lines.append(f"<code>ETA: {_format_eta(eta_seconds)}</code>")
    await _safe_edit_status(bot, chat_id, status_msg_id, "\n".join(lines))

async def _aria2c_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, total: int):
    aria2 = shutil.which("aria2c")
    if not aria2:
        raise RuntimeError("aria2c not found in PATH")
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
        media_url,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
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
        if now - last_edit < 3 and last_edit >= 0:
            continue
        await _safe_edit_progress(bot, chat_id, status_msg_id, title_text, downloaded, total, speed_bps, eta_seconds)
        last_edit = now
        last_sample_size = downloaded
        last_sample_ts = now
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="ignore").strip() if stderr else ""
        raise RuntimeError(err or f"aria2c exited with code {proc.returncode}")

async def _download_one_instagram_media(session, media_url: str, media_type: str, title: str, bot, chat_id, status_msg_id, index_text: str):
    total, content_type = await _probe_media_meta(session, media_url)
    ext = _guess_ext(content_type, media_type, media_url)
    safe_title = sanitize_filename(title or ("Instagram Video" if media_type == "video" else "Instagram Image"))
    out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{safe_title}{ext}")
    await _aria2c_download_with_progress(
        session=session,
        media_url=media_url,
        out_path=out_path,
        bot=bot,
        chat_id=chat_id,
        status_msg_id=status_msg_id,
        title_text=index_text,
        total=total,
    )
    if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
        raise RuntimeError("Downloaded Instagram media is empty")
    return out_path

async def _fetch_instagram_html(session, raw_url: str) -> str:
    url = _normalize_instagram_url(raw_url)
    async with session.get(url, headers=_WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=30), allow_redirects=True) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Instagram page request failed: HTTP {resp.status}")
        return await resp.text()

async def instagram_api_download(raw_url: str, fmt_key: str, bot, chat_id, status_msg_id):
    session = await get_http_session()
    downloaded_paths = []
    await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>Fetching Instagram media...</b>")
    try:
        html_text = await _fetch_instagram_html(session, raw_url)
        meta = _extract_media_candidates_from_html(html_text)
        picked_items = _pick_media_for_format(meta, fmt_key)
        if not picked_items:
            if fmt_key == "mp3":
                raise RuntimeError("Instagram image post does not contain audio")
            raise RuntimeError("No downloadable Instagram media found")
        title = _build_title(meta.get("caption") or "", picked_items[0][0])
        if len(picked_items) == 1:
            media_type, media_url = picked_items[0]
            out_path = await _download_one_instagram_media(
                session=session,
                media_url=media_url,
                media_type=media_type,
                title=title,
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
                index_text="Downloading Instagram media...",
            )
            downloaded_paths.append(out_path)
            return {"path": out_path, "title": title}
        items = []
        total_items = len(picked_items)
        for idx, (media_type, media_url) in enumerate(picked_items, start=1):
            item_title = title if idx == 1 else f"{title} {idx}"
            out_path = await _download_one_instagram_media(
                session=session,
                media_url=media_url,
                media_type=media_type,
                title=item_title,
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
                index_text=f"Downloading Instagram media {idx}/{total_items}...",
            )
            downloaded_paths.append(out_path)
            items.append({"path": out_path, "type": media_type})
        return {"items": items, "title": title, "source": "Instagram"}
    except Exception as e:
        log.warning("Instagram extractor failed, falling back to Indown | url=%s fmt=%s err=%r", raw_url, fmt_key, e)
        for path in downloaded_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception as cleanup_err:
                log.warning("Failed to remove partial Instagram file | path=%s err=%s", path, cleanup_err)
    await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>Instagram extractor failed, fallback to Indown...</b>")
    return await igdl_download_for_fallback(
        bot=bot,
        chat_id=chat_id,
        reply_to=None,
        status_msg_id=status_msg_id,
        url=raw_url,
    )

async def send_instagram_result(bot, chat_id: int, reply_to: int, result: dict):
    if result.get("items"):
        await send_instagram_fallback_result(bot=bot, chat_id=chat_id, reply_to=reply_to, result=result)
        return
    path = result.get("path")
    title = result.get("title") or "Instagram Media"
    if not path or not os.path.exists(path):
        raise RuntimeError("Instagram media file not found")
    with open(path, "rb") as f:
        if path.lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
            await bot.send_video(chat_id=chat_id, video=f, caption=title, reply_to_message_id=reply_to, supports_streaming=True)
        else:
            await bot.send_photo(chat_id=chat_id, photo=f, caption=title, reply_to_message_id=reply_to)

async def cleanup_instagram_result(result: dict):
    await cleanup_instagram_fallback_result(result)