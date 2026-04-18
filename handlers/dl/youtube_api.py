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

SONZAI_YOUTUBE_API = "https://rynekoo-api.hf.space/downloader/youtube/v2"

DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

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

def _pick_best_media(medias: list[dict], preferred: str | None = None) -> dict | None:
    if not isinstance(medias, list) or not medias:
        return None
    cleaned = []
    for item in medias:
        if not isinstance(item, dict):
            continue
        media_url = str(item.get("url") or "").strip()
        if not media_url:
            continue
        label = str(item.get("label") or item.get("quality") or "").strip()
        ext = str(item.get("ext") or item.get("extension") or "").strip().lower()
        height = int(item.get("height") or _resolution_value(label) or 0)
        has_audio = bool(item.get("is_audio"))
        media_type = str(item.get("type") or "").strip().lower()
        cleaned.append({
            "raw": item,
            "url": media_url,
            "label": label,
            "ext": ext or "mp4",
            "height": height,
            "has_audio": has_audio,
            "type": media_type,
        })
    if not cleaned:
        return None
    if preferred:
        preferred = str(preferred).strip().lower()
        for item in cleaned:
            if str(item["height"]) == preferred.replace("p", ""):
                return item["raw"]
            if item["label"].lower() == preferred:
                return item["raw"]
    cleaned.sort(key=lambda x: (0 if x["has_audio"] else 1, -(x["height"] or 0), 0 if x["ext"] == "mp4" else 1))
    return cleaned[0]["raw"]

async def _fetch_sonzai_payload(raw_url: str) -> dict:
    session = await get_http_session()
    async with session.get(SONZAI_YOUTUBE_API, params={"url": raw_url}, headers=DOWNLOAD_HEADERS, timeout=aiohttp.ClientTimeout(total=25)) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"YouTube API HTTP {resp.status}")
        data = await resp.json(content_type=None)
    if not isinstance(data, dict):
        raise RuntimeError("Invalid YouTube API response")
    if not bool(data.get("success")):
        raise RuntimeError(data.get("message") or "YouTube API request failed")
    result = data.get("result") or {}
    medias = result.get("medias")
    if not isinstance(medias, list) or not medias:
        raise RuntimeError("No downloadable links returned by YouTube API")
    return result

async def sonzai_get_resolutions(raw_url: str) -> list[dict]:
    data = await _fetch_sonzai_payload(raw_url)
    medias = data.get("medias") or []
    grouped = {}
    for item in medias:
        if not isinstance(item, dict):
            continue
        media_url = str(item.get("url") or "").strip()
        if not media_url:
            continue
        media_type = str(item.get("type") or "").strip().lower()
        if media_type != "video":
            continue
        label = str(item.get("label") or item.get("quality") or "").strip()
        height = int(item.get("height") or _resolution_value(label) or 0)
        if not height:
            continue
        current = grouped.get(height)
        candidate = {
            "height": height,
            "format_id": str(height),
            "ext": str(item.get("ext") or item.get("extension") or "mp4"),
            "has_audio": bool(item.get("is_audio")),
            "filesize": int(item.get("clen") or 0) if str(item.get("clen") or "").isdigit() else 0,
            "total_size": int(item.get("clen") or 0) if str(item.get("clen") or "").isdigit() else 0,
            "_raw": item,
        }
        if not current:
            grouped[height] = candidate
            continue
        if candidate["has_audio"] and not current["has_audio"]:
            grouped[height] = candidate
            continue
        if candidate["ext"] == "mp4" and current["ext"] != "mp4":
            grouped[height] = candidate
    out = []
    for height in sorted(grouped.keys(), reverse=True):
        item = grouped[height]
        item.pop("_raw", None)
        out.append(item)
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
        "--header", f"User-Agent: {DOWNLOAD_HEADERS['User-Agent']}",
        "--header", f"Accept: {DOWNLOAD_HEADERS['Accept']}",
        "--header", f"Accept-Language: {DOWNLOAD_HEADERS['Accept-Language']}",
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
    async with session.get(media_url, headers=DOWNLOAD_HEADERS, timeout=aiohttp.ClientTimeout(total=600)) as media_resp:
        if media_resp.status >= 400:
            raise RuntimeError(f"Failed to download YouTube media: HTTP {media_resp.status}")
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
    medias = data.get("medias") or []
    picked = _pick_best_media(medias, preferred=format_id if fmt_key == "video" else None)
    if not picked:
        raise RuntimeError("No suitable YouTube download link found")
    media_url = str(picked.get("url") or "").strip()
    if not media_url:
        raise RuntimeError("YouTube media URL is empty")
    label = str(picked.get("label") or picked.get("quality") or "").strip()
    title = _normalize_title(str(data.get("title") or "").strip() or f"YouTube Video {label}")
    ext = _guess_ext(str(data.get("title") or "").strip(), media_url)
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