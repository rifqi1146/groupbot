import os
import re
import time
import uuid
import shutil
import asyncio
import aiohttp
import aiofiles
from urllib.parse import urlparse, unquote
from utils.http import get_http_session
from .constants import TMP_DIR
from .utils import sanitize_filename, progress_bar

SONZAI_YOUTUBE_API = "https://api.sonzaix.indevs.in/youtube/video"

def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
        return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    except Exception:
        text = (url or "").lower()
        return "youtu.be" in text or "youtube.com" in text

def _resolution_value(label: str) -> int:
    m = re.search(r"(\d+)", str(label or ""))
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0

def _normalize_title(filename: str) -> str:
    name = os.path.splitext((filename or "").strip())[0]
    name = re.sub(r"\s*\(\d+p.*?\)\s*$", "", name, flags=re.I)
    return name.strip() or "YouTube Video"

def _pick_best_resolution(links: dict, preferred: str | None = None) -> tuple[str, str] | None:
    if not isinstance(links, dict) or not links:
        return None
    clean = []
    for key, value in links.items():
        if not value:
            continue
        label = str(key).strip()
        url = str(value).strip()
        if not url:
            continue
        clean.append((label, url))
    if not clean:
        return None
    if preferred:
        preferred = str(preferred).strip()
        for label, url in clean:
            if label == preferred:
                return label, url
    clean.sort(key=lambda item: _resolution_value(item[0]), reverse=True)
    return clean[0]

def _guess_ext(filename: str, media_url: str) -> str:
    ext = os.path.splitext((filename or "").strip())[1].lower()
    if ext:
        return ext
    try:
        path = unquote(urlparse(media_url).path or "")
        ext = os.path.splitext(path)[1].lower()
        if ext:
            return ext
    except Exception:
        pass
    return ".mp4"

async def _fetch_sonzai_payload(raw_url: str) -> dict:
    session = await get_http_session()
    async with session.get(SONZAI_YOUTUBE_API, params={"url": raw_url}, timeout=aiohttp.ClientTimeout(total=25)) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Sonzai API HTTP {resp.status}")
        data = await resp.json(content_type=None)
    if not isinstance(data, dict):
        raise RuntimeError("Invalid Sonzai API response")
    links = data.get("download_link")
    if not isinstance(links, dict) or not links:
        raise RuntimeError("No downloadable links returned by Sonzai API")
    return data

async def sonzai_get_resolutions(raw_url: str) -> list[dict]:
    data = await _fetch_sonzai_payload(raw_url)
    links = data.get("download_link") or {}
    out = []
    for label, media_url in links.items():
        if not media_url:
            continue
        height = _resolution_value(label)
        if not height:
            continue
        out.append({
            "height": height,
            "format_id": str(label).strip(),
            "ext": "mp4",
            "has_audio": True,
            "filesize": 0,
            "total_size": 0,
        })
    out.sort(key=lambda x: int(x.get("height") or 0), reverse=True)
    return out

async def _aria2c_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id):
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
    last_size = 0
    last_size_ts = time.time()
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
        if now - last_edit < 10:
            continue
        elapsed = max(now - last_size_ts, 0.001)
        speed_bps = max(downloaded - last_size, 0) / elapsed
        downloaded_text = f"{downloaded / (1024 * 1024):.1f} MB"
        speed_text = f"{speed_bps / (1024 * 1024):.1f} MB/s"
        text = (
            "<b>Downloading YouTube media...</b>\n\n"
            f"<code>{downloaded_text} downloaded</code>\n"
            f"<code>Speed: {speed_text}</code>"
        )
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=text, parse_mode="HTML")
        except Exception:
            pass
        last_edit = now
        last_size = downloaded
        last_size_ts = now
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="ignore").strip() if stderr else ""
        raise RuntimeError(err or f"aria2c exited with code {proc.returncode}")

async def _aiohttp_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id):
    async with session.get(media_url, timeout=aiohttp.ClientTimeout(total=600)) as media_resp:
        if media_resp.status >= 400:
            raise RuntimeError(f"Failed to download Sonzai media: HTTP {media_resp.status}")
        total = int(media_resp.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        last = 0.0
        async with aiofiles.open(out_path, "wb") as f:
            async for chunk in media_resp.content.iter_chunked(64 * 1024):
                await f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last >= 0.7:
                    try:
                        if total > 0:
                            pct = downloaded / total * 100
                            text = f"<b>Downloading YouTube media...</b>\n\n<code>{progress_bar(pct)}</code>"
                        else:
                            mb = downloaded / (1024 * 1024)
                            text = f"<b>Downloading YouTube media...</b>\n\n<code>{mb:.1f} MB</code>"
                        await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=text, parse_mode="HTML")
                    except Exception:
                        pass
                    last = now

async def sonzai_youtube_download(raw_url: str, fmt_key: str, bot, chat_id, status_msg_id, format_id: str | None = None):
    session = await get_http_session()
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text="<b>Fetching YouTube media...</b>", parse_mode="HTML")
    except Exception:
        pass
    data = await _fetch_sonzai_payload(raw_url)
    filename = str(data.get("filename") or "").strip()
    links = data.get("download_link") or {}
    picked = _pick_best_resolution(links, preferred=format_id if fmt_key == "video" else None)
    if not picked:
        raise RuntimeError("No suitable Sonzai download link found")
    picked_label, media_url = picked
    title = _normalize_title(filename or f"YouTube Video {picked_label}")
    ext = _guess_ext(filename, media_url)
    safe_title = sanitize_filename(title)
    out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{safe_title}{ext}")
    try:
        await _aria2c_download_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id)
    except Exception:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        await _aiohttp_download_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id)
    return {"path": out_path, "title": title}