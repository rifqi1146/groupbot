import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes
import os
import asyncio

async def music_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        return await update.message.reply_text("Pake: /music <nama lagu atau artis>")

    # Bikin folder kalau belum ada
    os.makedirs('downloads', exist_ok=True)

    # Typing action
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_audio")

    file_path = None  # Var buat simpen nama file final

    def progress_hook(d):
        nonlocal file_path
        if d['status'] == 'finished':
            file_path = d['filename']  # Dapatkan nama file setelah download & postprocess
            # Kalau postprocess, yt-dlp ubah ext, jadi ambil yang final

    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',  # Template nama
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'progress_hooks': [progress_hook],  # Hook buat tangkep nama file final
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)
            if not info or not info.get('entries'):
                raise Exception("Gak nemu lagu nih. Coba query lain!")

            # Kalau file_path masih None (jarang), fallback ke manual
            if not file_path:
                # Asumsi nama dari title, ubah ext ke mp3
                base_name = ydl.prepare_filename(info['entries'][0])
                file_path = base_name.rsplit('.', 1)[0] + '.mp3'

        # Check file exists
        if not os.path.exists(file_path):
            raise Exception(f"File gak ketemu: {file_path}. Mungkin download gagal.")

        # Kirim audio
        await update.message.reply_audio(
            audio=open(file_path, 'rb'),
            title=info['entries'][0]['title'],
            performer=info['entries'][0].get('uploader', 'Unknown'),
            duration=info['entries'][0]['duration'],
            caption=f"Lagu: {info['entries'][0]['title']} 🎵"
        )

        # Hapus file
        os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"Error nih: {str(e)}. Coba query lain, cek koneksi, atau pastiin ffmpeg installed di VPS lu.")