import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes
import os
import asyncio
import shutil
import glob  # Buat scan file

async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Pake: /music <nama lagu atau artis>")

    os.makedirs('downloads', exist_ok=True)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_audio")

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
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            # Gak pake hook lagi, biar simple
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)
            if not info or not info.get('entries'):
                raise Exception("Gak nemu lagu/video match query ini!")

            entry = info['entries'][0]

        # STRATEGI BARU: Scan folder downloads/ cari file MP3 terbaru
        # Cari semua .mp3 di folder
        mp3_files