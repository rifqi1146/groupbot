import os
import re
import time
import html
import uuid
import shutil
import asyncio
import subprocess
import sqlite3
import aiohttp
from utils.config import OWNER_ID
from handlers.join import require_join_or_block
from utils.premium import init_premium_db, premium_load_set, is_premium

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

# dl config
TMP_DIR = "downloads"
os.makedirs(TMP_DIR, exist_ok=True)

AUTO_DL_DB = "data/auto_dl.sqlite3"

MAX_TG_SIZE = 1900 * 1024 * 1024

# format
DL_FORMATS = {
    "video": {"label": "🎥 Video"},
    "mp3": {"label": "🎵 MP3"},
}

DL_CACHE = {}

PREMIUM_ONLY_DOMAINS = {
    "pornhub.com",
    "xnxx.com",
}

# ux
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

def detect_media_type(path: str) -> str:
    ext = os.path.splitext(path.lower())[1]
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return "photo"
    if ext in (".mp4", ".mkv", ".webm"):
        return "video"
    return "unknown"

# sqlite
def _auto_dl_db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(AUTO_DL_DB)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_dl_groups (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()

def _auto_dl_db():
    _auto_dl_db_init()
    return sqlite3.connect(AUTO_DL_DB)

def _load_auto_dl() -> set[int]:
    con = _auto_dl_db()
    try:
        cur = con.execute("SELECT chat_id FROM auto_dl_groups WHERE enabled=1")
        return {int(r[0]) for r in cur.fetchall() if r and r[0] is not None}
    finally:
        con.close()

def _save_auto_dl(groups: set[int]):
    con = _auto_dl_db()
    try:
        now = time.time()
        con.execute("BEGIN")
        con.execute("UPDATE auto_dl_groups SET enabled=0, updated_at=?", (float(now),))
        if groups:
            con.executemany(
                """
                INSERT INTO auto_dl_groups (chat_id, enabled, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  enabled=1,
                  updated_at=excluded.updated_at
                """,
                [(int(cid), float(now)) for cid in groups],
            )
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()


def _is_premium_user(user_id: int) -> bool:
    uid = int(user_id)

    if uid in OWNER_ID:
        return True

    try:
        s = premium_load_set()
    except Exception:
        s = set()

    return is_premium(uid, s)
        
        
def _extract_domain(url: str) -> str:
    u = (url or "").strip().lower()

    if not u.startswith(("http://", "https://")):
        u = "https://" + u

    m = re.search(r"https?://([^/]+)", u)
    if not m:
        return ""
    host = m.group(1)
    host = host.split(":", 1)[0]
    return host


def _is_premium_required(url: str) -> bool:
    host = _extract_domain(url)
    if not host:
        return False

    for d in PREMIUM_ONLY_DOMAINS:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    return False
    
                    
# platform check
def is_pornhub(url: str) -> bool:
    return any(x in url for x in (
        "pornhub.com",
        "www.pornhub.com",
        "m.pornhub.com",
    ))

def is_xnxx(url: str) -> bool:
    return any(x in url for x in (
        "xnxx.com",
        "www.xnxx.com",
        "m.xnxx.com",
    ))
    
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
        is_pornhub(url),
        is_xnxx(url),
    ))

# resolve tt
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
        info = __import__("json").loads(p.stdout)
        stream = info["streams"][0]

        duration = float(stream.get("duration", 0))
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))

        return duration < 1.5 or width == 0 or height == 0
    except Exception:
        return True

async def _is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if user.id in OWNER_ID:
        return True

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except:
        return False

async def autodl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.message
    user_id = msg.from_user.id

    if chat.type == "private":
        return await msg.reply_text(
            "ℹ️ Auto-detect selalu <b>AKTIF</b> di private chat.",
            parse_mode="HTML"
        )

    if not await _is_admin_or_owner(update, context):
        return await msg.reply_text(
            "❌ <b>Anda bukan admin</b>",
            parse_mode="HTML"
        )

    groups = _load_auto_dl()
    arg = context.args[0].lower() if context.args else ""

    if arg == "enable":
        groups.add(chat.id)
        _save_auto_dl(groups)
        return await msg.reply_text(
            "✅ Auto-detect link <b>AKTIF</b> di grup ini.",
            parse_mode="HTML"
        )

    if arg == "disable":
        groups.discard(chat.id)
        _save_auto_dl(groups)
        return await msg.reply_text(
            "❌ Auto-detect link <b>DIMATIKAN</b> di grup ini.",
            parse_mode="HTML"
        )

    if arg == "status":
        if chat.id in groups:
            return await msg.reply_text(
                "📡 Status Auto-detect: <b>AKTIF</b>",
                parse_mode="HTML"
            )
        return await msg.reply_text(
            "📴 Status Auto-detect: <b>NONAKTIF</b>",
            parse_mode="HTML"
        )

    if arg == "list":
        if user_id not in OWNER_ID:
            return

        if not groups:
            return await msg.reply_text(
                "📭 Belum ada grup dengan auto-detect aktif.",
                parse_mode="HTML"
            )

        lines = ["📋 <b>Grup dengan Auto-detect Aktif:</b>\n"]
        for gid in groups:
            try:
                c = await context.bot.get_chat(gid)
                title = html.escape(c.title or str(gid))
                lines.append(f"• {title}")
            except:
                lines.append(f"• <code>{gid}</code>")

        return await msg.reply_text(
            "\n".join(lines),
            parse_mode="HTML"
        )

    return await msg.reply_text(
        "⚙️ <b>Usage:</b>\n"
        "<code>/autodl enable</code>\n"
        "<code>/autodl disable</code>\n"
        "<code>/autodl status</code>\n"
        "<code>/autodl list</code>",
        parse_mode="HTML"
    )

# auto detect
async def auto_dl_detect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    chat = update.effective_chat
    text = normalize_url(msg.text)

    if text.startswith("/"):
        return

    if not is_supported_platform(text):
        return

    if chat.type in ("group", "supergroup"):
        groups = _load_auto_dl()
        if chat.id not in groups:
            return

    if not await require_join_or_block(update, context):
        return
    
    if _is_premium_required(text) and not _is_premium_user(update.effective_user.id):
        return await msg.reply_text("🔞 Link ini hanya bisa didownload user premium.")
            
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

# ask callback
async def dlask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

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

    await q.edit_message_text(
        "📥 <b>Pilih format</b>",
        reply_markup=dl_keyboard(dl_id),
        parse_mode="HTML"
    )

# douyin api
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

# fallback ytdlp
async def ytdlp_download(url, fmt_key, bot, chat_id, status_msg_id):
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        raise RuntimeError("yt-dlp not found in PATH")

    out_tpl = f"{TMP_DIR}/%(title)s.%(ext)s"

    async def run(cmd):
        print("\n[YTDLP CMD]")
        print(" ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        last_edit = 0
        last_pct = -1

        while True:
            line = await proc.stdout.readline()
            if not line:
                break

            raw = line.decode(errors="ignore").strip()
            print("[YTDLP STDOUT]", raw)

            if "|" not in raw:
                continue

            head = raw.split("|", 1)[0].replace("%", "")
            if not head.replace(".", "", 1).isdigit():
                continue

            pct = float(head)
            if pct <= last_pct:
                continue
            last_pct = pct

            now = time.time()
            if now - last_edit >= 6:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=(
                            "🚀 <b>yt-dlp download...</b>\n\n"
                            f"<code>{progress_bar(pct)} {pct:.1f}%</code>"
                        ),
                        parse_mode="HTML"
                    )
                except Exception as e:
                    print("[TG EDIT ERROR]", e)

                last_edit = now

        stdout, stderr = await proc.communicate()

        if stdout:
            print("\n[YTDLP STDOUT REMAIN]")
            print(stdout.decode(errors="ignore"))

        if stderr:
            print("\n[YTDLP STDERR]")
            print(stderr.decode(errors="ignore"))

        print("[YTDLP EXIT CODE]", proc.returncode)
        return proc.returncode

    if fmt_key == "mp3":
        code = await run([
            YT_DLP,
            "--cookies", COOKIES_PATH,
            "--js-runtimes", "deno:/root/.deno/bin/deno",
            "--no-playlist",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--newline",
            "--progress-template",
            "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "-o", out_tpl,
            url
        ])
        if code != 0:
            return None
    else:
        code = await run([
            YT_DLP,
            "--cookies", COOKIES_PATH,
            "--js-runtimes", "deno:/root/.deno/bin/deno",
            "--no-playlist",
            "-f", "bestvideo*+bestaudio/best",
            "--merge-output-format", "mp4",
            "--newline",
            "--progress-template",
            "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "-o", out_tpl,
            url
        ])

        if code != 0:
            print("[YTDLP] video failed → trying bestimage")
            code = await run([
                YT_DLP,
                "--cookies", COOKIES_PATH,
                "--no-playlist",
                "-f", "bestimage",
                "-o", out_tpl,
                url
            ])

            if code != 0:
                return None

    def media_priority(p):
        p = p.lower()
        if p.endswith(".mp4"):
            return 0
        if p.endswith(".mp3"):
            return 1
        if p.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return 2
        return 9

    files = sorted(
        (
            os.path.join(TMP_DIR, f)
            for f in os.listdir(TMP_DIR)
            if f.lower().endswith((".mp4", ".mp3", ".jpg", ".jpeg", ".png", ".webp"))
        ),
        key=lambda p: (media_priority(p), -os.path.getmtime(p))
    )

    print("[YTDLP OUTPUT FILES]", files)
    return files[0] if files else None

def reencode_mp3(src_path: str) -> str:
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

# worker
async def _dl_worker(app, chat_id, reply_to, raw_url, fmt_key, status_msg_id):
    bot = app.bot
    path = None

    def detect_media_type(p):
        ext = os.path.splitext(p.lower())[1]
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            return "photo"
        if ext in (".mp4", ".mkv", ".webm"):
            return "video"
        return "unknown"

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

                    await bot.send_chat_action(chat_id=chat_id, action="upload_audio")

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
        else:
            path = await ytdlp_download(
                raw_url,
                fmt_key,
                bot,
                chat_id,
                status_msg_id
            )

        if not path or not os.path.exists(path):
            raise RuntimeError("Download gagal")

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text="🚀 <b>Mengunggah...</b>",
            parse_mode="HTML"
        )

        bot_name = (await bot.get_me()).first_name or "Bot"
        caption = os.path.splitext(os.path.basename(path))[0]
        media_type = detect_media_type(path)

        if fmt_key == "mp3":
            fixed_audio = reencode_mp3(path)
            await bot.send_audio(
                chat_id=chat_id,
                audio=fixed_audio,
                title=caption[:64],
                performer=bot_name,
                filename=f"{caption[:50]}.mp3",
                reply_to_message_id=reply_to,
                disable_notification=True
            )
            os.remove(fixed_audio)

        elif media_type == "photo":
            await bot.send_photo(
                chat_id=chat_id,
                photo=path,
                caption=(
                    f"🖼️ <b>{html.escape(caption)}</b>\n\n"
                    f"🪄 <i>Powered by {html.escape(bot_name)}</i>"
                ),
                parse_mode="HTML",
                reply_to_message_id=reply_to,
                disable_notification=True
            )

        elif media_type == "video":
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

        else:
            raise RuntimeError("Media tidak didukung")

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

# dl cmd
async def dl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

    if not context.args:
        return await update.message.reply_text("❌ Kirim link TikTok / Platform Yt-dlp Support")

    url = context.args[0]

    if _is_premium_required(url):
        if not _is_premium_user(update.effective_user.id):
            return await update.message.reply_text(
                "🔞 Download dari website ini khusus user premium"
            )

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

# dl callback
async def dl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

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

try:
    _auto_dl_db_init()
except Exception:
    pass
    