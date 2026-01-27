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
        nonlocal file_path
        if d['status'] == 'finished':
            file_path = d.get('filename')  # Tangkep nama final
            # Log detail
            print(f"Download finished: {file_path}")  # Ini bakal muncul di console/log lu

    try:
        # Check ffmpeg exists (biar tau kalau ini penyebab)
        if not shutil.which("ffmpeg"):
            raise Exception("FFmpeg gak installed! Install dulu: sudo apt install ffmpeg -y")

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': False,  # Matikan quiet biar liat log detail di console
            'verbose': True,  # Tambah verbose buat debug full (liat di terminal pas run)
            'noplaylist': True,
            'progress_hooks': [progress_hook],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch:{query}", download=True)
                if not info or not info.get('entries'):
                    raise yt_dlp.DownloadError("Gak nemu lagu/video match query ini!")
            except yt_dlp.DownloadError as de:
                raise Exception(f"yt-dlp gagal download: {str(de)}. Mungkin query salah atau video restricted.")

            if not file_path:
                base_name = ydl.prepare_filename(info['entries'][0])
                file_path = base_name.rsplit('.', 1)[0] + '.mp3'

        if not os.path.exists(file_path):
            raise Exception(f"File gak ketemu setelah download: {file_path}. Cek log console buat detail.")

        await update.message.reply_audio(
            audio=open(file_path, 'rb'),
            title=info['entries'][0]['title'],
            performer=info['entries'][0].get('uploader', 'Unknown'),
            duration=info['entries'][0]['duration'],
            caption=f"Lagu: {info['entries'][0]['title']} 🎵"
        )

        os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"Error detail: {str(e)}\n\nCoba: Install ffmpeg, update yt-dlp, atau query lain yang valid (misal 'despacito'). Liat console log VPS lu buat detail yt-dlp.")