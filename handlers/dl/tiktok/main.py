import os
import re
import time
import uuid
import html
import shutil
import aiohttp
import asyncio
import aiofiles
from telegram import InputMediaPhoto
from telegram.error import RetryAfter
from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR
from handlers.dl.utils import sanitize_filename, is_invalid_video
from handlers.dl.service import reencode_mp3

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
        if d:
            return len(f"🎬 {t}\n\n{d}\n\n{footer_plain}")
        return len(f"🎬 {t}\n\n{footer_plain}")
    short_title = clean_title
    short_desc = clean_desc
    if short_desc:
        allowed_desc = max_len - len(f"🎬 {short_title}\n\n\n\n{footer_plain}")
        short_desc = _truncate_text(short_desc, allowed_desc)
    if plain_len(short_title, short_desc) > max_len:
        if short_desc:
            allowed_title = max_len - len(f"🎬 \n\n{short_desc}\n\n{footer_plain}")
        else:
            allowed_title = max_len - len(f"🎬 \n\n{footer_plain}")
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
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"

def _format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec <= 0:
        return "0 B/s"
    value = float(bytes_per_sec)
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1024 or unit == "GB/s":
            if unit == "B/s":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB/s"

def _format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
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

async def _probe_total_bytes(session, url: str) -> int:
    total = 0
    try:
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
    except Exception:
        total = 0
    if total > 0:
        return total
    try:
        async with session.get(url, headers={"Range": "bytes=0-0"}, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            content_range = resp.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)$", content_range)
            if m:
                return int(m.group(1))
            if resp.headers.get("Content-Length"):
                return int(resp.headers.get("Content-Length", 0) or 0)
    except Exception:
        pass
    return 0

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

async def _aiohttp_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str):
    async with session.get(media_url, timeout=aiohttp.ClientTimeout(total=600)) as r:
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

async def _download_with_best_engine(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str):
    try:
        await _aria2c_download_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id, title_text)
    except Exception:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        await _aiohttp_download_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id, title_text)

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
    safe_title = sanitize_filename(title)
    uid = uuid.uuid4().hex
    out_path = f"{TMP_DIR}/{uid}_{safe_title}.mp4"
    await _download_with_best_engine(session, video_url, out_path, bot, chat_id, status_msg_id, "Downloading TikTok video...")
    return {"path": out_path, "title": title.strip() or "TikTok Video"}

async def tiktok_fallback_send(bot, chat_id, reply_to, status_msg_id, url, fmt_key):
    session = await get_http_session()
    async def _safe_edit(text: str):
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            if "Message is not modified" in str(e):
                return
            raise
    async def _set_uploading(kind: str):
        label = {"audio": "🎵 <b>Uploading audio...</b>", "video": "🎬 <b>Uploading video...</b>", "album": "🖼️ <b>Uploading slideshow...</b>"}.get(kind, "<b>Uploading...</b>")
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id, text=label, parse_mode="HTML")
        except Exception as e:
            if "Message is not modified" in str(e):
                return
            raise
    last_data = None
    for attempt in range(3):
        try:
            async with session.post("https://www.tikwm.com/api/", data={"url": url}, timeout=aiohttp.ClientTimeout(total=20)) as r:
                last_data = await r.json()
            if isinstance(last_data, dict) and last_data.get("code") == 0 and last_data.get("data"):
                break
        except Exception:
            last_data = None
        await asyncio.sleep(0.6 * (attempt + 1))
    data = last_data or {}
    info = data.get("data") or {}
    if fmt_key == "mp3":
        music_url = info.get("music") or (info.get("music_info") or {}).get("play")
        if not music_url:
            raise RuntimeError("Audio not found")
        tmp_audio = f"{TMP_DIR}/{uuid.uuid4().hex}.mp3"
        await _download_with_best_engine(session, music_url, tmp_audio, bot, chat_id, status_msg_id, "Downloading TikTok audio...")
        title = info.get("title") or info.get("desc") or "TikTok Audio"
        bot_name = (await bot.get_me()).first_name or "Bot"
        fixed_audio = reencode_mp3(tmp_audio)
        await _set_uploading("audio")
        await bot.send_chat_action(chat_id=chat_id, action="upload_audio")
        await bot.send_audio(chat_id=chat_id, audio=fixed_audio, title=title[:64], performer=bot_name, filename=f"{title[:50]}.mp3", reply_to_message_id=reply_to, disable_notification=True)
        await bot.delete_message(chat_id, status_msg_id)
        os.remove(tmp_audio)
        os.remove(fixed_audio)
        return True
    images = info.get("images") or []
    if images:
        CHUNK_SIZE = 10
        ALBUM_COOLDOWN = 5
        chunks = [images[i:i + CHUNK_SIZE] for i in range(0, len(images), CHUNK_SIZE)]
        bot_name = (await bot.get_me()).first_name or "Bot"
        title = (info.get("title") or info.get("desc") or "TikTok Slideshow").strip()
        caption_text = _build_safe_album_caption(title, bot_name)
        await _set_uploading("album")
        for idx, chunk in enumerate(chunks):
            media = []
            for i, img in enumerate(chunk):
                media.append(InputMediaPhoto(media=img, caption=caption_text if idx == 0 and i == 0 else None, parse_mode="HTML" if idx == 0 and i == 0 else None))
            while True:
                try:
                    await bot.send_media_group(chat_id=chat_id, media=media, reply_to_message_id=reply_to if idx == 0 else None)
                    break
                except RetryAfter as e:
                    wait_time = max(int(getattr(e, "retry_after", 0)) + 1, ALBUM_COOLDOWN)
                    await asyncio.sleep(wait_time)
            if idx < len(chunks) - 1:
                await asyncio.sleep(ALBUM_COOLDOWN)
        await bot.delete_message(chat_id, status_msg_id)
        return True
    video_url = info.get("play") or info.get("wmplay") or info.get("hdplay")
    if video_url:
        title = info.get("title") or info.get("desc") or "TikTok Video"
        desc = info.get("desc") or info.get("title") or ""
        safe_title = sanitize_filename(title)
        uid = uuid.uuid4().hex
        out_path = f"{TMP_DIR}/{uid}_{safe_title}.mp4"
        await _download_with_best_engine(session, video_url, out_path, bot, chat_id, status_msg_id, "Downloading TikTok video...")
        await _set_uploading("video")
        await bot.send_chat_action(chat_id=chat_id, action="upload_video")
        bot_name = (await bot.get_me()).first_name or "Bot"
        caption = _build_safe_caption(title, desc, bot_name)
        await bot.send_video(chat_id=chat_id, video=open(out_path, "rb"), caption=caption, parse_mode="HTML", supports_streaming=False, reply_to_message_id=reply_to, disable_notification=True)
        try:
            os.remove(out_path)
        except Exception:
            pass
        await bot.delete_message(chat_id, status_msg_id)
        return True
    raise RuntimeError("TikTok download failed (no video/images from API)")