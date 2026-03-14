import asyncio
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import os
import shutil
import glob
import html
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(BASE_DIR, "..", "data", "cookies.txt")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "..", "downloads")


def _base_ydl_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "js_runtimes": {"deno": {"path": "/root/.deno/bin/deno"}},
        "extractor_args": {"youtube": {"player_client": ["web"]}},
    }
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    return opts


def _search_music_sync(search_query: str):
    ydl_opts = {
        **_base_ydl_opts(),
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch5:{search_query}", download=False)

    entries = (info or {}).get("entries") or []
    return entries[:5]


def _download_music_sync(video_id: str):
    if not shutil.which("ffmpeg"):
        raise Exception("FFmpeg is not installed on the system.")

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    job_dir = tempfile.mkdtemp(prefix="music_", dir=DOWNLOADS_DIR)

    ydl_opts = {
        **_base_ydl_opts(),
        "format": "bestaudio/best",
        "outtmpl": os.path.join(job_dir, "%(title)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "flac",
            "preferredquality": "192",
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=True
        )

    flac_files = glob.glob(os.path.join(job_dir, "*.flac"))
    if not flac_files:
        raise Exception("Audio file not found.")

    file_path = max(flac_files, key=os.path.getmtime)
    return info, file_path, job_dir


async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        return await update.message.reply_text(
            "🎵 <b>Music Command</b>\n\n"
            "Use the format:\n"
            "<code>/music &lt;song title or artist name&gt;</code>",
            parse_mode="HTML"
        )

    status_msg = await update.message.reply_text(
        "⏳ <b>Searching for the song...</b>\n\n"
        "Please wait a moment 🎧",
        reply_to_message_id=update.message.message_id,
        parse_mode="HTML",
    )

    try:
        entries = await asyncio.to_thread(_search_music_sync, query)

        if not entries:
            raise Exception("No matching songs or videos were found.")

        keyboard = []
        text = "<b>🎧 Music Search Results</b>\n\n"

        for i, entry in enumerate(entries, 1):
            title = entry.get("title") or "Untitled"
            video_id = entry.get("id")
            uploader = entry.get("uploader") or "Unknown"
            duration = entry.get("duration") or 0
            text += f"{i}. <b>{html.escape(title)}</b>\n"
            text += f"   By: {html.escape(uploader)} ({duration//60}:{duration%60:02d})\n\n"
            
            if video_id:
                keyboard.append([
                    InlineKeyboardButton(
                        f"Select {i}",
                        callback_data=f"music_download:{video_id}"
                    )
                ])
                
        if not keyboard:
            raise Exception("Search results found, but all video IDs are missing.")

        await status_msg.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    except Exception as e:
        await status_msg.edit_text(
            f"<b>Failed to search for the song</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )


async def music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(":", 1)[1]
    chat_id = query.message.chat_id
    reply_to_id = None
    job_dir = None
    file_path = None
    entry = None

    if query.message.reply_to_message:
        reply_to_id = query.message.reply_to_message.message_id

    await query.edit_message_text(
        "⏳ <b>Downloading the song</b>\n\n"
        "Please wait, the process is ongoing 🎶",
        parse_mode="HTML"
    )

    try:
        entry, file_path, job_dir = await asyncio.to_thread(_download_music_sync, video_id)

        with open(file_path, "rb") as audio_file:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                filename=os.path.basename(file_path),
                title=entry.get("title") or "Audio",
                performer=entry.get("uploader", "Unknown"),
                duration=entry.get("duration"),
                caption=(
                    "🎵 <b>Download Successful</b>\n\n"
                    f"<b>Title:</b> {html.escape(entry.get('title') or 'Audio')}"
                ),
                reply_to_message_id=reply_to_id,
                parse_mode="HTML"
            )

        await query.message.delete()

    except Exception as e:
        await query.edit_message_text(
            f"<b>Failed to download the song</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )

    finally:
        if job_dir and os.path.isdir(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)