import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes
import os
import asyncio
import shutil  # Buat check ffmpeg

async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Pake: /music <nama lagu atau artis>")

    os.makedirs('downloads', exist_ok=True)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_audio")

    file_path = None

    def progress_hook(d):
        if d['status'] == 'finished':
            print(f"Download awal finished: {d.get('filename')}")  # Log .webm

    def postprocess_hook(d):
        nonlocal file_path
        if d['status'] == 'finished':
            file_path = d['filename']  # Ini setelah postprocess, .mp3
            print(f"Postprocess finished: {file_path}")  # Log .mp3 final

    try:
        if not shutil.which("ffmpeg"):
            raise Exception("FFmpeg gak installed! Install: sudo apt install ffmpeg -y")

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,  # Matikan buat produksi, nyalain False kalau debug
            'no_warnings': True,
            'noplaylist': True,
            'progress_hooks': [progress_hook],
            'postprocessor_hooks': [postprocess_hook],  # Kunci fix: Tangkep setelah convert
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)
            if not info or not info.get('entries'):
                raise Exception("Gak nemu lagu/video match query ini!")

            entry = info['entries'][0]

            if not file_path:
                # Fallback lebih aman: Pakai _filename dari entry kalau ada, atau construct manual
                if '_filename' in entry:
                    file_path = entry['_filename']
                else:
                    base_name = ydl.prepare_filename(entry)
                    file_path = base_name.rsplit('.', 1)[0] + '.mp3'

            print(f"Final file_path yang dicoba: {file_path}")  # Log buat debug

        if not os.path.exists(file_path):
            raise Exception(f"File gak ketemu: {file_path}. Cek apakah postprocess gagal.")

        await update.message.reply_audio(
            audio=open(file_path, 'rb'),
            title=entry['title'],
            performer=entry.get('uploader', 'Unknown'),
            duration=entry['duration'],
            caption=f"Lagu: {entry['title']} 🎵"
        )

        os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"Error detail: {str(e)}\n\nCek console log buat detail yt-dlp. Kalau masih gagal, paste full log baru.")