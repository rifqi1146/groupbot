import os
import re
import json
import time
import html
import uuid
import shutil
import asyncio
import subprocess
import aiohttp

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from telegram.ext import ContextTypes

from utils.http import get_http_session
from utils.text import bold, code, italic, underline, link, mono

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(BASE_DIR, "..", "data", "cookies.txt")

#dl config
TMP_DIR = "downloads"
os.makedirs(TMP_DIR, exist_ok=True)

MAX_TG_SIZE = 1900 * 1024 * 1024

#format
DL_FORMATS = {
    "video": {"label": "🎥 Video"},
    "mp3": {"label": "🎵 MP3"},
}

DL_CACHE = {}

#ux
def progress_bar(percent: float, length: int = 12) -> str:
    try:
        p = max(0.0, min(100.0, float(percent)))
    except Exception:
        p = 0.0
    filled = int(round((p / 100.0) * length))
    empty = length - filled
    bar = "▰" * filled + "▱" * empty
    return f"{bar} {p:.1f}%"

def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name[:max_len] or "video"
    
def dl_keyboard(dl_id: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎥 Video", callback_data=f"dl:{dl_id}:video"),
            InlineKeyboardButton("🎵 MP3", callback_data=f"dl:{dl_id}:mp3"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"dl:{dl_id}:cancel")
        ]
    ])

# platform check
def is_youtube(url: str) -> bool:
    return any(x in url for x in (
        "youtube.com",
        "youtu.be",
        "music.youtube.com",
    ))

def is_tiktok(url: str) -> bool:
    return any(x in url for x in (
        "tiktok.com",
        "vt.tiktok.com",
        "vm.tiktok.com",
    ))

def is_instagram(url: str) -> bool:
    return any(x in url for x in (
        "instagram.com",
        "instagr.am",
    ))

def is_facebook(url: str) -> bool:
    return any(x in url for x in (
        "facebook.com",
        "fb.watch",
        "fb.com",
        "m.facebook.com",
    ))

def is_twitter_x(url: str) -> bool:
    return any(x in url for x in (
        "twitter.com",
        "x.com",
    ))

def is_reddit(url: str) -> bool:
    return any(x in url for x in (
        "reddit.com",
        "redd.it",
    ))
        
def is_supported_platform(url: str) -> bool:
    return any((
        is_tiktok(url),
        is_youtube(url),
        is_instagram(url),
        is_facebook(url),
        is_twitter_x(url),
        is_reddit(url),
    ))
    
#resolve tt
def normalize_url(text: str) -> str:
    text = text.strip()
    text = text.replace("\u200b", "")
    text = text.split("\n")[0]
    return text
    
def is_invalid_video(path: str) -> bool:
    try:
        p = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration,width,height",
                "-of", "json",
                path
            ],
            capture_output=True,
            text=True
        )
        info = json.loads(p.stdout)
        stream = info["streams"][0]

        duration = float(stream.get("duration", 0))
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))

        return duration < 1.5 or width == 0 or height == 0
    except Exception:
        return True
        
#auto detect
async def auto_dl_detect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = normalize_url(msg.text)

    if text.startswith("/"):
        return

    if not is_supported_platform(text):
        return

    dl_id = uuid.uuid4().hex[:8]

    DL_CACHE[dl_id] = {
        "url": text,
        "user": update.effective_user.id,
        "reply_to": msg.message_id,
        "ts": time.time(),
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬇️ Download", callback_data=f"dlask:{dl_id}:go"),
            InlineKeyboardButton("❌ Close", callback_data=f"dlask:{dl_id}:close"),
        ]
    ])

    await msg.reply_text(
        "👀 <b>Ketemu link</b>\n\nMau aku downloadin?",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


#ask callback
async def dlask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    _, dl_id, action = q.data.split(":", 2)

    data = DL_CACHE.get(dl_id)
    if not data:
        return await q.edit_message_text("❌ Request expired")

    if q.from_user.id != data["user"]:
        return await q.answer("Bukan request lu", show_alert=True)

    if action == "close":
        DL_CACHE.pop(dl_id, None)
        return await q.message.delete()

    # lanjut ke pilih format
    await q.edit_message_text(
        "📥 <b>Pilih format</b>",
        reply_markup=dl_keyboard(dl_id),
        parse_mode="HTML"
    )

#douyin api
async def douyin_download(url, bot, chat_id, status_msg_id):
    session = await get_http_session()

    async with session.post(
        "https://www.tikwm.com/api/",
        data={"url": url},
        timeout=aiohttp.ClientTimeout(total=20)
    ) as r:
        data = await r.json()

    if data.get("code") != 0:
        raise RuntimeError("Douyin API error")

    info = data.get("data") or {}
    video_url = info.get("play")
    if not video_url:
        raise RuntimeError("Video URL kosong")

    title = info.get("title") or "TikTok Video"
    safe_title = sanitize_filename(title)
    out_path = f"{TMP_DIR}/{safe_title}.mp4"

    async with session.get(video_url) as r:
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        last = 0

        with open(out_path, "wb") as f:
            async for chunk in r.content.iter_chunked(64 * 1024):
                f.write(chunk)
                downloaded += len(chunk)

                if total and time.time() - last >= 1.2:
                    pct = downloaded / total * 100
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=(
                            "🚀 <b>Download...</b>\n\n"
                            f"<code>{progress_bar(pct)} {pct:.1f}%</code>"
                        ),
                        parse_mode="HTML"
                    )
                    last = time.time()

    return out_path

#fallback ytdlp
async def ytdlp_download(url, fmt_key, bot, chat_id, status_msg_id):
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        raise RuntimeError("yt-dlp not found in PATH")

    out_tpl = f"{TMP_DIR}/%(title)s.%(ext)s"

    if fmt_key == "mp3":
        cmd = [
            YT_DLP,
            "--cookies", COOKIES_PATH,
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--newline",
            "--progress-template",
            "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "-o", out_tpl,
            url
        ]
    else:
        cmd = [
            YT_DLP,
            "--cookies", COOKIES_PATH,
            "-f", "mp4/bestvideo*+bestaudio/best",
            "--merge-output-format", "mp4",
            "--newline",
            "--progress-template",
            "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "-o", out_tpl,
            url
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    last = 0
    while True:
        line = await proc.stdout.readline()
        if not line:
            break

        raw = line.decode(errors="ignore").strip()
        if "|" in raw:
            head = raw.split("|", 1)[0].replace("%", "")
            if head.replace(".", "", 1).isdigit():
                pct = float(head)
                if time.time() - last >= 1.2:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=(
                            "🚀 <b>yt-dlp download...</b>\n\n"
                            f"<code>{progress_bar(pct)} {pct:.1f}%</code>"
                        ),
                        parse_mode="HTML"
                    )
                    last = time.time()

    await proc.wait()
    if proc.returncode != 0:
        return None

    files = sorted(
        (os.path.join(TMP_DIR, f) for f in os.listdir(TMP_DIR)),
        key=os.path.getmtime,
        reverse=True
    )

    return files[0] if files else None

def reencode_mp3(src_path: str) -> str:
    """
    Force re-encode audio to clean MP3 for Telegram.
    Return new file path.
    """
    fixed_path = f"{TMP_DIR}/{uuid.uuid4().hex}_fixed.mp3"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ab", "192k",
            "-ar", "44100",
            fixed_path
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if not os.path.exists(fixed_path):
        raise RuntimeError("FFmpeg re-encode failed")

    return fixed_path
    
#worker
async def _dl_worker(app, chat_id, reply_to, raw_url, fmt_key, status_msg_id):
    bot = app.bot
    path = None

    try:
        if is_tiktok(raw_url):
            try:
                url = await resolve_tiktok_url(raw_url)
            except Exception:
                url = raw_url

            try:
                path = await douyin_download(url, bot, chat_id, status_msg_id)

                if is_invalid_video(path):
                    try:
                        os.remove(path)
                    except:
                        pass
                    raise RuntimeError("Static video")

            except Exception:
                session = await get_http_session()
                async with session.post(
                    "https://www.tikwm.com/api/",
                    data={"url": url},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    data = await r.json()

                if fmt_key == "mp3":
                    music_url = (
                        data.get("data", {}).get("music")
                        or data.get("data", {}).get("music_info", {}).get("play")
                    )

                    if not music_url:
                        raise RuntimeError("Audio slideshow tidak ditemukan")

                    tmp_audio = f"{TMP_DIR}/{uuid.uuid4().hex}.mp3"

                    async with session.get(music_url) as r:
                        with open(tmp_audio, "wb") as f:
                            async for chunk in r.content.iter_chunked(64 * 1024):
                                f.write(chunk)

                    title = (
                        data.get("data", {}).get("title")
                        or data.get("data", {}).get("desc")
                        or "TikTok Audio"
                    )

                    bot_name = (await bot.get_me()).first_name or "Bot"
                    fixed_audio = reencode_mp3(tmp_audio)
                    
                    await bot.send_chat_action(
                        chat_id=chat_id,
                        action="upload_audio"
                    )
                    
                    await bot.send_audio(
                        chat_id=chat_id,
                        audio=fixed_audio,
                        title=title[:64],
                        performer=bot_name,
                        filename=f"{title[:50]}.mp3",
                        reply_to_message_id=reply_to,
                        disable_notification=True
                    )

                    await bot.delete_message(chat_id, status_msg_id)

                    os.remove(tmp_audio)
                    os.remove(fixed_audio)
                    return

                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text="🖼️ Slideshow terdeteksi, mengirim album...",
                    parse_mode="HTML"
                )

                images = data.get("data", {}).get("images") or []
                if not images:
                    raise RuntimeError("Foto slideshow tidak ditemukan")

                CHUNK_SIZE = 10
                chunks = [images[i:i + CHUNK_SIZE] for i in range(0, len(images), CHUNK_SIZE)]

                bot_name = (await bot.get_me()).first_name or "Bot"

                title = (
                    data.get("data", {}).get("title")
                    or data.get("data", {}).get("desc")
                    or "Slideshow TikTok"
                )

                title = html.escape(title.strip())

                caption_text = (
                    f"🖼️ <b>{title}</b>\n\n"
                    f"🪄 <i>Powered by {html.escape(bot_name)}</i>"
                )

                for idx, chunk in enumerate(chunks):
                    media = []
                    for i, img in enumerate(chunk):
                        media.append(
                            InputMediaPhoto(
                                media=img,
                                caption=caption_text if idx == 0 and i == 0 else None,
                                parse_mode="HTML" if idx == 0 and i == 0 else None
                            )
                        )

                    await bot.send_media_group(
                        chat_id=chat_id,
                        media=media,
                        reply_to_message_id=reply_to if idx == 0 else None
                    )

                await bot.delete_message(chat_id, status_msg_id)
                return
        
        elif not is_tiktok(raw_url):
            path = await ytdlp_download(
                raw_url,
                fmt_key,
                bot,
                chat_id,
                status_msg_id
            )

        else:
            raise RuntimeError("Platform tidak didukung")

        if not path or not os.path.exists(path):
            raise RuntimeError("Download gagal")

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text="🚀 <b>Mengunggah...</b>",
            parse_mode="HTML"
        )

        if fmt_key == "mp3":
            title = os.path.splitext(os.path.basename(path))[0]
            bot_name = (await bot.get_me()).first_name or "Bot"
            fixed_audio = reencode_mp3(path)

            await bot.send_audio(
                chat_id=chat_id,
                audio=fixed_audio,
                title=title[:64],
                performer=bot_name,
                filename=f"{title[:50]}.mp3",
                reply_to_message_id=reply_to,
                disable_notification=True
            )

            os.remove(fixed_audio)

        else:
            caption = os.path.splitext(os.path.basename(path))[0]
            bot_name = (await bot.get_me()).first_name or "Bot"

            await bot.send_video(
                chat_id=chat_id,
                video=path,
                caption=(
                    f"🎬 <b>{html.escape(caption)}</b>\n\n"
                    f"🪄 <i>Powered by {html.escape(bot_name)}</i>"
                ),
                parse_mode="HTML",
                supports_streaming=False,
                reply_to_message_id=reply_to,
                disable_notification=True
            )

        await bot.delete_message(chat_id, status_msg_id)

    except Exception as e:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=f"❌ Gagal: {e}"
            )
        except:
            pass

    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass
                
#dl cmd
async def dl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("❌ Kirim link TikTok / Platform Yt-dlp Support")

    url = context.args[0]

    dl_id = uuid.uuid4().hex[:8]
    DL_CACHE[dl_id] = {
        "url": url,
        "user": update.effective_user.id,
        "reply_to": update.message.message_id
    }

    await update.message.reply_text(
        "📥 <b>Pilih format</b>",
        reply_markup=dl_keyboard(dl_id),
        parse_mode="HTML"
    )

#dl callback
async def dl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    _, dl_id, choice = q.data.split(":", 2)

    data = DL_CACHE.get(dl_id)
    if not data:
        return await q.edit_message_text("❌ Data expired")

    if q.from_user.id != data["user"]:
        return await q.answer("Bukan request lu", show_alert=True)

    if choice == "cancel":
        DL_CACHE.pop(dl_id, None)
        return await q.edit_message_text("❌ Dibatalkan")

    DL_CACHE.pop(dl_id, None)

    await q.edit_message_text(
        f"⏳ <b>Menyiapkan {DL_FORMATS[choice]['label']}...</b>",
        parse_mode="HTML"
    )

    context.application.create_task(
        _dl_worker(
            app=context.application,
            chat_id=q.message.chat.id,
            reply_to=data["reply_to"],
            raw_url=data["url"],
            fmt_key=choice,
            status_msg_id=q.message.message_id
        )
    )

