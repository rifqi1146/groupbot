import os
import re
import time
import uuid
import html
import shutil
import json
import asyncio
import aiohttp
import aiofiles
import logging
from urllib.parse import urlparse
from telegram import InputMediaPhoto
from telegram.error import RetryAfter
from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR
from handlers.dl.utils import sanitize_filename, is_invalid_video
from handlers.dl.service import reencode_mp3, send_downloaded_media

log = logging.getLogger(__name__)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
WEB_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "navigate",
}
UNIVERSAL_RE = re.compile(r'<script[^>]+\bid="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S | re.I)
SIGI_RE = re.compile(r'<script[^>]+\bid="SIGI_STATE"[^>]*>(.*?)</script>', re.S | re.I)
NEXT_RE = re.compile(r'<script[^>]+\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)

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
        return len(f"🎬 {t}\n\n{d}\n\n{footer_plain}") if d else len(f"🎬 {t}\n\n{footer_plain}")
    short_title, short_desc = clean_title, clean_desc
    if short_desc:
        allowed_desc = max_len - len(f"🎬 {short_title}\n\n\n\n{footer_plain}")
        short_desc = _truncate_text(short_desc, allowed_desc)
    if plain_len(short_title, short_desc) > max_len:
        allowed_title = max_len - len(f"🎬 \n\n{short_desc}\n\n{footer_plain}") if short_desc else max_len - len(f"🎬 \n\n{footer_plain}")
        short_title = _truncate_text(short_title, allowed_title)
    if short_desc and plain_len(short_title, short_desc) > max_len:
        allowed_desc = max_len - len(f"🎬 {short_title}\n\n\n\n{footer_plain}")
        short_desc = _truncate_text(short_desc, allowed_desc)
    if not short_title:
        short_title = "TikTok Video"
    if short_desc:
        return f"<blockquote expandable>🎬 {html.escape(short_title)}</blockquote>\n\n{html.escape(short_desc)}\n\n🪄 <i>Powered by {html.escape(clean_bot)}</i>"
    return f"<blockquote expandable>🎬 {html.escape(short_title)}</blockquote>\n\n🪄 <i>Powered by {html.escape(clean_bot)}</i>"

def _build_safe_album_caption(title: str, bot_name: str, max_len: int = 1024) -> str:
    clean_title = (title or "TikTok Slideshow").strip() or "TikTok Slideshow"
    clean_bot = (bot_name or "Bot").strip() or "Bot"
    footer_plain = f"🪄 Powered by {clean_bot}"
    allowed_title = max_len - len(f"🖼️ \n\n{footer_plain}")
    short_title = _truncate_text(clean_title, allowed_title)
    if not short_title:
        short_title = "TikTok Slideshow"
    return f"<blockquote expandable>🖼️ {html.escape(short_title)}</blockquote>\n\n🪄 <i>Powered by {html.escape(clean_bot)}</i>"

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
    lines = [f"<b>{html.escape(title)}</b>", ""]
    if total > 0:
        pct = min(downloaded * 100 / total, 100.0)
        lines.append(f"<code>{html.escape(_format_size(downloaded))}/{html.escape(_format_size(total))} downloaded</code>")
        lines.append(f"<code>{pct:.1f}%</code>")
    else:
        lines.append(f"<code>{html.escape(_format_size(downloaded))} downloaded</code>")
    if speed_bps > 0:
        lines.append(f"<code>Speed: {html.escape(_format_speed(speed_bps))}</code>")
    if eta_seconds is not None and eta_seconds >= 0 and total > 0 and speed_bps > 0:
        lines.append(f"<code>ETA: {html.escape(_format_eta(eta_seconds))}</code>")
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text="\n".join(lines), parse_mode="HTML")
    except Exception:
        pass

async def _safe_edit_status(bot, chat_id, status_msg_id, text: str):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        if "Message is not modified" in str(e):
            return
        raise

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
            if resp.headers.get("Content-Length"):
                return int(resp.headers.get("Content-Length", 0) or 0)
    except Exception:
        pass
    return 0

def _cookie_header(cookies: list[dict] | None) -> str:
    if not cookies:
        return ""
    parts = []
    for c in cookies:
        name = str((c or {}).get("name") or "").strip()
        value = str((c or {}).get("value") or "").strip()
        if name:
            parts.append(f"{name}={value}")
    return "; ".join(parts)

async def _aria2c_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, headers: dict | None = None):
    aria2 = shutil.which("aria2c")
    if not aria2:
        raise RuntimeError("aria2c not found in PATH")
    total = await _probe_total_bytes(session, media_url, headers=headers)
    out_dir, out_name = os.path.dirname(out_path) or ".", os.path.basename(out_path)
    cmd = [
        aria2, "--dir", out_dir, "--out", out_name, "--file-allocation=none", "--allow-overwrite=true", "--auto-file-renaming=false",
        "--continue=true", "--max-connection-per-server=8", "--split=8", "--min-split-size=1M", "--summary-interval=0",
        "--download-result=hide", "--console-log-level=warn"
    ]
    for k, v in (headers or {}).items():
        if v:
            cmd.extend(["--header", f"{k}: {v}"])
    cmd.append(media_url)
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    last_edit, last_sample_size, last_sample_ts = -10.0, 0, time.time()
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
        last_edit, last_sample_size, last_sample_ts = now, downloaded, now
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="ignore").strip() if stderr else ""
        raise RuntimeError(err or f"aria2c exited with code {proc.returncode}")

async def _aiohttp_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, headers: dict | None = None):
    async with session.get(media_url, headers=headers, timeout=aiohttp.ClientTimeout(total=600), allow_redirects=True) as r:
        if r.status >= 400:
            raise RuntimeError(f"Download failed: HTTP {r.status}")
        total, downloaded, last_edit, last_sample_size, last_sample_ts = int(r.headers.get("Content-Length", 0) or 0), 0, -10.0, 0, time.time()
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
                if now - last_edit < 3 and last_edit >= 0:
                    continue
                await _safe_edit_progress(bot, chat_id, status_msg_id, title_text, downloaded, total, speed_bps, eta_seconds)
                last_edit, last_sample_size, last_sample_ts = now, downloaded, now

async def _download_with_best_engine(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, headers: dict | None = None):
    try:
        await _aria2c_download_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id, title_text, headers=headers)
    except Exception as e:
        log.warning("TikTok aria2c failed, fallback aiohttp | err=%r", e)
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        await _aiohttp_download_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id, title_text, headers=headers)

def _extract_aweme_id(url: str) -> str:
    m = re.search(r"/(?:video|photo)/(\d+)", url or "", flags=re.I)
    return (m.group(1) if m else "").strip()

async def _resolve_tiktok_url(url: str) -> str:
    session = await get_http_session()
    async with session.get(url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
        return str(resp.url)

def _json_walk(obj, key: str):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _json_walk(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _json_walk(item, key)
            if found is not None:
                return found
    return None

def _pick_first_url(value) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for x in value:
            if isinstance(x, str) and x.strip():
                return x.strip()
    return ""

def _parse_direct_media(item: dict) -> dict:
    desc = str(item.get("desc") or item.get("description") or "").strip()
    title = desc or "TikTok Video"
    image_post = item.get("imagePost") or item.get("image_post") or {}
    if isinstance(image_post, dict) and isinstance(image_post.get("images"), list) and image_post.get("images"):
        images = []
        for img in image_post.get("images") or []:
            image_url = _pick_first_url(
                (((img or {}).get("imageURL") or {}).get("urlList"))
                or (((img or {}).get("displayImage") or {}).get("urlList"))
                or (((img or {}).get("ownerWatermarkImage") or {}).get("urlList"))
            )
            if image_url:
                images.append(image_url)
        if images:
            return {"kind": "album", "title": title, "desc": desc, "images": images}
    video = item.get("video") or {}
    for candidate in (
        video.get("playAddr"), video.get("playAddrStruct"), video.get("downloadAddr"), video.get("downloadAddrStruct"),
        ((video.get("bitrateInfo") or [{}])[0] if isinstance(video.get("bitrateInfo"), list) and video.get("bitrateInfo") else {}).get("PlayAddr"),
        ((video.get("bitrateInfo") or [{}])[0] if isinstance(video.get("bitrateInfo"), list) and video.get("bitrateInfo") else {}).get("playAddr"),
    ):
        if isinstance(candidate, dict):
            video_url = _pick_first_url(candidate.get("urlList") or candidate.get("UrlList"))
            if video_url:
                return {"kind": "video", "title": title, "desc": desc, "video_url": video_url}
        elif isinstance(candidate, str) and candidate.strip():
            return {"kind": "video", "title": title, "desc": desc, "video_url": candidate.strip()}
    raise RuntimeError("TikTok direct media URL not found")

def _parse_universal_data(html_text: str) -> dict:
    m = UNIVERSAL_RE.search(html_text or "")
    if not m:
        raise RuntimeError("TikTok universal data not found")
    try:
        data = json.loads(m.group(1))
    except Exception as e:
        raise RuntimeError(f"Failed to parse TikTok universal data: {e}") from e
    default_scope = data.get("__DEFAULT_SCOPE__")
    if not isinstance(default_scope, dict):
        raise RuntimeError("TikTok default scope not found")
    item_struct = default_scope.get("itemStruct")
    if not isinstance(item_struct, dict):
        item_module = default_scope.get("webapp.video-detail")
        if isinstance(item_module, dict):
            item_info = item_module.get("itemInfo") or {}
            item_struct = item_info.get("itemStruct") if isinstance(item_info, dict) else None
    if not isinstance(item_struct, dict):
        item_struct = _json_walk(default_scope, "itemStruct")
    if not isinstance(item_struct, dict):
        raise RuntimeError("TikTok itemStruct not found")
    return item_struct

def _parse_sigi_state(html_text: str) -> dict:
    m = SIGI_RE.search(html_text or "")
    if not m:
        raise RuntimeError("TikTok SIGI_STATE not found")
    try:
        data = json.loads(m.group(1))
    except Exception as e:
        raise RuntimeError(f"Failed to parse TikTok SIGI_STATE: {e}") from e
    item_module = data.get("ItemModule")
    if isinstance(item_module, dict) and item_module:
        first = next(iter(item_module.values()), None)
        if isinstance(first, dict):
            return first
    detail = data.get("VideoPage") or data.get("ItemPage") or {}
    item_struct = detail.get("itemInfo", {}).get("itemStruct") if isinstance(detail, dict) else None
    if isinstance(item_struct, dict):
        return item_struct
    item_struct = _json_walk(data, "itemStruct")
    if isinstance(item_struct, dict):
        return item_struct
    raise RuntimeError("TikTok itemStruct not found in SIGI_STATE")

def _parse_next_data(html_text: str) -> dict:
    m = NEXT_RE.search(html_text or "")
    if not m:
        raise RuntimeError("TikTok __NEXT_DATA__ not found")
    try:
        data = json.loads(m.group(1))
    except Exception as e:
        raise RuntimeError(f"Failed to parse TikTok __NEXT_DATA__: {e}") from e
    item_struct = _json_walk(data, "itemStruct")
    if isinstance(item_struct, dict):
        return item_struct
    raise RuntimeError("TikTok itemStruct not found in __NEXT_DATA__")

def _extract_item_struct(html_text: str) -> dict:
    errors = []
    for parser in (_parse_universal_data, _parse_sigi_state, _parse_next_data):
        try:
            item = parser(html_text)
            if isinstance(item, dict) and item:
                return item
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError(" ; ".join(errors) if errors else "TikTok itemStruct not found")

async def _fetch_tiktok_direct(url: str) -> dict:
    resolved = await _resolve_tiktok_url(url)
    aweme_id = _extract_aweme_id(resolved)
    if not aweme_id:
        raise RuntimeError("TikTok aweme id not found")
    targets = [resolved, f"https://www.tiktok.com/@_/video/{aweme_id}", f"https://www.tiktok.com/embed/v3/{aweme_id}"]
    session = await get_http_session()
    last_err = None
    for target in targets:
        for attempt in range(4):
            try:
                async with session.get(target, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as resp:
                    final_url = str(resp.url)
                    if "/login" in final_url:
                        raise RuntimeError("TikTok returned login page")
                    html_text = await resp.text()
                    cookies = [{"name": c.key, "value": c.value} for c in resp.cookies.values()]
                item_struct = _extract_item_struct(html_text)
                media = _parse_direct_media(item_struct)
                media["cookies"] = cookies
                media["resolved_url"] = resolved
                media["aweme_id"] = aweme_id
                media["target_url"] = target
                return media
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.35 * (attempt + 1))
    raise RuntimeError(f"TikTok scraping failed: {last_err}")

async def _download_direct_video(media: dict, bot, chat_id, status_msg_id) -> dict:
    session = await get_http_session()
    title = (media.get("title") or "TikTok Video").strip()
    video_url = media.get("video_url") or ""
    cookie_header = _cookie_header(media.get("cookies"))
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.tiktok.com/"}
    if cookie_header:
        headers["Cookie"] = cookie_header
    out_path = f"{TMP_DIR}/{uuid.uuid4().hex}_{sanitize_filename(title)}.mp4"
    await _download_with_best_engine(session, video_url, out_path, bot, chat_id, status_msg_id, "Downloading TikTok video (scraping)...", headers=headers)
    if is_invalid_video(out_path):
        try:
            os.remove(out_path)
        except Exception:
            pass
        raise RuntimeError("Invalid video file from TikTok scraping")
    log.info("TikTok direct scraping success | type=video file=%s", out_path)
    return {"path": out_path, "title": title, "desc": media.get("desc") or "", "source": "scraping"}

async def _download_album_images(session, image_urls: list[str], title: str, bot, chat_id, status_msg_id, headers: dict | None = None) -> list[dict]:
    if not image_urls:
        return []
    total = len(image_urls)
    sem = asyncio.Semaphore(8)
    results = [None] * total

    async def one(idx: int, image_url: str):
        async with sem:
            safe_title = sanitize_filename(title or "TikTok Slideshow")
            out_path = f"{TMP_DIR}/{uuid.uuid4().hex}_{safe_title}_{idx + 1}.jpg"
            try:
                async with session.get(image_url, headers=headers, timeout=aiohttp.ClientTimeout(total=120), allow_redirects=True) as r:
                    if r.status >= 400:
                        raise RuntimeError(f"Image HTTP {r.status}")
                    async with aiofiles.open(out_path, "wb") as f:
                        async for chunk in r.content.iter_chunked(64 * 1024):
                            if chunk:
                                await f.write(chunk)
                results[idx] = {"type": "photo", "path": out_path}
                await _safe_edit_status(bot, chat_id, status_msg_id, f"<b>Downloading TikTok slideshow...</b>\n\n<code>{idx + 1}/{total} photos</code>")
            except Exception:
                log.exception("Failed to download slideshow image | index=%s url=%s", idx, image_url)
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)
                except Exception:
                    pass
                raise

    await asyncio.gather(*(one(i, url) for i, url in enumerate(image_urls)))
    return [x for x in results if x]

async def _download_direct_album(media: dict, bot, chat_id, status_msg_id) -> dict:
    session = await get_http_session()
    title = (media.get("title") or "TikTok Slideshow").strip()
    image_urls = [u for u in (media.get("images") or []) if u]
    if not image_urls:
        raise RuntimeError("TikTok slideshow images not found")
    cookie_header = _cookie_header(media.get("cookies"))
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.tiktok.com/"}
    if cookie_header:
        headers["Cookie"] = cookie_header
    items = await _download_album_images(session, image_urls, title, bot, chat_id, status_msg_id, headers=headers)
    if not items:
        raise RuntimeError("TikTok slideshow download failed")
    log.info("TikTok direct scraping success | type=album items=%s", len(items))
    return {"items": items, "title": title, "desc": media.get("desc") or "", "source": "scraping"}

async def tiktok_scrape_download(url, bot, chat_id, status_msg_id, fmt_key="mp4"):
    await _safe_edit_status(bot, chat_id, status_msg_id, "<b>Scraping TikTok metadata...</b>")
    media = await _fetch_tiktok_direct(url)
    kind = media.get("kind")
    log.info("TikTok scraping metadata success | url=%s kind=%s title=%r target=%s", url, kind, media.get("title"), media.get("target_url"))
    if fmt_key == "mp3":
        if kind != "video":
            raise RuntimeError("TikTok slideshow does not contain audio")
        return await _download_direct_video(media, bot, chat_id, status_msg_id)
    if kind == "video":
        return await _download_direct_video(media, bot, chat_id, status_msg_id)
    if kind == "album":
        await _safe_edit_status(bot, chat_id, status_msg_id, "<b>TikTok slideshow detected (scraping)...</b>")
        return await _download_direct_album(media, bot, chat_id, status_msg_id)
    raise RuntimeError("Unsupported TikTok media type")

async def douyin_download(url, bot, chat_id, status_msg_id):
    session = await get_http_session()
    async with session.post("https://www.tikwm.com/api/", data={"url": url}, timeout=aiohttp.ClientTimeout(total=20)) as r:
        data = await r.json()
    if data.get("code") != 0:
        raise RuntimeError("Douyin API error")
    info = data.get("data") or {}
    images = info.get("images") or info.get("image") or []
    if isinstance(images, list) and len(images) > 0:
        raise RuntimeError("SLIDESHOW")
    video_url = info.get("hdplay") or info.get("play") or info.get("wmplay") or info.get("play_url")
    if not video_url:
        raise RuntimeError("Video URL kosong")
    title = info.get("title") or info.get("desc") or "TikTok Video"
    out_path = f"{TMP_DIR}/{uuid.uuid4().hex}_{sanitize_filename(title)}.mp4"
    log.info("TikTok fallback start | source=tikwm url=%s", url)
    await _download_with_best_engine(session, video_url, out_path, bot, chat_id, status_msg_id, "Downloading TikTok video (tikwm)...")
    log.info("TikTok fallback success | source=tikwm file=%s", out_path)
    return {"path": out_path, "title": title.strip() or "TikTok Video", "source": "tikwm"}

async def tiktok_download(url, bot, chat_id, status_msg_id, fmt_key="mp4"):
    try:
        log.info("TikTok primary start | source=scraping url=%s fmt=%s", url, fmt_key)
        result = await tiktok_scrape_download(url=url, bot=bot, chat_id=chat_id, status_msg_id=status_msg_id, fmt_key=fmt_key)
        if isinstance(result, dict):
            if result.get("path"):
                log.info("TikTok primary success | source=scraping file=%s", result.get("path"))
            elif result.get("items"):
                log.info("TikTok primary success | source=scraping items=%s", len(result.get("items") or []))
        return result
    except Exception as e:
        log.exception("TikTok primary failed | source=scraping url=%s fmt=%s err=%r", url, fmt_key, e)
        raise

async def tiktok_fallback_send(bot, chat_id, reply_to, status_msg_id, url, fmt_key):
    session = await get_http_session()

    async def _set_uploading(kind: str):
        label = {"audio": "🎵 <b>Uploading audio...</b>", "video": "🎬 <b>Uploading video...</b>", "album": "🖼️ <b>Uploading slideshow...</b>"}.get(kind, "<b>Uploading...</b>")
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=label, parse_mode="HTML")
        except Exception as e:
            if "Message is not modified" in str(e):
                return
            raise

    try:
        result = await tiktok_scrape_download(url=url, bot=bot, chat_id=chat_id, status_msg_id=status_msg_id, fmt_key=fmt_key)

        if fmt_key == "mp3":
            path = result.get("path")
            title = result.get("title") or "TikTok Audio"
            if not path or not os.path.exists(path):
                raise RuntimeError("Scraping mp3 source file not found")
            fixed_audio = None
            try:
                fixed_audio = reencode_mp3(path)
                await _set_uploading("audio")
                await bot.send_chat_action(chat_id=chat_id, action="upload_audio")
                bot_name = (await bot.get_me()).first_name or "Bot"
                await bot.send_audio(chat_id=chat_id, audio=fixed_audio, title=title[:64], performer=bot_name, filename=f"{title[:50]}.mp3", reply_to_message_id=reply_to, disable_notification=True)
                await bot.delete_message(chat_id, status_msg_id)
                log.info("TikTok send success | source=scraping type=audio")
                return True
            finally:
                for p in (fixed_audio, path):
                    try:
                        if p and os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass

        if result.get("items") and result.get("source") == "scraping":
            await _set_uploading("album")
            await send_downloaded_media(bot=bot, chat_id=chat_id, reply_to=reply_to, status_msg_id=status_msg_id, path=result, fmt_key="photo")
            await bot.delete_message(chat_id, status_msg_id)
            log.info("TikTok send success | source=scraping type=album")
            return True

        if result.get("path") and result.get("source") == "scraping":
            out_path = result["path"]
            title = result.get("title") or "TikTok Video"
            desc = result.get("desc") or title
            await _set_uploading("video")
            await bot.send_chat_action(chat_id=chat_id, action="upload_video")
            bot_name = (await bot.get_me()).first_name or "Bot"
            caption = _build_safe_caption(title, desc, bot_name)
            with open(out_path, "rb") as fh:
                await bot.send_video(chat_id=chat_id, video=fh, caption=caption, parse_mode="HTML", supports_streaming=False, reply_to_message_id=reply_to, disable_notification=True)
            try:
                os.remove(out_path)
            except Exception:
                pass
            await bot.delete_message(chat_id, status_msg_id)
            log.info("TikTok send success | source=scraping type=video")
            return True

        raise RuntimeError("TikTok scraping result invalid")
    except Exception as e:
        log.exception("TikTok scraping failed, fallback to tikwm | url=%s fmt=%s err=%r", url, fmt_key, e)

    last_data = None
    for attempt in range(3):
        try:
            async with session.post("https://www.tikwm.com/api/", data={"url": url}, timeout=aiohttp.ClientTimeout(total=20)) as r:
                last_data = await r.json()
            if isinstance(last_data, dict) and last_data.get("code") == 0 and last_data.get("data"):
                break
        except Exception as e:
            log.warning("Tikwm request failed | attempt=%s url=%s err=%r", attempt + 1, url, e)
            last_data = None
        await asyncio.sleep(0.6 * (attempt + 1))

    data = last_data or {}
    info = data.get("data") or {}
    log.info("TikTok fallback using tikwm | url=%s fmt=%s", url, fmt_key)

    if fmt_key == "mp3":
        music_url = info.get("music") or (info.get("music_info") or {}).get("play")
        if not music_url:
            raise RuntimeError("Audio not found")
        tmp_audio = f"{TMP_DIR}/{uuid.uuid4().hex}.mp3"
        await _download_with_best_engine(session, music_url, tmp_audio, bot, chat_id, status_msg_id, "Downloading TikTok audio (tikwm)...")
        title = info.get("title") or info.get("desc") or "TikTok Audio"
        bot_name = (await bot.get_me()).first_name or "Bot"
        fixed_audio = reencode_mp3(tmp_audio)
        await _set_uploading("audio")
        await bot.send_chat_action(chat_id=chat_id, action="upload_audio")
        await bot.send_audio(chat_id=chat_id, audio=fixed_audio, title=title[:64], performer=bot_name, filename=f"{title[:50]}.mp3", reply_to_message_id=reply_to, disable_notification=True)
        await bot.delete_message(chat_id, status_msg_id)
        os.remove(tmp_audio)
        os.remove(fixed_audio)
        log.info("TikTok send success | source=tikwm type=audio")
        return True

    images = info.get("images") or []
    if images:
        title = (info.get("title") or info.get("desc") or "TikTok Slideshow").strip()
        items = await _download_album_images(
            session,
            [str(x).strip() for x in images if str(x).strip()],
            title,
            bot,
            chat_id,
            status_msg_id,
            headers={"User-Agent": USER_AGENT, "Referer": "https://www.tiktok.com/"},
        )
        result = {"items": items, "title": title, "source": "tikwm"}
        await _set_uploading("album")
        await send_downloaded_media(bot=bot, chat_id=chat_id, reply_to=reply_to, status_msg_id=status_msg_id, path=result, fmt_key="photo")
        await bot.delete_message(chat_id, status_msg_id)
        log.info("TikTok send success | source=tikwm type=album")
        return True

    video_url = info.get("play") or info.get("wmplay") or info.get("hdplay") or info.get("play_url")
    if video_url:
        title = info.get("title") or info.get("desc") or "TikTok Video"
        desc = info.get("desc") or info.get("title") or ""
        out_path = f"{TMP_DIR}/{uuid.uuid4().hex}_{sanitize_filename(title)}.mp4"
        await _download_with_best_engine(session, video_url, out_path, bot, chat_id, status_msg_id, "Downloading TikTok video (tikwm)...")
        await _set_uploading("video")
        await bot.send_chat_action(chat_id=chat_id, action="upload_video")
        bot_name = (await bot.get_me()).first_name or "Bot"
        caption = _build_safe_caption(title, desc, bot_name)
        with open(out_path, "rb") as fh:
            await bot.send_video(chat_id=chat_id, video=fh, caption=caption, parse_mode="HTML", supports_streaming=False, reply_to_message_id=reply_to, disable_notification=True)
        try:
            os.remove(out_path)
        except Exception:
            pass
        await bot.delete_message(chat_id, status_msg_id)
        log.info("TikTok send success | source=tikwm type=video")
        return True

    raise RuntimeError("TikTok download failed (no video/images from scraping or tikwm)")
    
    