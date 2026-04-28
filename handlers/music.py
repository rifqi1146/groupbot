import asyncio
import os
import shutil
import glob
import html
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from handlers.join import require_join_or_block
from database.user_settings_db import get_user_settings

try:
    from ytSearch import VideosSearch
except Exception:
    VideosSearch = None

def _find_project_root() -> str:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "data").exists() or (parent / "bot.py").exists():
            return str(parent)
    return str(here.parent.parent)

PROJECT_ROOT = _find_project_root()
COOKIES_PATH = os.path.join(PROJECT_ROOT, "data", "cookies.txt")
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")
DENO_BIN = os.getenv("DENO_BIN") or shutil.which("deno") or "/root/.deno/bin/deno"

def _base_ydl_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["web"]}},
    }
    if DENO_BIN and os.path.exists(DENO_BIN):
        opts["js_runtimes"] = {"deno": {"path": DENO_BIN}}
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    return opts

def _video_id_from_url(url: str) -> str | None:
    try:
        p = urlparse(url or "")
        host = (p.hostname or "").lower()
        if host == "youtu.be":
            return p.path.strip("/").split("/")[0] or None
        if "youtube.com" in host:
            q = parse_qs(p.query)
            if q.get("v"):
                return q["v"][0]
            parts = [x for x in p.path.split("/") if x]
            if "shorts" in parts:
                idx = parts.index("shorts")
                if len(parts) > idx + 1:
                    return parts[idx + 1]
    except Exception:
        pass
    return None

def _video_id_from_entry(entry: dict) -> str | None:
    video_id = str(entry.get("id") or entry.get("videoId") or "").strip()
    if video_id:
        return video_id
    return _video_id_from_url(str(entry.get("link") or entry.get("url") or ""))

def _duration_to_seconds(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        parts = [int(x) for x in text.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        return None
    return None

def _format_duration(value) -> str:
    seconds = _duration_to_seconds(value)
    if not seconds:
        return "?:??"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _entry_title(entry: dict) -> str:
    return str(entry.get("title") or "Untitled").strip() or "Untitled"

def _entry_uploader(entry: dict) -> str:
    channel = entry.get("channel")
    if isinstance(channel, dict):
        name = channel.get("name") or channel.get("title")
        if name:
            return str(name)
    return str(entry.get("uploader") or entry.get("channelName") or entry.get("author") or "Unknown")

async def _search_music(search_query: str, limit: int = 5) -> list[dict]:
    if VideosSearch is None:
        raise RuntimeError("ytSearch module not found. Install yt-search-py or py-yt-search.")
    search = VideosSearch(search_query, limit=limit)
    result = await search.next()
    entries = (result or {}).get("result") or []
    out = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        video_id = _video_id_from_entry(item)
        if not video_id:
            continue
        out.append({
            "id": video_id,
            "title": _entry_title(item),
            "uploader": _entry_uploader(item),
            "duration": item.get("duration"),
            "link": item.get("link") or f"https://www.youtube.com/watch?v={video_id}",
        })
    return out[:limit]

def _download_music_sync(video_id: str, output_format: str):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is not installed on the system.")
    output_format = str(output_format or "flac").lower().strip()
    if output_format not in ("flac", "mp3"):
        output_format = "flac"
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    job_dir = tempfile.mkdtemp(prefix="music_", dir=DOWNLOADS_DIR)
    ydl_opts = {
        **_base_ydl_opts(),
        "format": "bestaudio/best",
        "outtmpl": os.path.join(job_dir, "%(title).120s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": output_format,
            "preferredquality": "192",
        }],
    }
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    pattern = "*.mp3" if output_format == "mp3" else "*.flac"
    files = glob.glob(os.path.join(job_dir, pattern))
    if not files:
        raise RuntimeError("Audio file not found.")
    file_path = max(files, key=os.path.getmtime)
    return info or {}, file_path, job_dir

async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    msg = update.effective_message
    query = " ".join(context.args).strip()
    if not query:
        return await msg.reply_text(
            "🎵 <b>Music Command</b>\n\n"
            "Use the format:\n"
            "<code>/music &lt;song title or artist name&gt;</code>",
            parse_mode="HTML",
        )
    status_msg = await msg.reply_text(
        "⏳ <b>Searching for the song...</b>\n\n"
        "Please wait a moment 🎧",
        reply_to_message_id=msg.message_id,
        parse_mode="HTML",
    )
    try:
        entries = await _search_music(query, limit=5)
        if not entries:
            raise RuntimeError("No matching songs or videos were found.")
        keyboard = []
        text = "<b>🎧 Music Search Results</b>\n\n"
        for i, entry in enumerate(entries, 1):
            title = entry["title"]
            video_id = entry["id"]
            uploader = entry["uploader"]
            duration = _format_duration(entry.get("duration"))
            text += f"{i}. <b>{html.escape(title)}</b>\n"
            text += f"   By: {html.escape(uploader)} ({html.escape(duration)})\n\n"
            keyboard.append([InlineKeyboardButton(f"Select {i}", callback_data=f"music_download:{video_id}")])
        await status_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(
            f"<b>Failed to search for the song</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )

async def music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    query = update.callback_query
    await query.answer()
    video_id = query.data.split(":", 1)[1].strip()
    chat_id = query.message.chat_id
    reply_to_id = query.message.reply_to_message.message_id if query.message.reply_to_message else None
    settings = get_user_settings(query.from_user.id)
    output_format = str(settings.get("music_format") or "flac").lower()
    job_dir = None
    try:
        await query.edit_message_text(
            "⏳ <b>Downloading the song</b>\n\n"
            f"Output format: <b>{html.escape(output_format.upper())}</b>",
            parse_mode="HTML",
        )
        entry, file_path, job_dir = await asyncio.to_thread(_download_music_sync, video_id, output_format)
        title = str(entry.get("title") or "Audio")
        performer = str(entry.get("uploader") or entry.get("channel") or "Unknown")
        duration = _duration_to_seconds(entry.get("duration"))
        with open(file_path, "rb") as audio_file:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                filename=os.path.basename(file_path),
                title=title[:64],
                performer=performer[:64],
                duration=duration,
                caption=(
                    "🎵 <b>Download Successful</b>\n\n"
                    f"<b>Title:</b> {html.escape(title)}"
                ),
                reply_to_message_id=reply_to_id,
                parse_mode="HTML",
            )
        await query.message.delete()
    except Exception as e:
        await query.edit_message_text(
            f"<b>Failed to download the song</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )
    finally:
        if job_dir and os.path.isdir(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)