import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
import os
import asyncio
import shutil
import glob

async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Pake: /music <nama lagu atau artis>")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'skip_download': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{query}", download=False)
            if not info or not info.get('entries'):
                raise Exception("Gak nemu lagu/video match query ini!")

            entries = info['entries'][:5]

        keyboard = []
        text = "Pilih lagu nih bro:\n\n"
        for i, entry in enumerate(entries, 1):
            title = entry['title']
            video_id = entry['id']
            uploader = entry.get('uploader', 'Unknown')
            duration = entry['duration']
            text += f"{i}. {title} by {uploader} ({duration//60}:{duration%60:02d})\n"

            keyboard.append([InlineKeyboardButton(f"Pilih {i}: {title[:20]}...", callback_data=f"music_download:{video_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Reply list ke command user
        await update.message.reply_text(text, reply_markup=reply_markup, reply_to_message_id=update.message.message_id)

    except Exception as e:
        await update.message.reply_text(f"Error cari lagu: {str(e)}")

async def music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    video_id = query.data.split(':', 1)[1]

    # Edit message list jadi notif download
    await query.edit_message_text(text="Download lagu yang lu pilih nih... 🎵")

    chat_id = query.message.chat_id
    await context.bot.send_chat_action(chat_id=chat_id, action="upload_audio")

    try:
        if not shutil.which("ffmpeg"):
            raise Exception("FFmpeg gak installed!")

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
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            if not info:
                raise Exception("Gak bisa download lagu ini!")

            entry = info

        mp3_files = glob.glob('downloads/*.mp3')
        if not mp3_files:
            raise Exception("Gak nemu file MP3!")

        file_path = max(mp3_files, key=os.path.getmtime)
        print(f"Found MP3: {file_path}")

        # Kirim audio, reply ke command user asli
        await context.bot.send_audio(
            chat_id=chat_id,
            audio=open(file_path, 'rb'),
            title=entry['title'],
            performer=entry.get('uploader', 'Unknown'),
            duration=entry['duration'],
            caption=f"Lagu yang lu pilih: {entry['title']} 🎵",
            reply_to_message_id=query.message.reply_to_message_id  # Reply ke /music command
        )

        os.remove(file_path)

        # Hapus pesan download setelah sukses
        await query.message.delete()

    except Exception as e:
        await query.edit_message_text(text=f"Error download: {str(e)}")  # Kalau error, gak hapus, tapi edit
