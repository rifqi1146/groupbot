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
from urllib.parse import urlparse, parse_qs
from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR
from handlers.dl.utils import sanitize_filename
from handlers.dl.ytdlp import ytdlp_download

log = logging.getLogger(__name__)

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

SHARE_RE = re.compile(r"https?://(?:(?:www|m)\.)?facebook\.com/share/(?:r|v|p)/([a-zA-Z0-9]+)", re.I)
CONTENT_RE = re.compile(
    r"https?://(?:(?:www|m|mbasic)\.)?facebook\.com/"
    r"(?:watch/?\?(?:[^&]*&)*v=|(?:reel|videos?|posts?)/|[^/]+/(?:videos|posts|reels?)/)"
    r"([a-zA-Z0-9]+)",
    re.I,
)

HD_URL_PATTERN = re.compile(
    r'"progressive_url"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*,\s*"failure_reason"\s*:\s*[^,]+\s*,\s*"metadata"\s*:\s*\{\s*"quality"\s*:\s*"HD"\s*\}',
    re.S,
)
SD_URL_PATTERN = re.compile(
    r'"progressive_url"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*,\s*"failure_reason"\s*:\s*[^,]+\s*,\s*"metadata"\s*:\s*\{\s*"quality"\s*:\s*"SD"\s*\}',
    re.S,
)
TITLE_PATTERN = re.compile(
    r'"title"\s*:\s*\{\s*"text"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
    re.S,
)

DEBUG_FACEBOOK = True

def is_facebook_url(url: str) -> bool:
    text = (url or "").strip()
    if not text:
        return False
    host = (urlparse(text).hostname or "").lower()
    if "facebook.com" in host or host in {"fb.watch", "fb.com", "www.fb.com"}:
        return True
    return "facebook.com/" in text.lower() or "fb.watch/" in text.lower()

def _dbg(msg: str, *args):
    if DEBUG_FACEBOOK:
        log.warning("FBDBG | " + msg, *args)

def _clip(text: str, limit: int = 400) -> str:
    text = (text or "").replace("\n", "\\n").replace("\r", "\\r")
    if len(text) <= limit:
        return text
    return text[:limit] + "...<cut>"

def _write_debug_file(prefix: str, content: bytes | str) -> str:
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        path = os.path.join(TMP_DIR, f"{prefix}_{uuid.uuid4().hex}.txt")
        mode = "wb" if isinstance(content, (bytes, bytearray)) else "w"
        with open(path, mode, encoding=None if "b" in mode else "utf-8") as f:
            f.write(content)
        _dbg("debug file written | path=%s", path)
        return path
    except Exception as e:
        _dbg("failed writing debug file | err=%r", e)
        return ""

def _extract_content_id(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    m = CONTENT_RE.search(text)
    if m:
        value = (m.group(1) or "").strip()
        _dbg("content id from regex | url=%s id=%s", text, value)
        return value
    parsed = urlparse(text)
    if "watch" in parsed.path:
        qs = parse_qs(parsed.query)
        val = (qs.get("v") or [""])[0].strip()
        if val:
            _dbg("content id from watch query | url=%s id=%s", text, val)
            return val
    _dbg("content id not found | url=%s", text)
    return ""

def _normalize_content_url(content_url: str, content_id: str) -> str:
    original = (content_url or "").strip()
    content_url = original.replace("m.facebook.com", "www.facebook.com", 1)
    content_url = content_url.replace("mbasic.facebook.com", "www.facebook.com", 1)
    if "/watch" in content_url and content_id:
        content_url = f"https://www.facebook.com/reel/{content_id}"
    _dbg("normalize content url | before=%s after=%s content_id=%s", original, content_url, content_id)
    return content_url

async def _follow_share_redirect(url: str) -> str:
    session = await get_http_session()
    _dbg("follow share redirect start | url=%s", url)
    async with session.get(url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as resp:
        final_url = str(resp.url)
        _dbg("follow share redirect done | status=%s final=%s", resp.status, final_url)
        return final_url

def _unescape_unicode(text: str) -> str:
    if not text:
        return ""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if i + 5 < n and text[i] == "\\" and text[i + 1] == "u":
            hex_part = text[i + 2:i + 6]
            try:
                out.append(chr(int(hex_part, 16)))
                i += 6
                continue
            except Exception:
                pass
        out.append(text[i])
        i += 1
    return "".join(out)

def _unescape_facebook_url(text: str) -> str:
    text = (text or "").replace(r"\/", "/")
    return _unescape_unicode(text)

def _find_video_section(body: bytes, video_id: str) -> bytes | None:
    if not video_id:
        _dbg("find section skipped | no video_id")
        return None
    anchor = f"dash_mpd_debug.mpd?v={video_id}".encode()
    start = body.find(anchor)
    if start == -1:
        _dbg("anchor not found | video_id=%s anchor=%s", video_id, anchor.decode(errors="ignore"))
        return None
    remaining = body[start:]
    end_marker = f'"id":"{video_id}"'.encode()
    end_idx = remaining.find(end_marker)
    if end_idx > 0:
        section = remaining[: end_idx + len(end_marker)]
        _dbg("section found with end marker | video_id=%s start=%s len=%s", video_id, start, len(section))
        return section
    max_len = min(20000, len(remaining))
    section = remaining[:max_len]
    _dbg("section fallback window | video_id=%s start=%s len=%s", video_id, start, len(section))
    return section

def _parse_video_from_body(body: bytes, video_id: str) -> dict:
    data = {
        "hd_url": "",
        "sd_url": "",
        "title": "",
        "width": 0,
        "height": 0,
    }

    _dbg("parse body start | video_id=%s body_len=%s", video_id, len(body))

    section = _find_video_section(body, video_id)
    used_full_body = False
    if section is None:
        section = body
        used_full_body = True
        _dbg("section nil, fallback to full body | video_id=%s", video_id)

    section_text = section.decode("utf-8", errors="ignore")
    body_text = body.decode("utf-8", errors="ignore")

    hd_match = HD_URL_PATTERN.search(section_text)
    if hd_match:
        data["hd_url"] = _unescape_facebook_url(hd_match.group(1))
        _dbg("hd match found | url=%s", _clip(data["hd_url"], 200))
    else:
        _dbg("hd match not found | used_full_body=%s", used_full_body)

    sd_match = SD_URL_PATTERN.search(section_text)
    if sd_match:
        data["sd_url"] = _unescape_facebook_url(sd_match.group(1))
        _dbg("sd match found | url=%s", _clip(data["sd_url"], 200))
    else:
        _dbg("sd match not found | used_full_body=%s", used_full_body)

    title_match = TITLE_PATTERN.search(body_text)
    if title_match:
        data["title"] = _unescape_unicode(title_match.group(1))
        _dbg("title match found | title=%s", _clip(data["title"], 200))
    else:
        _dbg("title match not found")

    if not data["hd_url"] and not data["sd_url"]:
        preview = _clip(section_text, 1500)
        _dbg("no video urls found | section_preview=%s", preview)
        _write_debug_file("facebook_body", body)
        _write_debug_file("facebook_section", section)
        raise RuntimeError("no video URLs found in page")

    return data

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
    out_dir, out_name = os.path.dirname(out_path) or ".", os.path.basename(out_path)
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
        if now - last_edit < 3 and last_edit >= 0:
            continue
        await _safe_edit_progress(bot, chat_id, status_msg_id, title_text, downloaded, total, speed_bps, eta_seconds)
        last_edit = now
        last_sample_size = downloaded
        last_sample_ts = now

    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="ignore").strip() if stderr else ""
        _dbg("aria2c failed | code=%s err=%s", proc.returncode, _clip(err, 500))
        raise RuntimeError(err or f"aria2c exited with code {proc.returncode}")

    _dbg("aria2c success | out=%s", out_path)

async def _aiohttp_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, headers: dict | None = None):
    _dbg("aiohttp download start | out=%s url=%s", out_path, _clip(media_url, 200))
    async with session.get(media_url, headers=headers, timeout=aiohttp.ClientTimeout(total=600), allow_redirects=True) as r:
        _dbg("aiohttp download response | status=%s final=%s", r.status, str(r.url))
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
                if now - last_edit < 3 and last_edit >= 0:
                    continue
                await _safe_edit_progress(bot, chat_id, status_msg_id, title_text, downloaded, total, speed_bps, eta_seconds)
                last_edit = now
                last_sample_size = downloaded
                last_sample_ts = now
    _dbg("aiohttp download success | out=%s", out_path)

async def _download_with_best_engine(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, headers: dict | None = None):
    try:
        await _aria2c_download_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id, title_text, headers=headers)
    except Exception as e:
        log.warning("Facebook aria2c failed, fallback aiohttp | err=%r", e)
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        await _aiohttp_download_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id, title_text, headers=headers)

async def _get_video_data(content_url: str, content_id: str) -> dict:
    content_url = _normalize_content_url(content_url, content_id)
    session = await get_http_session()
    _dbg("fetch video data start | url=%s content_id=%s", content_url, content_id)
    async with session.get(
        content_url,
        headers=WEB_HEADERS,
        timeout=aiohttp.ClientTimeout(total=25),
        allow_redirects=True,
    ) as resp:
        final_url = str(resp.url)
        status = resp.status
        body = await resp.read()
        _dbg("fetch video data response | status=%s final=%s body_len=%s", status, final_url, len(body))
        if status != 200:
            _write_debug_file("facebook_http_error", body)
            raise RuntimeError(f"failed to get page: HTTP {status}")
    return _parse_video_from_body(body, content_id)

async def facebook_scrape_download(raw_url: str, fmt_key: str, bot, chat_id, status_msg_id, format_id: str | None = None, has_audio: bool = False):
    await _safe_edit_status(bot, chat_id, status_msg_id, "<b>Scraping Facebook video...</b>")
    _dbg("facebook scrape start | raw_url=%s fmt_key=%s", raw_url, fmt_key)

    content_url = (raw_url or "").strip()
    is_share = bool(SHARE_RE.search(content_url))
    _dbg("share url detected=%s | url=%s", is_share, content_url)

    if is_share:
        content_url = await _follow_share_redirect(content_url)

    content_id = _extract_content_id(content_url)
    if not content_id:
        _dbg("scrape failed before fetch | reason=no content id | content_url=%s", content_url)
        raise RuntimeError("failed to extract facebook content id")

    video_data = await _get_video_data(content_url, content_id)
    _dbg(
        "video data parsed | title=%s hd=%s sd=%s",
        _clip(video_data.get("title", ""), 150),
        bool(video_data.get("hd_url")),
        bool(video_data.get("sd_url")),
    )

    video_url = video_data.get("hd_url") or video_data.get("sd_url")
    if not video_url:
        _dbg("video url empty after parse | content_url=%s content_id=%s", content_url, content_id)
        raise RuntimeError("no video formats found")

    title = (video_data.get("title") or "Facebook Video").strip() or "Facebook Video"
    out_path = f"{TMP_DIR}/{uuid.uuid4().hex}_{sanitize_filename(title)}.mp4"

    session = await get_http_session()
    headers = {
        "User-Agent": WEB_HEADERS["User-Agent"],
        "Referer": _normalize_content_url(content_url, content_id),
    }

    _dbg("download chosen url | url=%s out=%s", _clip(video_url, 200), out_path)

    await _download_with_best_engine(
        session,
        video_url,
        out_path,
        bot,
        chat_id,
        status_msg_id,
        "Downloading Facebook video...",
        headers=headers,
    )

    return {
        "path": out_path,
        "title": title,
        "source": "facebook_scraping",
        "desc": title,
    }

async def facebook_download(raw_url: str, fmt_key: str, bot, chat_id, status_msg_id, format_id: str | None = None, has_audio: bool = False):
    try:
        return await facebook_scrape_download(
            raw_url=raw_url,
            fmt_key=fmt_key,
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            format_id=format_id,
            has_audio=has_audio,
        )
    except Exception as e:
        log.exception("Facebook scraping failed, fallback to yt-dlp | url=%s err=%r", raw_url, e)
        await _safe_edit_status(bot, chat_id, status_msg_id, "<b>Facebook scraping failed</b>\n\n<i>Fallback to yt-dlp...</i>")
        return await ytdlp_download(
            raw_url,
            fmt_key,
            bot,
            chat_id,
            status_msg_id,
            format_id=format_id,
            has_audio=has_audio,
        )