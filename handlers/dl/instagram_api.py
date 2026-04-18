import os
import re
import time
import uuid
import shutil
import logging
import mimetypes
import asyncio
import aiohttp
import aiofiles
from urllib.parse import urlparse, unquote

from utils.http import get_http_session
from .constants import TMP_DIR
from .utils import sanitize_filename
from .instagram_scrape import igdl_download_for_fallback, send_instagram_fallback_result, cleanup_instagram_fallback_result

INSTAGRAM_API_URL = "https://anabot.my.id/api/download/instagram"
ANABOT_APIKEY = os.getenv("ANABOT_APIKEY", "freeApikey")

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
    for key in ("media", "medias", "items", "carousel", "carousel_media", "result"):
        items = data.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, str):
                add_candidate("photo", item)
                continue
            if not isinstance(item, dict):
                continue
            media_type = str(item.get("type") or item.get("media_type") or item.get("kind") or "").lower()
            media_url = item.get("url") or item.get("download_url") or item.get("media_url") or item.get("video_url") or item.get("image_url") or item.get("src")
            thumb_url = item.get("thumbnail") or item.get("thumb")
            if media_url:
                if item.get("thumbnail") and item.get("url") and not media_type:
                    add_candidate("video", media_url)
                elif "video" in media_type or media_type in ("2", "clip", "reel"):
                    add_candidate("video", media_url)
                else:
                    guessed_ext = _guess_ext_from_url(media_url)
                    if guessed_ext in (".mp4", ".mov", ".m4v", ".webm"):
                        add_candidate("video", media_url)
                    else:
                        add_candidate("photo", media_url)
            if thumb_url:
                add_candidate("photo", thumb_url)
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

async def _probe_total_bytes(session, media_url: str) -> int:
    total = 0
    try:
        async with session.head(media_url, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
    except Exception:
        total = 0
    if total > 0:
        return total
    try:
        async with session.get(media_url, headers={"Range": "bytes=0-0"}, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            content_range = resp.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)$", content_range)
            if m:
                return int(m.group(1))
            if resp.headers.get("Content-Length"):
                return int(resp.headers.get("Content-Length", 0) or 0)
    except Exception:
        pass
    return 0

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

async def _aria2c_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str):
    aria2 = shutil.which("aria2c")
    if not aria2:
        raise RuntimeError("aria2c not found in PATH")
    total = await _probe_total_bytes(session, media_url)
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

async def instagram_api_download(raw_url: str, fmt_key: str, bot, chat_id, status_msg_id):
    session = await get_http_session()
    out_path = None
    await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>Fetching Instagram media...</b>")
    try:
        async with session.get(
            INSTAGRAM_API_URL,
            params={"url": raw_url, "apikey": ANABOT_APIKEY},
            headers={"accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Instagram API request failed: HTTP {resp.status}")
            data = await resp.json(content_type=None)
        if not isinstance(data, dict):
            raise RuntimeError("Instagram API returned invalid response")
        if not bool(data.get("success")):
            raise RuntimeError(data.get("message") or "Instagram API request failed")
        payload = data.get("data") or {}
        candidates = _extract_media_candidates(payload)
        picked = _pick_media_for_format(candidates, fmt_key)
        if not picked:
            if fmt_key == "mp3":
                raise RuntimeError("Instagram image post does not contain audio")
            raise RuntimeError("No downloadable Instagram media found")
        media_type, media_url = picked
        title = _build_title(payload, media_type)
        ext = _guess_ext("", media_type, media_url)
        safe_title = sanitize_filename(title)
        out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{safe_title}{ext}")
        await _aria2c_download_with_progress(
            session=session,
            media_url=media_url,
            out_path=out_path,
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            title_text="Downloading Instagram media...",
        )
        if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
            raise RuntimeError("Downloaded Instagram media is empty")
        return {"path": out_path, "title": title}
    except Exception as e:
        log.warning("Instagram Anabot API download failed, falling back to Indown | url=%s fmt=%s err=%r", raw_url, fmt_key, e)
        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception as cleanup_err:
                log.warning("Failed to remove partial Instagram API file | path=%s err=%s", out_path, cleanup_err)
    await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>Anabot failed, fallback to Indown...</b>")
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