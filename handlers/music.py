import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
import os
import asyncio

async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Pake: /music <nama lagu atau artis>")

    # Typing action biar user tau lagi proses
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_audio")

    try:
        # Opsi yt-dlp: search YouTube, ambil audio best, format mp3
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',  # Simpen di folder downloads/
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',  # Bitrate oke, file kecil
            }],
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,  # Ambil satu lagu doang
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Search & download
            info = ydl.extract_info(f"ytsearch:{query}", download=True)
            file_path = ydl.prepare_filename(info)
            file_path = file_path.rsplit('.', 1)[0] + '.mp3'  # Ubah ext ke mp3

        # Kirim audio ke user
        await update.message.reply_audio(
            audio=open(file_path, 'rb'),
            title=info['title'],
            performer=info.get('uploader', 'Unknown'),
            duration=info['duration'],
            caption=f"Lagu: {info['title']} 🎵"
        )

        # Hapus file setelah kirim (hemat storage)
        os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"Error nih: {str(e)}. Coba query lain atau cek koneksi.")

# Register di commands.py
# Tambah: ("music", music_cmd, False)