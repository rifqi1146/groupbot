import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
import os
import asyncio
import shutil
import glob
import html

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(BASE_DIR, "..", "data", "cookies.txt")

async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text(
            "🎵 <b>Perintah Musik</b>\n\n"
            "Gunakan format:\n"
            "<code>/music &lt;judul lagu atau nama artis&gt;</code>",
            parse_mode="HTML"
        )

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'skip_download': True,
            'cookies': COOKIES_PATH,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{query}", download=False)
            if not info or not info.get('entries'):
                raise Exception("Tidak ditemukan lagu atau video yang sesuai dengan pencarian.")

            entries = info['entries'][:5]

        keyboard = []
        text = "<b>🎧 Hasil Pencarian Lagu</b>\n\n"
        for i, entry in enumerate(entries, 1):
            title = entry['title']
            video_id = entry['id']
            uploader = entry.get('uploader', 'Tidak diketahui')
            duration = entry['duration']
            text += f"{i}. <b>{html.escape(title)}</b>\n"
            text += f"   Oleh: {html.escape(uploader)} ({duration//60}:{duration%60:02d})\n\n"

            keyboard.append([
                InlineKeyboardButton(
                    f"▶️ Pilih {i}",
                    callback_data=f"music_download:{video_id}"
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            reply_to_message_id=update.message.message_id,
            parse_mode="HTML"
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ <b>Gagal mencari lagu</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )


async def music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(':', 1)[1]

    await query.edit_message_text(
        "⏳ <b>Sedang mengunduh lagu</b>\n\n"
        "Mohon tunggu sebentar, proses sedang berlangsung 🎶",
        parse_mode="HTML"
    )

    chat_id = query.message.chat_id
    
    try:
        if not shutil.which("ffmpeg"):
            raise Exception("FFmpeg tidak terpasang di sistem.")

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'cookies': COOKIES_PATH,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=True
            )
            if not info:
                raise Exception("Gagal mengunduh lagu.")

            entry = info

        mp3_files = glob.glob('downloads/*.mp3')
        if not mp3_files:
            raise Exception("File audio tidak ditemukan.")

        file_path = max(mp3_files, key=os.path.getmtime)
        
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action="upload_audio"
        )
        
        await context.bot.send_audio(
            chat_id=chat_id,
            audio=open(file_path, 'rb'),
            title=entry['title'],
            performer=entry.get('uploader', 'Tidak diketahui'),
            duration=entry['duration'],
            caption=(
                "🎵 <b>Unduhan Berhasil</b>\n\n"
                f"<b>Judul:</b> {html.escape(entry['title'])}"
            ),
            reply_to_message_id=query.message.reply_to_message.message_id,
            parse_mode="HTML"
        )

        os.remove(file_path)
        await query.message.delete()

    except Exception as e:
        await query.edit_message_text(
            f"❌ <b>Gagal mengunduh lagu</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )