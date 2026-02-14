import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import os
import shutil
import glob
import html

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(BASE_DIR, "..", "data", "cookies.txt")

async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
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
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "cookiefile": COOKIES_PATH,
            "js_runtimes": {"deno": {"path": "/root/.deno/bin/deno"}},
            "extractor_args": {"youtube": {"player_client": ["web", "tv", "android"]}},
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{query}", download=False)
            if not info or not info.get("entries"):
                raise Exception("No matching songs or videos were found.")
            entries = info["entries"][:5]

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
                        f"▶️ Select {i}",
                        callback_data=f"music_download:{video_id}"
                    )
                ])

        if not keyboard:
            raise Exception("Search results found, but all video IDs are missing.")

        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text(
            text,
            reply_markup=reply_markup,
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

    await query.edit_message_text(
        "⏳ <b>Downloading the song</b>\n\n"
        "Please wait, the process is ongoing 🎶",
        parse_mode="HTML"
    )

    chat_id = query.message.chat_id

    try:
        if not shutil.which("ffmpeg"):
            raise Exception("FFmpeg is not installed on the system.")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": "downloads/%(title)s.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "cookiefile": COOKIES_PATH,
            "js_runtimes": {"deno": {"path": "/root/.deno/bin/deno"}},
            "extractor_args": {"youtube": {"player_client": ["web", "tv", "android"]}},
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=True
            )
            if not info:
                raise Exception("Failed to download the song.")
            entry = info

        mp3_files = glob.glob("downloads/*.mp3")
        if not mp3_files:
            raise Exception("Audio file not found.")

        file_path = max(mp3_files, key=os.path.getmtime)

        await context.bot.send_audio(
            chat_id=chat_id,
            audio=open(file_path, "rb"),
            title=entry.get("title") or "Audio",
            performer=entry.get("uploader", "Unknown"),
            duration=entry.get("duration"),
            caption=(
                "🎵 <b>Download Successful</b>\n\n"
                f"<b>Title:</b> {html.escape(entry.get('title') or 'Audio')}"
            ),
            reply_to_message_id=query.message.reply_to_message.message_id,
            parse_mode="HTML"
        )

        os.remove(file_path)
        await query.message.delete()

    except Exception as e:
        await query.edit_message_text(
            f"❌ <b>Failed to download the song</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )