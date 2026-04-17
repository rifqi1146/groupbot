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
    total = 0
    try:
        async with session.head(media_url, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
    except Exception:
        total = 0
    if total <= 0:
        try:
            async with session.get(media_url, headers={"Range": "bytes=0-0"}, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
                content_range = resp.headers.get("Content-Range", "")
                m = re.search(r"/(\d+)$", content_range)
                if m:
                    total = int(m.group(1))
                elif resp.headers.get("Content-Length"):
                    total = int(resp.headers.get("Content-Length", 0) or 0)
        except Exception:
            total = 0
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
        "--summary-interval=1",
        "--download-result=hide",
        "--console-log-level=notice",
        "--show-console-readout=true",
        media_url,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    downloaded_text = None
    total_text = f"{total / (1024 * 1024):.1f} MB" if total > 0 else None
    pct_text = None
    speed_text = None
    eta_text = None
    last = -10.0

    async def _reader():
        nonlocal downloaded_text, total_text, pct_text, speed_text, eta_text
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            raw = line.decode(errors="ignore").strip()
            if not raw:
                continue
            m = re.search(r"([0-9.]+(?:KiB|MiB|GiB|B))/([0-9.]+(?:KiB|MiB|GiB|B))\((\d+)%\)", raw)
            if m:
                downloaded_text = m.group(1)
                total_text = m.group(2)
                pct_text = m.group(3)
            m = re.search(r"\bDL:([0-9.]+(?:KiB|MiB|GiB|B)/s)\b", raw)
            if m:
                speed_text = m.group(1)
            m = re.search(r"\bETA:([0-9hms]+)\b", raw)
            if m:
                eta_text = m.group(1)

    def _build_text():
        lines = ["<b>Downloading YouTube...</b>", ""]
        if downloaded_text and total_text:
            lines.append(f"<code>{html.escape(downloaded_text)}/{html.escape(total_text)} downloaded</code>")
        elif downloaded_text:
            lines.append(f"<code>{html.escape(downloaded_text)} downloaded</code>")
        if pct_text:
            lines.append(f"<code>{html.escape(pct_text)}%</code>")
        if speed_text:
            lines.append(f"<code>Speed: {html.escape(speed_text)}</code>")
        if eta_text:
            lines.append(f"<code>ETA: {html.escape(eta_text)}</code>")
        return "\n".join(lines)

    reader_task = asyncio.create_task(_reader())
    try:
        while proc.returncode is None:
            await asyncio.sleep(0.7)
            if os.path.exists(out_path):
                try:
                    downloaded = os.path.getsize(out_path)
                    if downloaded > 0:
                        downloaded_text = f"{downloaded / (1024 * 1024):.1f} MB"
                        if total > 0:
                            total_text = f"{total / (1024 * 1024):.1f} MB"
                            pct_text = str(min(int(downloaded * 100 / total), 100))
                except Exception:
                    pass
            if not downloaded_text:
                continue
            now = time.time()
            if now - last < 10:
                continue
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=_build_text(), parse_mode="HTML")
            except Exception:
                pass
            last = now
        await reader_task
        if os.path.exists(out_path):
            try:
                downloaded = os.path.getsize(out_path)
                if downloaded > 0:
                    downloaded_text = f"{downloaded / (1024 * 1024):.1f} MB"
                    if total > 0:
                        total_text = f"{total / (1024 * 1024):.1f} MB"
                        pct_text = "100"
            except Exception:
                pass
        if downloaded_text:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=_build_text(), parse_mode="HTML")
            except Exception:
                pass
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="ignore").strip() if stderr else ""
            raise RuntimeError(err or f"aria2c exited with code {proc.returncode}")
    finally:
        if not reader_task.done():
            reader_task.cancel()

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