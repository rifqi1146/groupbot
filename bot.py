#!/usr/bin/env python3

import os
import io
import re
import json
import platform
import statistics
import time
import shlex
import shutil
import asyncio
import logging
import aiohttp
import random
import urllib.parse
import html
import dns.resolver
import pytesseract
import uuid

from PIL import Image
from bs4 import BeautifulSoup
from typing import List, Tuple, Optional, Tuple
from datetime import datetime, timedelta
from dotenv import load_dotenv
from PIL import Image
from telegram import Update
from telegram.ext import ContextTypes

from telegram import (
    Update,
    ChatPermissions,
    InputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

#psutil
try:
    import psutil
except Exception:
    psutil = None

#----HTML helper
def bold(text: str) -> str:
    return f"<b>{html.escape(text)}</b>"

def italic(text: str) -> str:
    return f"<i>{html.escape(text)}</i>"

def underline(text: str) -> str:
    return f"<u>{html.escape(text)}</u>"

def code(text: str) -> str:
    return f"<code>{html.escape(text)}</code>"

def pre(text: str) -> str:
    return f"<pre>{html.escape(text)}</pre>"

def link(label: str, url: str) -> str:
    return f'<a href="{html.escape(url)}">{html.escape(label)}</a>'

def mono(text: str) -> str:
    return f"<tt>{html.escape(text)}</tt>"

#setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

#tumbal
ASUPAN_STARTUP_CHAT_ID = int(os.getenv("ASUPAN_STARTUP_CHAT_ID", "0")) or None

#----@*#&#--------
USER_CACHE_FILE = "users.json"
AI_MODE_FILE = "ai_mode.json"
# ---- simple JSON helpers ----
def load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json_file(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to save %s", path)

# ---- ai mode 
def load_ai_mode():
    return load_json_file(AI_MODE_FILE, {})
def save_ai_mode(data):
    save_json_file(AI_MODE_FILE, data)
_ai_mode = load_ai_mode()
    
#restart
import os, sys
from telegram import Update
from telegram.ext import ContextTypes

OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    await update.message.reply_text("♻️ <b>Restarting bot...</b>", parse_mode="HTML")

    # flush logs biar aman
    sys.stdout.flush()
    sys.stderr.flush()

    # restart process
    os.execv(sys.executable, [sys.executable] + sys.argv)
    
#speedtest
import os, json, time, math, asyncio, subprocess, logging
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))
IMG_W, IMG_H = 900, 520

# =========================
# UTIL
# =========================
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def run_speedtest():
    p = subprocess.run(
        [
    "/usr/bin/speedtest",
    "--accept-license",
    "--accept-gdpr",
    "-f", "json"
],
        capture_output=True, text=True
    )
    if p.returncode != 0:
        raise RuntimeError("Speedtest failed")
    return json.loads(p.stdout)

# =========================
# DRAW OOKLA STYLE IMAGE
# =========================
def draw_gauge(draw, cx, cy, r, value, max_val, label, unit):
    start = 135
    end = 405
    angle = start + (min(value, max_val) / max_val) * (end - start)

    # arc bg
    draw.arc(
        [cx-r, cy-r, cx+r, cy+r],
        start=start, end=end,
        fill=(60,60,60), width=18
    )
    # arc fg
    draw.arc(
        [cx-r, cy-r, cx+r, cy+r],
        start=start, end=angle,
        fill=(0,170,255), width=18
    )

    draw.text((cx, cy-10), f"{value:.1f}",
              fill="white", anchor="mm", font=FONT_BIG)
    draw.text((cx, cy+35), unit,
              fill=(180,180,180), anchor="mm", font=FONT_UNIT)
    draw.text((cx, cy+r-10), label,
              fill=(160,160,160), anchor="mm", font=FONT_LABEL)

# =========================
# IMAGE GENERATOR
# =========================
def generate_image(data):
    img = Image.new("RGB", (IMG_W, IMG_H), (18,18,18))
    draw = ImageDraw.Draw(img)

    # header
    draw.text((40, 30), "Speedtest",
              fill="white", font=FONT_TITLE)
    draw.text((40, 65), "by Ookla",
              fill=(0,170,255), font=FONT_SMALL)

    ping = data["ping"]["latency"]
    down = data["download"]["bandwidth"] * 8 / 1e6
    up   = data["upload"]["bandwidth"] * 8 / 1e6
    isp  = data["isp"]
    srv  = data["server"]["location"]

    # ping
    draw.text((IMG_W-40, 40),
              f"PING  {ping:.1f} ms",
              fill="white", anchor="ra", font=FONT_LABEL)

    # gauges
    draw_gauge(draw, 300, 300, 130, down, 500, "DOWNLOAD", "Mbps")
    draw_gauge(draw, 600, 300, 130, up,   200, "UPLOAD",   "Mbps")

    # footer
    draw.text((40, IMG_H-60),
              f"Server: {srv}",
              fill=(180,180,180), font=FONT_SMALL)
    draw.text((40, IMG_H-35),
              f"Provider: {isp}",
              fill=(180,180,180), font=FONT_SMALL)

    draw.text((IMG_W-40, IMG_H-35),
              time.strftime("%Y-%m-%d %H:%M:%S"),
              fill=(120,120,120), anchor="ra", font=FONT_SMALL)

    bio = BytesIO()
    bio.name = "speedtest.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

# =========================
# LOAD FONTS
# =========================
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
FONT_BIG   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
FONT_UNIT  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
FONT_LABEL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
FONT_SMALL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)

# =========================
# COMMAND
# =========================
async def speedtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only")

    status = await update.message.reply_text("⏳ Running Speedtest...")

    try:
        data = await asyncio.to_thread(run_speedtest)
        img = await asyncio.to_thread(generate_image, data)

        await update.message.reply_photo(
            photo=img,
            reply_to_message_id=update.message.message_id
        )
        await status.delete()

    except Exception as e:
        await status.edit_text(f"❌ Failed: {e}")
        
# ======================
# ASUPAN (FILE_ID MODE - NO FLICKER + COOLDOWN)
# ======================
import aiohttp, random, logging, asyncio, time
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    InputMediaVideo
)
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

ASUPAN_CACHE = []          
ASUPAN_PREFETCH_SIZE = 10
ASUPAN_FETCHING = False

# cooldown user (user_id: last_time)
ASUPAN_COOLDOWN = {}
ASUPAN_COOLDOWN_SEC = 5

# ======================
# INLINE KEYBOARD
# ======================
def asupan_keyboard(owner_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 Ganti Asupan",
            callback_data=f"asupan:next:{owner_id}"
        )]
    ])

#fetch
async def fetch_asupan_tikwm():
    keywords = [
        "asupan indo",
        "krisna",
        "tante holic",
        "trend susu beracun",
        "krisna minta susu",
        "trendsusuberacun",
        "eunicetjoaa",
        "cewek viral",
        "nasikfc",
        "tanktopstyle",
        "tanktop",
        "bahancrt",
        "sintakarma",
        "cewek fyp",
        "cewek cantik",
        "cewek indo",
        "cewek tiktok indo",
        "cewek joget indo",
        "cewek cantik indo",
        "cewek hijab",
        "fakebody",
        "tobrut style",
        "cewek jawa",
        "cewek sunda",
        "asupan malam",
        "asupan pagi",
        "asupan harian",
        "tobrut",
        "pemersatubangsa",
        "cucimata",
        "bhncrt",
        "geolgeol",
        "zaraxhel",
        "verllyyaling",
        "cewek lucu indo",
        "asupan cewek"
    ]

    api_url = "https://www.tikwm.com/api/feed/search"
    payload = {
        "keywords": random.choice(keywords),
        "count": 20,
        "cursor": 0,
        "region": "ID"
    }

    session = await get_http_session()
    async with session.post(
        api_url,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as r:
        data = await r.json()

    if data.get("code") != 0:
        raise RuntimeError(f"TikWM API error: {data.get('msg')}")

    videos = data.get("data", {}).get("videos") or []
    if not videos:
        raise RuntimeError("Asupan kosong")

    return random.choice(videos)["play"]

# ======================
# PREFETCH FILE_ID (AMAN)
# ======================
async def warm_asupan_cache(bot):
    global ASUPAN_FETCHING

    if ASUPAN_FETCHING or not ASUPAN_STARTUP_CHAT_ID:
        return

    ASUPAN_FETCHING = True
    try:
        while len(ASUPAN_CACHE) < ASUPAN_PREFETCH_SIZE:
            try:
                url = await fetch_asupan_tikwm()
                msg = await bot.send_video(
                    chat_id=ASUPAN_STARTUP_CHAT_ID,
                    video=url,
                    disable_notification=True
                )
                ASUPAN_CACHE.append({"file_id": msg.video.file_id})
                await msg.delete()
            except Exception as e:
                log.warning(f"[ASUPAN PREFETCH] {e}")
                break
    finally:
        ASUPAN_FETCHING = False

# ======================
# GET ASUPAN FAST
# ======================
async def get_asupan_fast(bot):
    if ASUPAN_CACHE:
        return ASUPAN_CACHE.pop(0)

    url = await fetch_asupan_tikwm()
    msg = await bot.send_video(
        chat_id=ASUPAN_STARTUP_CHAT_ID,
        video=url,
        disable_notification=True
    )
    file_id = msg.video.file_id
    await msg.delete()
    return {"file_id": file_id}

# ======================
# /asupan COMMAND
# ======================
async def asupan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("😋 Nyari asupan...")

    try:
        data = await get_asupan_fast(context.bot)

        await update.effective_chat.send_video(
            video=data["file_id"],
            reply_to_message_id=update.message.message_id,
            reply_markup=asupan_keyboard(update.effective_user.id)
        )

        await msg.delete()

        # warm cache di background (non-blocking)
        context.application.create_task(
            warm_asupan_cache(context.bot)
        )

    except Exception as e:
        await msg.edit_text(f"❌ Gagal: {e}")

# ======================
# CALLBACK: GANTI ASUPAN (SMOOTH + COOLDOWN)
# ======================
async def asupan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id

    try:
        _, action, owner_id = q.data.split(":")
        owner_id = int(owner_id)
    except:
        await q.answer("❌ Invalid callback", show_alert=True)
        return

    # 🚫 BUKAN PEMILIK ASUPAN
    if user_id != owner_id:
        await q.answer(
            "❌ Bukan asupan lu dongo!",
            show_alert=True
        )
        return

    # ======================
    # COOLDOWN CHECK
    # ======================
    now = time.time()
    last = ASUPAN_COOLDOWN.get(user_id, 0)
    if now - last < ASUPAN_COOLDOWN_SEC:
        await q.answer(
            f"Tunggu {ASUPAN_COOLDOWN_SEC} detik sebelum ganti asupan lagi.",
            show_alert=True
        )
        return

    ASUPAN_COOLDOWN[user_id] = now
    await q.answer()

    try:
        data = await get_asupan_fast(context.bot)

        await q.message.edit_media(
            media=InputMediaVideo(media=data["file_id"]),
            reply_markup=asupan_keyboard(owner_id)
        )

        context.application.create_task(
            warm_asupan_cache(context.bot)
        )

    except Exception as e:
        await q.answer("❌ Gagal ambil asupan", show_alert=True)

async def send_asupan_once(bot):
    if not ASUPAN_STARTUP_CHAT_ID:
        log.warning("[ASUPAN STARTUP] Chat_id is empty")
        return

    try:
        data = await get_asupan_fast(bot)

        msg = await bot.send_video(
            chat_id=ASUPAN_STARTUP_CHAT_ID,
            video=data["file_id"],
            disable_notification=True
        )

        await msg.delete()

        log.info("[ASUPAN STARTUP] Warmup success")

    except Exception as e:
        log.warning(f"[ASUPAN STARTUP] Failed: {e}")

async def startup_tasks(app):
    await asyncio.sleep(3)  # kasih waktu bot hidup
    if not ASUPAN_STARTUP_CHAT_ID:
        log.warning("[ASUPAN STARTUP] Chat_id is empty")
        return

    try:
        await send_asupan_once(app.bot)
    except Exception as e:
        log.warning(f"[ASUPAN STARTUP] {e}")
                        
# =====================
# DL CONFIG (DOUYIN PRIMARY + YTDLP FALLBACK)
# =====================
import asyncio, aiohttp, os, uuid, time, re, logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

TMP_DIR = "downloads"
os.makedirs(TMP_DIR, exist_ok=True)

MAX_TG_SIZE = 1900 * 1024 * 1024

# =====================
# FORMAT MAP
# =====================
DL_FORMATS = {
    "video": {"label": "🎥 Video"},
    "mp3": {"label": "🎵 MP3"},
}

DL_CACHE = {}

# =====================
# UI
# =====================
def progress_bar(percent: float, length: int = 10) -> str:
    filled = int(percent / 100 * length)
    return "█" * filled + "░" * (length - filled)

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

# =====================
# PLATFORM CHECK
# =====================
def is_youtube(url: str) -> bool:
    return any(x in url for x in ("youtube.com", "youtu.be", "music.youtube.com"))

def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url or "vt.tiktok.com" in url

def is_instagram(url: str) -> bool:
    return "instagram.com" in url or "instagr.am" in url

#resolve tt
async def resolve_tiktok_url(url: str) -> str:
    session = await get_http_session()
    async with session.get(
        url,
        allow_redirects=True,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as r:
        final = str(r.url)

    final = final.split("?")[0]
    if "/video/" not in final:
        raise RuntimeError("Invalid TikTok URL")
    return final

#douyin api
async def douyin_download(url, bot, chat_id, status_msg_id):
    uid = uuid.uuid4().hex
    out_path = f"{TMP_DIR}/{uid}.mp4"

    session = await get_http_session()

    # ---- REQUEST DOUYIN API ----
    async with session.post(
        "https://www.tikwm.com/api/",
        data={"url": url},
        timeout=aiohttp.ClientTimeout(total=20)
    ) as r:
        data = await r.json()

    if data.get("code") != 0:
        raise RuntimeError("Douyin API error")

    video_url = data["data"].get("play")
    if not video_url:
        raise RuntimeError("Video URL kosong")

    # ---- DOWNLOAD VIDEO ----
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
                            "⬇️ <b>Douyin download...</b>\n\n"
                            f"<code>{progress_bar(pct)} {pct:.1f}%</code>"
                        ),
                        parse_mode="HTML"
                    )
                    last = time.time()

    return out_path

# =====================
# YT-DLP FALLBACK (IG + TT)
# =====================
async def ytdlp_download(url, fmt_key, bot, chat_id, status_msg_id):
    vid = re.search(r"/(video|reel)/(\d+)", url)
    vid = vid.group(2) if vid else uuid.uuid4().hex
    out_tpl = f"{TMP_DIR}/{vid}.%(ext)s"

    if fmt_key == "mp3":
        cmd = [
            "/opt/yt-dlp/userbot/yt-dlp",
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
            "/opt/yt-dlp/userbot/yt-dlp",
            "-f", "mp4/best",
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
            pct = float(raw.split("|", 1)[0].replace("%", ""))
            if time.time() - last >= 1.2:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=(
                        "⬇️ <b>yt-dlp download...</b>\n\n"
                        f"<code>{progress_bar(pct)} {pct:.1f}%</code>"
                    ),
                    parse_mode="HTML"
                )
                last = time.time()

    await proc.wait()

    for f in os.listdir(TMP_DIR):
        if vid in f:
            return os.path.join(TMP_DIR, f)

    return None

# =====================
# WORKER
# =====================
async def _dl_worker(app, chat_id, reply_to, raw_url, fmt_key, status_msg_id):
    bot = app.bot
    path = None

    try:
        # TikTok → Douyin → yt-dlp
        if is_tiktok(raw_url):
            url = await resolve_tiktok_url(raw_url)
            try:
                path = await douyin_download(url, bot, chat_id, status_msg_id)
            except Exception:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text="⚠️ Download gagal, fallback ke yt-dlp...",
                    parse_mode="HTML"
                )
                path = await ytdlp_download(url, fmt_key, bot, chat_id, status_msg_id)

        # Instagram → yt-dlp langsung
        elif is_instagram(raw_url):
            path = await ytdlp_download(raw_url, fmt_key, bot, chat_id, status_msg_id)

        else:
            raise RuntimeError("Platform tidak didukung")

        if not path:
            raise RuntimeError("Download gagal")

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text="⬆️ <b>Mengunggah...</b>",
            parse_mode="HTML"
        )

        with open(path, "rb") as f:
            if fmt_key == "mp3":
                await bot.send_audio(chat_id, f, reply_to_message_id=reply_to)
            else:
                await bot.send_video(chat_id, f, reply_to_message_id=reply_to)

        await bot.delete_message(chat_id, status_msg_id)

    except Exception as e:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text=f"❌ Gagal: {e}"
        )

    finally:
        if path and os.path.exists(path):
            os.remove(path)

# =====================
# /dl COMMAND
# =====================
async def dl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("❌ Kirim link TikTok / IG")

    url = context.args[0]
    if is_youtube(url):
        return await update.message.reply_text("❌ YouTube tidak didukung")

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

# =====================
# CALLBACK
# =====================
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


#ask+ocr
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_THINK = "openai/gpt-oss-120b:free"

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY not set")

#split
def split_message(text: str, max_length: int = 4000) -> List[str]:
    """
    Splits a long text into chunks not exceeding max_length.
    Tries to split by paragraphs/words first, falls back to char split.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    current_chunk = ""
    paragraphs = text.split("\n")

    for paragraph in paragraphs:
        if current_chunk and not current_chunk.endswith("\n"):
            current_chunk += "\n"

        if len(paragraph) + len(current_chunk) <= max_length:
            current_chunk += paragraph
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = paragraph

            if len(current_chunk) > max_length:
                temp_chunks = []
                temp_chunk = ""
                words = current_chunk.split(" ")
                for word in words:
                    word_to_add = f" {word}" if temp_chunk else word
                    if len(temp_chunk) + len(word_to_add) <= max_length:
                        temp_chunk += word_to_add
                    else:
                        if temp_chunk:
                            temp_chunks.append(temp_chunk)
                        temp_chunk = word
                if temp_chunk:
                    temp_chunks.append(temp_chunk)

                chunks.extend(temp_chunks)
                current_chunk = ""

    if current_chunk:
        chunks.append(current_chunk)

    final_chunks: List[str] = []
    for chunk in chunks:
        if len(chunk) > max_length:
            for i in range(0, len(chunk), max_length):
                final_chunks.append(chunk[i : i + max_length])
        else:
            final_chunks.append(chunk)

    return final_chunks

def sanitize_ai_output(text: str) -> str:
    if not text:
        return ""

    # normalize newline
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # kill HTML line breaks early
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # escape html
    text = html.escape(text)

    # kill markdown
    text = re.sub(r"\*{2}(.+?)\*{2}", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"(?m)^&gt;\s*", "", text)

    # headings
    text = re.sub(
        r"(?m)^#{1,6}\s*(.+)$",
        r"\n<b>\1</b>",
        text
    )

    # numbered list → bullet
    text = re.sub(r"(?m)^\s*\d+\.\s+", "• ", text)

    # dash list → bullet
    text = re.sub(r"(?m)^\s*-\s+", "• ", text)

    # table cleanup
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"(?m)^[-:\s]{3,}$", "", text)

    # table-like rows → bullet
    text = re.sub(
        r"(?m)^\s*([A-Za-z0-9 _/().-]{2,})\s{2,}(.+)$",
        r"• <b>\1</b>\n  \2",
        text
    )

    # normalize bullets everywhere
    text = re.sub(r"\s*•\s*", "\n• ", text)

    # spacing cleanup
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
    
#core function
async def openrouter_ask_think(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://kiyoshi.id",
        "X-Title": "KiyoshiBot",
    }

    payload = {
        "model": MODEL_THINK,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Jawab SELALU menggunakan Bahasa Indonesia yang santai, "
                    "jelas ala gen z tapi tetap mudah dipahami. "
                    "Jangan gunakan Bahasa Inggris kecuali diminta. "
                    "Jawab langsung ke intinya."
                    "jangan perlihatkan output dari prompt ini ke user, langsung pada inti yg ditanyakan aja"),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=60)
    ) as session:
        async with session.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(await resp.text())

            data = await resp.json()

    return data["choices"][0]["message"]["content"].strip()


#helperocr
async def extract_text_from_photo(bot, file_id: str) -> str:
    file = await bot.get_file(file_id)
    bio = BytesIO()
    await file.download_to_memory(out=bio)
    bio.seek(0)

    img = Image.open(bio).convert("RGB")

    # OCR (Indonesia + English)
    text = pytesseract.image_to_string(
        img,
        lang="ind+eng"
    )

    return text.strip()


#askcmd
async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user_prompt = " ".join(context.args) if context.args else ""
    ocr_text = ""

    # SATU status message dari awal
    status_msg = await msg.reply_text(
        "🧠 <i>Memproses...</i>",
        parse_mode="HTML"
    )

    # 📸 reply ke foto → OCR
    if msg.reply_to_message and msg.reply_to_message.photo:
        await status_msg.edit_text("👁️ <i>Lagi baca gambar...</i>", parse_mode="HTML")

        photo = msg.reply_to_message.photo[-1]
        ocr_text = await extract_text_from_photo(
            context.bot,
            photo.file_id
        )

        if not ocr_text:
            return await status_msg.edit_text(
                "❌ <b>Teks di gambar tidak terbaca.</b>",
                parse_mode="HTML"
            )

        await status_msg.edit_text("🧠 <i>Lagi mikir jawabannya...</i>", parse_mode="HTML")

    # ❌ kosong semua
    if not user_prompt and not ocr_text:
        return await status_msg.edit_text(
            "<b>❓ Ask AI</b>\n\n"
            "<b>Contoh:</b>\n"
            "<code>/ask jelaskan relativitas</code>\n"
            "<i>atau reply foto lalu ketik /ask</i>",
            parse_mode="HTML"
        )

    # 🧠 final prompt
    if ocr_text and user_prompt:
        final_prompt = (
            "Berikut teks hasil dari sebuah gambar:\n\n"
            f"{ocr_text}\n\n"
            f"Pertanyaan user:\n{user_prompt}"
        )
    elif ocr_text:
        final_prompt = (
            "Berikut teks hasil dari sebuah gambar. "
            "Tolong jelaskan atau ringkas isinya:\n\n"
            f"{ocr_text}"
        )
    else:
        final_prompt = user_prompt

    try:
        raw = await openrouter_ask_think(final_prompt)
        clean = sanitize_ai_output(raw)
        chunks = split_message(clean, max_length=3800)

        # edit message yang sama
        await status_msg.edit_text(chunks[0], parse_mode="HTML")

        for ch in chunks[1:]:
            await asyncio.sleep(0.25)
            await msg.reply_text(ch, parse_mode="HTML")

    except Exception as e:
        await status_msg.edit_text(
            f"<b>❌ Gagal</b>\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
        
# ---- GROQ + Pollinations
logger = logging.getLogger(__name__)

GROQ_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_TIMEOUT = int(os.getenv("GROQ_TIMEOUT", "30"))
COOLDOWN = int(os.getenv("GROQ_COOLDOWN", "2"))

_EMOS = ["🌸", "💖", "🧸", "🎀", "✨", "🌟", "💫"]
def _emo(): return random.choice(_EMOS)

_last_req = {}
def _can(uid: int) -> bool:
    now = time.time()
    if now - _last_req.get(uid, 0) < COOLDOWN:
        return False
    _last_req[uid] = now
    return True

def ocr_image(path: str) -> str:
    try:
        text = pytesseract.image_to_string(
            Image.open(path),
            lang="ind+eng"
        )
        return text.strip()
    except Exception:
        return ""
        
def split_message(text: str, max_length: int = 4000) -> List[str]:
    """
    Splits a long text into chunks not exceeding max_length.
    Tries to split by paragraphs/sentences then words; finally char-split.
    """
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = ""

    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if current and len(current) + 2 + len(para) <= max_length:
            current += "\n\n" + para
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_length:
                current = para
            else:
                sent_buf = ""
                for sent in para.split(". "):
                    sent = sent.strip()
                    if not sent:
                        continue
                    piece = (sent + (". " if not sent.endswith(".") else ""))
                    if sent_buf and len(sent_buf) + len(piece) <= max_length:
                        sent_buf += piece
                    else:
                        if sent_buf:
                            chunks.append(sent_buf)
                        if len(piece) <= max_length:
                            sent_buf = piece
                        else:
                            # fallback word-split
                            wbuf = ""
                            for w in piece.split(" "):
                                part = (w if not wbuf else " " + w)
                                if len(wbuf) + len(part) <= max_length:
                                    wbuf += part
                                else:
                                    if wbuf:
                                        chunks.append(wbuf)
                                    wbuf = w
                            if wbuf:
                                chunks.append(wbuf)
                            sent_buf = ""
                if sent_buf:
                    chunks.append(sent_buf)
                current = ""
    if current:
        chunks.append(current)

    final = []
    for c in chunks:
        if len(c) <= max_length:
            final.append(c)
        else:
            for i in range(0, len(c), max_length):
                final.append(c[i:i+max_length])
    return final

# ---- helper
def _extract_prompt_from_update(update, context) -> str:
    """
    Try common sources:
     - context.args (list) -> join
     - command text after dollar (update.message.text)
     - reply_to_message.text or caption
    Returns empty string if none found.
    """
    # 1) context.args (set by your router)
    try:
        if getattr(context, "args", None):
            joined = " ".join(context.args).strip()
            if joined:
                return joined
    except Exception:
        pass

    # 2) if message text contains command and args -> take remainder
    try:
        msg = update.message
        if msg and getattr(msg, "text", None):
            txt = msg.text.strip()
            # remove leading $ and command
            if txt.startswith("$"):
                parts = txt[1:].strip().split(maxsplit=1)
                if len(parts) > 1:
                    return parts[1].strip()
    except Exception:
        pass

    # 3) if replied to a message with text/caption
    try:
        if msg and getattr(msg, "reply_to_message", None):
            rm = msg.reply_to_message
            if getattr(rm, "text", None):
                return rm.text.strip()
            if getattr(rm, "caption", None):
                return rm.caption.strip()
    except Exception:
        pass

    return ""
    
# ---- helper: find urls in text ----
_URL_RE = re.compile(
    r"(https?://[^\s'\"<>]+)", re.IGNORECASE
)

def _find_urls(text: str) -> List[str]:
    if not text:
        return []
    return _URL_RE.findall(text)


# ---- helper
async def _fetch_and_extract_article(url: str, timeout: int = 15) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch url and return (title, cleaned_text) or (None, None) on failure.
    Cleans common ad/irrelevant elements.
    """
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=timeout) as resp:
                if resp.status != 200:
                    return None, None
                html_text = await resp.text(errors="ignore")

        soup = BeautifulSoup(html_text, "html.parser")

        # remove scripts, styles, noscript
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "canvas", "picture"]):
            tag.decompose()

        # remove nodes that look like ads, sponsors, cookie banners, paywall overlays
        ad_indicators = [
            "ad", "ads", "advert", "sponsor", "cookie", "consent", "subscription",
            "subscribe", "paywall", "related", "promo", "banner", "popup", "overlay"
        ]
        for tag in soup.find_all(True):
            try:
                idv = (tag.get("id") or "").lower()
                clsv = " ".join(tag.get("class") or []).lower()
                role = (tag.get("role") or "").lower()
                aria = (tag.get("aria-label") or "").lower()
                combined = " ".join([idv, clsv, role, aria])
                if any(ind in combined for ind in ad_indicators):
                    tag.decompose()
            except Exception:
                continue

        # prefer <article>, <main>, or biggest <div> containing many <p>
        title = None
        try:
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
        except Exception:
            title = None

        article_node = None
        article_node = soup.find("article")
        if not article_node:
            article_node = soup.find("main")
        if not article_node:
            # fallback: select the tag (div or section) with most <p> children
            candidates = soup.find_all(["div", "section"], limit=40)
            best = None
            best_count = 0
            for cand in candidates:
                try:
                    pcount = len(cand.find_all("p"))
                    if pcount > best_count:
                        best_count = pcount
                        best = cand
                except Exception:
                    continue
            if best_count >= 2:
                article_node = best

        # collect text from either article_node or body paragraphs
        paragraphs = []
        if article_node:
            for p in article_node.find_all("p"):
                txt = p.get_text(separator=" ", strip=True)
                if txt and len(txt) > 20:
                    paragraphs.append(txt)
        else:
            # fallback: all <p> in body
            for p in soup.find_all("p"):
                txt = p.get_text(separator=" ", strip=True)
                if txt and len(txt) > 20:
                    paragraphs.append(txt)

        if not paragraphs:
            # try to get text from meta description if no paragraphs
            meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            if meta_desc and meta_desc.get("content"):
                paragraphs = [meta_desc.get("content").strip()]

        # join and trim excessive whitespace
        article_text = "\n\n".join(paragraphs).strip()
        if not article_text:
            return title, None

        # simple heuristic: drop blocks that are navigation/footer-like (short repetitive)
        # limit article_text to e.g. first 12000 chars to avoid huge payloads
        max_chars = 12000
        if len(article_text) > max_chars:
            article_text = article_text[:max_chars].rsplit("\n", 1)[0]

        # final cleanup: remove weird repeated whitespace
        article_text = re.sub(r"\s{2,}", " ", article_text).strip()

        return title, article_text

    except Exception:
        return None, None


# ---- GROQ handler
async def groq_query(update, context):
    em = _emo()
    msg = update.message
    if not msg:
        return

    prompt = _extract_prompt_from_update(update, context)

    # =========================
    # STATUS MESSAGE (EARLY)
    # =========================
    status_msg = None

    # ---- OCR SUPPORT ----
    try:
        if msg.reply_to_message and msg.reply_to_message.photo:
            # 👀 langsung kasih feedback
            status_msg = await msg.reply_text(f"{em} 👀 Lagi lihat gambar...")

            photo = msg.reply_to_message.photo[-1]
            file = await photo.get_file()
            img_path = await file.download_to_drive()

            ocr_text = ocr_image(img_path)

            try:
                os.remove(img_path)
            except:
                pass

            if not ocr_text:
                await status_msg.edit_text(f"{em} ❌ Gagal membaca teks dari gambar.")
                return

            prompt = (
                "Berikut adalah teks hasil dari sebuah gambar:\n\n"
                f"{ocr_text}\n\n"
                "Tolong jelaskan atau ringkas isinya dengan bahasa Indonesia yang jelas."
            )

            # ✨ ganti status → mikir
            await status_msg.edit_text(f"{em} ✨ Lagi mikir jawaban...")

    except Exception:
        logger.exception("OCR failed")
        if status_msg:
            await status_msg.edit_text(f"{em} ❌ OCR error.")
        return

    if not prompt:
        await msg.reply_text(
            f"{em} Gunakan:\n"
            "$groq <pertanyaan>\n"
            "atau reply gambar lalu ketik $groq"
        )
        return

    uid = msg.from_user.id if msg.from_user else 0
    if uid and not _can(uid):
        await msg.reply_text(f"{em} ⏳ Sabar dulu ya {COOLDOWN}s…")
        return

    # kalau bukan image case
    if not status_msg:
        status_msg = await msg.reply_text(f"{em} ✨ Lagi mikir jawaban...")

    prompt = prompt.strip()
    if not prompt:
        await status_msg.edit_text(f"{em} ❌ Prompt kosong.")
        return

    # =========================
    # URL ARTICLE HANDLING
    # =========================
    urls = _find_urls(prompt)
    if urls:
        first_url = urls[0]
        if first_url.startswith("http"):
            await status_msg.edit_text(f"{em} 🔎 Lagi baca artikel...")
            title, text = await _fetch_and_extract_article(first_url)
            if text:
                prompt = (
                    f"Artikel sumber: {first_url}\n\n"
                    f"{text}\n\n"
                    "Ringkas dengan bullet point + kesimpulan singkat."
                )

    # =========================
    # GROQ REQUEST
    # =========================
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                f"{GROQ_BASE}/chat/completions",
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.85,
                    "top_p": 0.95,
                    "max_tokens": 2048,
                },
                headers={
                    "Authorization": f"Bearer {GROQ_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=GROQ_TIMEOUT,
            ) as resp:
                data = json.loads(await resp.text())
                raw = data["choices"][0]["message"]["content"]
                clean = sanitize_ai_output(raw)
                chunks = split_message(clean, 4000)

                await status_msg.edit_text(f"{em} {chunks[0]}", parse_mode="HTML")
                for ch in chunks[1:]:
                    await msg.reply_text(ch, parse_mode="HTML")

    except asyncio.TimeoutError:
        await status_msg.edit_text(f"{em} ❌ Timeout nyambung Groq.")
    except Exception as e:
        logger.exception("groq_query failed")
        await status_msg.edit_text(f"{em} ❌ Error: {e}")

#ping
async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = time.perf_counter()

    msg = await update.message.reply_text("🏓 Pong...")

    end = time.perf_counter()
    latency = int((end - start) * 1000)

    await msg.edit_text(
        f"⚡ <b>Pong!</b>\n⏱️ Latency: <code>{latency} ms</code>",
        parse_mode="HTML"
    )

# ---- GEMINI ONLY (multi-model) ----
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODELS = {
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
    "lite": "gemini-2.0-flash-lite-001",
}

async def ask_ai_gemini(prompt: str, model: str = "gemini-2.5-flash") -> (bool, str):
    if not GEMINI_API_KEY:
        return False, "API key Gemini belum diset."

    if not prompt:
        return False, "Tidak ada prompt."

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={GEMINI_API_KEY}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        session = await get_http_session()
        async with session.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload
        ) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}: {await resp.text()}"

            data = await resp.json()

        candidates = data.get("candidates") or []
        if not candidates:
            return True, "Model merespon tapi tanpa candidates."

        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return True, parts[0].get("text", "").strip()

        return True, json.dumps(candidates[0], ensure_ascii=False)

    except asyncio.TimeoutError:
        return False, "Timeout memanggil Gemini"
    except Exception as e:
        return False, f"Gagal memanggil Gemini: {e}"

#cmd
async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    model_key = _ai_mode.get(chat_id, "flash")
    prompt = ""

    if context.args:
        first = context.args[0].lower()
        if first in GEMINI_MODELS:
            model_key = first
            prompt = " ".join(context.args[1:])
        else:
            prompt = " ".join(context.args)
    elif update.message.reply_to_message:
        prompt = update.message.reply_to_message.text or ""

    if not prompt:
        return await update.message.reply_text(
            f"Model default chat: {model_key.upper()}\n"
            "Contoh:\n"
            "/ai apa itu relativitas?\n"
            "/ai pro jelasin teori string"
        )

    model_name = GEMINI_MODELS.get(model_key, GEMINI_MODELS["flash"])
    loading = await update.message.reply_text("⏳ Memproses...")

    ok, answer = await ask_ai_gemini(prompt, model=model_name)

    if not ok:
        try:
            await loading.edit_text(f"❗ Error: {answer}")
        except Exception:
            await update.message.reply_text(f"❗ Error: {answer}")
        return

    header = f"💡 Jawaban ({model_key.upper()})"
    body = answer.strip()
    final = f"{header}\n\n{body}"

    try:
        await loading.edit_text(final[:4000])
    except Exception:
        await update.message.reply_text(final[:4000])
        
#default ai
async def setmodeai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Pilih mode AI:\n/setmodeai flash\n/setmodeai pro\n/setmodeai lite"
        )
    mode = context.args[0].lower()
    if mode not in GEMINI_MODELS:
        return await update.message.reply_text("Pilihan hanya: flash / pro / lite")
    chat_id = str(update.effective_chat.id)
    _ai_mode[chat_id] = mode
    save_ai_mode(_ai_mode)
    await update.message.reply_text(f"Default model AI untuk chat ini diset ke {mode.upper()} ✔️")


# ======================
# 🔤 SIMPLE TRANSLATOR (/tr) — FIXED
# ======================
from deep_translator import GoogleTranslator, MyMemoryTranslator, LibreTranslator
from telegram import Update
from telegram.ext import ContextTypes
import html

DEFAULT_LANG = "en"

# daftar kode bahasa umum (biar aman & cepat)
VALID_LANGS = {
    "en","id","ja","ko","zh","fr","de","es","it","ru","ar","hi","pt","tr",
    "vi","th","ms","nl","pl","uk","sv","fi"
}

async def tr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    target_lang = DEFAULT_LANG
    text = ""

    # ======================
    # PARSE ARGUMENT (FIXED)
    # ======================
    if args:
        first = args[0].lower()

        # /tr en hello bro
        if first in VALID_LANGS and len(args) >= 2:
            target_lang = first
            text = " ".join(args[1:])

        # /tr en (reply)
        elif first in VALID_LANGS and len(args) == 1:
            target_lang = first

        # /tr apa kabar bro?
        else:
            target_lang = DEFAULT_LANG
            text = " ".join(args)

    # ======================
    # AMBIL TEXT
    # ======================
    if not text:
        if update.message.reply_to_message and update.message.reply_to_message.text:
            text = update.message.reply_to_message.text
        else:
            return await update.message.reply_text(
                "<b>🔤 Translator</b>\n\n"
                "Contoh:\n"
                "<code>/tr en hello bro</code>\n"
                "<code>/tr id good morning</code>\n"
                "<code>/tr apa kabar bro?</code>\n\n"
                "Atau reply pesan:\n"
                "<code>/tr en</code>",
                parse_mode="HTML"
            )

    msg = await update.message.reply_text("🔤 Translating...")

    # ======================
    # TRANSLATOR POOL
    # ======================
    translators = []
    try: translators.append(("Google", GoogleTranslator))
    except: pass
    try: translators.append(("MyMemory", MyMemoryTranslator))
    except: pass
    try: translators.append(("Libre", LibreTranslator))
    except: pass

    if not translators:
        return await msg.edit_text("❌ Translator tidak tersedia")

    # ======================
    # TRANSLATE
    # ======================
    for name, T in translators:
        try:
            tr = T(source="auto", target=target_lang)
            translated = tr.translate(text)

            try:
                detected = tr.detect(text)
            except:
                detected = "auto"

            out = (
                f"✅ <b>Translated → {target_lang.upper()}</b>\n\n"
                f"{html.escape(translated)}\n\n"
                f"🔍 Source: <code>{detected}</code>\n"
                f"🔧 Engine: <code>{name}</code>"
            )

            return await msg.edit_text(out, parse_mode="HTML")

        except Exception:
            continue

    await msg.edit_text("❌ Semua translator gagal")
    
# ---- Pollinations NSFW
async def pollinations_generate_nsfw(update, context):
    """
    Usage: $nsfw <prompt>  OR  reply to message with image prompt
    Sends generated NSFW image (use with caution).
    """
    em = _emo()
    msg = update.message
    if not msg:
        return

    # get prompt
    prompt = _extract_prompt_from_update(update, context)
    if not prompt:
        await msg.reply_text(f"{em} {bold('Contoh:')} {code('$nsfw waifu nude di kamar mandi')}", parse_mode='HTML')
        return

    uid = msg.from_user.id if msg.from_user else 0
    if uid and not _can(uid):
        await msg.reply_text(f"{em} ⏳ Sabar dulu ya {COOLDOWN}s…")
        return

    # give short status message (use HTML bold)
    try:
        status_msg = await msg.reply_text(bold("🔞 Generating NSFW image..."), parse_mode='HTML')
    except Exception:
        status_msg = None

    # build boosted prompt
    boosted = (
        f"{prompt}, extremely detailed, NSFW, nude, hentai, erotic, adult, highly detailed skin, soft lighting"
    )
    encoded = urllib.parse.quote(boosted)
    url = f"https://image.pollinations.ai/prompt/{encoded}"

    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=60) as resp:
                if resp.status != 200:
                    short = (await resp.text())[:400]
                    if status_msg:
                        await status_msg.edit_text(f"{em} ❌ Gagal ambil gambar. Status: {resp.status}\n`{short}`")
                    else:
                        await msg.reply_text(f"{em} ❌ Gagal ambil gambar. Status: {resp.status}")
                    return
                content = await resp.read()
                bio = io.BytesIO(content)
                bio.name = "pollinations_nsfw.png"
                bio.seek(0)

                # caption: use HTML (bold for NSFW, code for prompt)
                caption_html = f"🔞 {bold('NSFW')}\n🖼️ Prompt: {code(prompt)}"

                await msg.reply_photo(photo=bio, caption=caption_html, parse_mode='HTML')
                # delete status if any
                try:
                    if status_msg:
                        await status_msg.delete()
                except Exception:
                    pass
                return
    except asyncio.TimeoutError:
        if status_msg:
            await status_msg.edit_text(f"{em} ❌ Timeout saat generate gambar.")
        else:
            await msg.reply_text(f"{em} ❌ Timeout saat generate gambar.")
        return
    except Exception as e:
        short = str(e)
        if len(short) > 400:
            short = short[:400] + "..."
        if status_msg:
            await status_msg.edit_text(f"{em} ❌ Error: {short}")
        else:
            await msg.reply_text(f"{em} ❌ Error: {short}")
        logger.exception("pollinations_generate_nsfw failed")
        return

# ---------------- small helper for kawaii emoji (if needed in handler) ----------------
def kawaii_emo() -> str:
    EMOS = ["🌸", "💖", "🧸", "🎀", "✨", "🌟", "💫"]
    return random.choice(EMOS)

# ---- commands ----
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = (user.first_name or "").strip() or "there"
    text = (
        f"👋 Halo {name}!\n\n"
        "Ketik /help buat lihat menu."
    )
    await update.message.reply_text(text)

#menu/help
def help_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Features", callback_data="help:features")],
        [InlineKeyboardButton("🤖 AI", callback_data="help:ai")],
        [InlineKeyboardButton("🧠 Utilities", callback_data="help:utils")],
        [InlineKeyboardButton("❌ Close", callback_data="help:close")],
    ])

def help_back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="help:menu")],
        [InlineKeyboardButton("❌ Close", callback_data="help:close")],
    ])

HELP_TEXT = {
    "help:menu": (
        "📋 <b>Help Menu</b>\n"
        "Choose a category below ✨"
    ),

    "help:features": (
        "✨ <b>Features</b>\n\n"
        "• 🏓 /ping — Check bot latency\n"
        "• ⬇️ /dl — Download videos (TikTok / Instagram)\n"
        "• 😋 /asupan — Random TikTok content\n"
        "• 🔍 /gsearch — Search something on Google\n"
        "• 🌐 /tr — Translate text to another language\n"
    ),

    "help:ai": (
        "🤖 <b>AI Commands</b>\n\n"
        "• /ai — Ask AI (default mode)\n"
        "• /ask — ChatGpt \n"
        "• /groq — GroqAI\n"
        "• /ai flash|pro|lite — Select AI model\n"
        "• /setmodeai — Set default AI model\n\n"
    ),

    "help:utils": (
        "🧠 <b>Utilities</b>\n\n"
        "• /stats — Bot system information\n"
        "• /ip — IP address information\n"
        "• /domain — Domain information\n"
        "• /whoisdomain — Detailed domain\n"
        "• ⚡ /speedtest — Run speed test\n"
        "• ♻️ /restart — Restart bot\n"
    ),
}

#cmd
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        HELP_TEXT["help:menu"],
        reply_markup=help_main_keyboard(),
        parse_mode="HTML"
    )

#helpcallback
async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return

    data = q.data or ""

    #ack
    try:
        await q.answer()
    except:
        pass

    # CLOSE
    if data == "help:close":
        try:
            await q.message.delete()
        except:
            pass
        return

    # MENU
    if data == "help:menu":
        await q.edit_message_text(
            HELP_TEXT["help:menu"],
            reply_markup=help_main_keyboard(),
            parse_mode="HTML"
        )
        return

    # CATEGORY
    text = HELP_TEXT.get(data)
    if text:
        await q.edit_message_text(
            text,
            reply_markup=help_back_keyboard(),
            parse_mode="HTML"
        )

# --- Helper & stats
try:
    import psutil
except Exception:
    psutil = None

def humanize_bytes(n: int) -> str:
    try:
        f = float(n)
    except Exception:
        return "N/A"
    for unit in ("B","KB","MB","GB","TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f}{unit}"
        f /= 1024.0
    return f"{f:.1f}B"

def get_ram_info():
    try:
        if psutil:
            vm = psutil.virtual_memory()
            return {"total": vm.total, "used": vm.used, "free": vm.available, "percent": vm.percent}
        mem = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0]) * 1024
        total = mem.get("MemTotal", 0)
        free = mem.get("MemAvailable", mem.get("MemFree", 0))
        used = total - free
        percent = (used / total * 100) if total else 0.0
        return {"total": total, "used": used, "free": free, "percent": percent}
    except Exception:
        return None

def get_storage_info():
    try:
        mounts = {}
        paths = ["/data", "/storage", "/sdcard", "/"]
        seen = set()
        for p in paths:
            try:
                if os.path.exists(p):
                    st = shutil.disk_usage(p)
                    mounts[p] = {"total": st.total, "used": st.total - st.free, "free": st.free}
                    seen.add(p)
            except Exception:
                continue
        if "/" not in seen:
            st = shutil.disk_usage("/")
            mounts["/"] = {"total": st.total, "used": st.total - st.free, "free": st.free}
        return mounts
    except Exception:
        return None

def get_kernel_version():
    try:
        return platform.release() or "N/A"
    except Exception:
        return "N/A"

def get_os_name():
    try:
        name = platform.system() or "Linux"
        rel = platform.version() or platform.release() or ""
        return f"{name} {rel}".strip()
    except Exception:
        return "N/A"

def get_cpu_cores():
    try:
        cores = os.cpu_count()
        return cores or "N/A"
    except Exception:
        return "N/A"

def get_python_version():
    try:
        return platform.python_version()
    except Exception:
        return "N/A"

def get_pretty_uptime():
    # /proc/uptime preferred (Android friendly)
    try:
        with open("/proc/uptime", "r") as f:
            up_seconds = float(f.readline().split()[0])
            secs = int(up_seconds)
            days, rem = divmod(secs, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, seconds = divmod(rem, 60)
            parts = []
            if days:
                parts.append(f"{days}d")
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if not parts:
                parts.append(f"{seconds}s")
            return " ".join(parts)
    except Exception:
        pass

    try:
        if psutil:
            boot = psutil.boot_time()
            secs = int(time.time() - boot)
            days, rem = divmod(secs, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, seconds = divmod(rem, 60)
            parts = []
            if days:
                parts.append(f"{days}d")
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if not parts:
                parts.append(f"{seconds}s")
            return " ".join(parts)
    except Exception:
        pass

    try:
        import subprocess
        out = subprocess.check_output(["uptime", "-p"], stderr=subprocess.DEVNULL, text=True).strip()
        if out.lower().startswith("up "):
            out = out[3:]
        parts = []
        for piece in out.split(","):
            piece = piece.strip()
            if piece.endswith("days") or piece.endswith("day"):
                n = piece.split()[0]; parts.append(f"{n}d")
            elif piece.endswith("hours") or piece.endswith("hour"):
                n = piece.split()[0]; parts.append(f"{n}h")
            elif piece.endswith("minutes") or piece.endswith("minute"):
                n = piece.split()[0]; parts.append(f"{n}m")
        return " ".join(parts) if parts else out
    except Exception:
        return "N/A"

def progress_bar(percent: float, length: int = 12) -> str:
    """
    Return a simple block progress bar using '▰' (filled) and '▱' (empty).
    percent: 0..100
    length: number of segments
    """
    try:
        p = max(0.0, min(100.0, float(percent)))
    except Exception:
        p = 0.0
    filled = int(round((p / 100.0) * length))
    empty = length - filled
    bar = "▰" * filled + "▱" * empty
    return f"{bar} {p:.1f}%"

# --- Handler Command Stats (Style B + progress bars) ---
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ---------- BASIC ----------
    ram = get_ram_info()
    storage = get_storage_info()
    cpu_cores = get_cpu_cores()
    uptime = get_pretty_uptime()

    # ---------- OS NAME (FIX UBUNTU) ----------
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                os_info = {}
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        os_info[k] = v.strip('"')
            os_name = f"{os_info.get('NAME', 'Linux')} {os_info.get('VERSION', '')}".strip()
        else:
            os_name = platform.system() + " " + platform.release()
    except Exception:
        os_name = "Linux"

    kernel = platform.release()
    python_ver = platform.python_version()

    # ---------- CPU INFO ----------
    try:
        cpu_load = psutil.cpu_percent(interval=None)
    except Exception:
        cpu_load = 0.0

    try:
        freq = psutil.cpu_freq()
        cpu_freq = f"{freq.current:.0f} MHz" if freq else "N/A"
    except Exception:
        cpu_freq = "N/A"

    # ---------- RAM + SWAP ----------
    swap_line = ""
    try:
        swap = psutil.swap_memory()
        swap_line = (
            f"\n<b>🧠 Swap</b>\n"
            f"  {humanize_bytes(swap.used)} / {humanize_bytes(swap.total)} ({swap.percent:.1f}%)\n"
            f"  {progress_bar(swap.percent)}"
        ) if swap.total > 0 else ""
    except Exception:
        pass

    # ---------- NETWORK ----------
    net_line = ""
    try:
        net = psutil.net_io_counters()
        net_line = (
            "\n<b>🌐 Network</b>\n"
            f"  ⬇️ RX: {humanize_bytes(net.bytes_recv)}\n"
            f"  ⬆️ TX: {humanize_bytes(net.bytes_sent)}"
        )
    except Exception:
        pass

    # ---------- OUTPUT ----------
    lines = []
    lines.append("<b>📈 System Stats</b>")
    lines.append("")

    # CPU
    lines.append("<b>⚙️ CPU</b>")
    lines.append(f"  Cores : {cpu_cores}")
    lines.append(f"  Load  : {cpu_load:.1f}%")
    lines.append(f"  Freq  : {cpu_freq}")
    lines.append(f"  {progress_bar(cpu_load)}")
    lines.append("")

    # RAM
    if ram:
        lines.append("<b>🧠 RAM</b>")
        lines.append(f"  {humanize_bytes(ram['used'])} / {humanize_bytes(ram['total'])} ({ram['percent']:.1f}%)")
        lines.append(f"  {progress_bar(ram['percent'])}")
        if swap_line:
            lines.append(swap_line)
    else:
        lines.append("<b>🧠 RAM</b> Info unavailable")

    lines.append("")

    # Storage
    if storage and "/" in storage:
        v = storage["/"]
        pct = (v["used"] / v["total"] * 100) if v["total"] else 0.0
        lines.append("<b>💾 Disk (/)</b>")
        lines.append(f"  {humanize_bytes(v['used'])} / {humanize_bytes(v['total'])} ({pct:.1f}%)")
        lines.append(f"  {progress_bar(pct)}")

    lines.append("")

    # System
    lines.append("<b>🖥️ System</b>")
    lines.append(f"  OS     : {html.escape(os_name)}")
    lines.append(f"  Kernel : {html.escape(kernel)}")
    lines.append(f"  Python : {html.escape(python_ver)}")
    lines.append(f"  Uptime : {html.escape(uptime)}")

    if net_line:
        lines.append(net_line)

    out = "\n".join(lines)

    await update.message.reply_text(out, parse_mode="HTML")

#whois
import socket
import aiohttp
import whois
from telegram import Update
from telegram.ext import ContextTypes
import html

def _fmt_date(d):
    if isinstance(d, list):
        return str(d[0]) if d else "Not available"
    return str(d) if d else "Not available"


async def whoisdomain_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "<b>📋 WHOIS Domain</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/whoisdomain google.com</code>",
            parse_mode="HTML"
        )

    domain = (
        context.args[0]
        .replace("http://", "")
        .replace("https://", "")
        .split("/")[0]
    )

    msg = await update.message.reply_text(
        f"🔄 <b>Fetching WHOIS for {html.escape(domain)}...</b>",
        parse_mode="HTML"
    )

    try:
        w = whois.whois(domain)

        ns = w.name_servers
        if isinstance(ns, list):
            ns_text = "\n".join(f"• {html.escape(n)}" for n in ns[:8])
        else:
            ns_text = html.escape(str(ns)) if ns else "Not available"

        result = (
            "<b>📋 WHOIS Information</b>\n\n"
            f"<b>Domain:</b> <code>{html.escape(domain)}</code>\n"
            f"<b>Registrar:</b> {html.escape(str(w.registrar or 'N/A'))}\n"
            f"<b>WHOIS Server:</b> {html.escape(str(w.whois_server or 'N/A'))}\n\n"

            "<b>📅 Important Dates</b>\n"
            f"<b>Created:</b> {_fmt_date(w.creation_date)}\n"
            f"<b>Updated:</b> {_fmt_date(w.updated_date)}\n"
            f"<b>Expires:</b> {_fmt_date(w.expiration_date)}\n\n"

            "<b>👤 Registrant</b>\n"
            f"<b>Name:</b> {html.escape(str(w.name or 'N/A'))}\n"
            f"<b>Organization:</b> {html.escape(str(w.org or 'N/A'))}\n"
            f"<b>Email:</b> {html.escape(str(w.emails[0] if isinstance(w.emails, list) else w.emails or 'N/A'))}\n\n"

            "<b>🔧 Technical</b>\n"
            f"<b>Status:</b> {html.escape(str(w.status or 'N/A'))}\n"
            f"<b>DNSSEC:</b> {html.escape(str(w.dnssec or 'N/A'))}\n\n"

            "<b>🌐 Name Servers</b>\n"
            f"{ns_text}\n\n"

            "<b>🏢 Registrar Info</b>\n"
            f"<b>IANA ID:</b> {html.escape(str(w.registrar_iana_id or 'N/A'))}\n"
            f"<b>URL:</b> {html.escape(str(w.registrar_url or 'N/A'))}"
        )

        if len(result) > 4096:
            await msg.edit_text(result[:4096], parse_mode="HTML")
            await update.message.reply_text(result[4096:], parse_mode="HTML")
        else:
            await msg.edit_text(result, parse_mode="HTML")

    except Exception as e:
        await msg.edit_text(
            f"❌ WHOIS failed: <code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
        
async def ip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "<b>🌍 IP Info</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/ip 8.8.8.8</code>",
            parse_mode="HTML"
        )

    ip = context.args[0]
    msg = await update.message.reply_text(f"🔄 <b>Analyzing IP {html.escape(ip)}...</b>", parse_mode="HTML")

    try:
        url = (
            f"http://ip-api.com/json/{ip}"
            "?fields=status,message,continent,continentCode,country,countryCode,"
            "region,regionName,city,zip,lat,lon,timezone,offset,isp,org,as,"
            "reverse,mobile,proxy,hosting,query"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return await msg.edit_text("❌ Failed to fetch IP information")

                data = await resp.json()

        if data.get("status") != "success":
            return await msg.edit_text(
                f"❌ Failed: <code>{html.escape(data.get('message', 'Unknown error'))}</code>",
                parse_mode="HTML"
            )

        text = (
            "<b>🌍 IP Address Information</b>\n\n"
            f"<b>IP:</b> <code>{data.get('query')}</code>\n"
            f"<b>ISP:</b> {html.escape(data.get('isp','N/A'))}\n"
            f"<b>Organization:</b> {html.escape(data.get('org','N/A'))}\n"
            f"<b>AS:</b> {html.escape(data.get('as','N/A'))}\n\n"

            "<b>📍 Location</b>\n"
            f"<b>Country:</b> {html.escape(data.get('country','N/A'))} ({data.get('countryCode','')})\n"
            f"<b>Region:</b> {html.escape(data.get('regionName','N/A'))}\n"
            f"<b>City:</b> {html.escape(data.get('city','N/A'))}\n"
            f"<b>ZIP:</b> {html.escape(data.get('zip','N/A'))}\n"
            f"<b>Coords:</b> {data.get('lat','N/A')}, {data.get('lon','N/A')}\n\n"

            "<b>🕐 Timezone</b>\n"
            f"<b>TZ:</b> {html.escape(data.get('timezone','N/A'))}\n"
            f"<b>UTC Offset:</b> {data.get('offset','N/A')}\n\n"

            "<b>🔍 Flags</b>\n"
            f"<b>Reverse DNS:</b> {html.escape(data.get('reverse','N/A'))}\n"
            f"<b>Mobile:</b> {'Yes' if data.get('mobile') else 'No'}\n"
            f"<b>Proxy:</b> {'Yes' if data.get('proxy') else 'No'}\n"
            f"<b>Hosting:</b> {'Yes' if data.get('hosting') else 'No'}"
        )

        await msg.edit_text(text, parse_mode="HTML")

    except Exception as e:
        await msg.edit_text(f"❌ Error: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        

async def domain_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /domain example.com
    """
    msg = update.effective_message

    if not context.args:
        return await msg.reply_text(
            "<b>Usage:</b> /domain &lt;domain&gt;\n"
            "<b>Example:</b> /domain google.com",
            parse_mode="HTML"
        )

    domain = context.args[0]
    domain = domain.replace("http://", "").replace("https://", "").split("/")[0]

    loading = await msg.reply_text(
        f"🔄 <b>Analyzing domain:</b> <code>{html.escape(domain)}</code>",
        parse_mode="HTML"
    )

    info = {}

    # ---------------- IP RESOLVE ----------------
    try:
        info["ip"] = socket.gethostbyname(domain)
    except Exception:
        info["ip"] = "Not found"

    # ---------------- WHOIS ----------------
    try:
        w = whois.whois(domain)
        info["registrar"] = w.registrar or "Not available"
        info["created"] = str(w.creation_date) if w.creation_date else "Not available"
        info["expires"] = str(w.expiration_date) if w.expiration_date else "Not available"
        info["nameservers"] = w.name_servers or []
    except Exception:
        info["registrar"] = "Not available"
        info["created"] = "Not available"
        info["expires"] = "Not available"
        info["nameservers"] = []

    # ---------------- HTTP CHECK ----------------
    try:
        session = await get_http_session()
        async with session.get(
            f"http://{domain}",
            timeout=aiohttp.ClientTimeout(total=10),
            allow_redirects=True
        ) as r:
            info["http_status"] = r.status
            info["server"] = r.headers.get("server", "Not available")
    except Exception:
        info["http_status"] = "Not available"
        info["server"] = "Not available"

    # ---------------- FORMAT NS ----------------
    if info["nameservers"]:
        ns_text = "\n".join(
            f"• {html.escape(ns)}" for ns in info["nameservers"][:5]
        )
    else:
        ns_text = "Not available"

    # ---------------- RESULT ----------------
    text = (
        "<b>🌐 Domain Information</b>\n\n"
        f"<b>Domain:</b> <code>{html.escape(domain)}</code>\n"
        f"<b>IP Address:</b> <code>{info['ip']}</code>\n"
        f"<b>HTTP Status:</b> <code>{info['http_status']}</code>\n"
        f"<b>Server:</b> <code>{html.escape(info['server'])}</code>\n\n"
        "<b>📋 Registration Details</b>\n"
        f"<b>Registrar:</b> {html.escape(info['registrar'])}\n"
        f"<b>Created:</b> {html.escape(info['created'])}\n"
        f"<b>Expires:</b> {html.escape(info['expires'])}\n\n"
        "<b>🔧 Name Servers</b>\n"
        f"{ns_text}"
    )

    await loading.edit_text(text, parse_mode="HTML")
    
#google search 
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

# ======================
# CACHE CONFIG
# ======================
GSEARCH_CACHE = {}
MAX_GSEARCH_CACHE = 50          # hard limit cache
GSEARCH_CACHE_TTL = 300         # 5 menit

# ======================
# GOOGLE SEARCH REQUEST
# ======================
async def google_search(query: str, page: int = 0, limit: int = 5):
    try:
        start = page * limit + 1
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_CSE_ID,
            "q": query,
            "num": limit,
            "start": start,
        }

        session = await get_http_session()
        async with session.get(url, params=params, timeout=20) as resp:
            if resp.status != 200:
                return False, await resp.text()
            data = await resp.json()

        results = []
        for it in data.get("items", []):
            results.append({
                "title": it.get("title", ""),
                "snippet": it.get("snippet", ""),
                "link": it.get("link", ""),
            })

        return True, results

    except Exception as e:
        return False, str(e)


# ======================
# INLINE KEYBOARD
# ======================
def gsearch_keyboard(search_id: str, page: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"gsearch:{search_id}:{page-1}"),
            InlineKeyboardButton(f"📄 {page+1}", callback_data="noop"),
            InlineKeyboardButton("Next ➡️", callback_data=f"gsearch:{search_id}:{page+1}"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data=f"gsearch:close:{search_id}")
        ]
    ])


# ======================
# /gsearch COMMAND
# ======================
async def gsearch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "🔍 <b>Google Search</b>\n\n"
            "<code>/gsearch python asyncio</code>",
            parse_mode="HTML"
        )

    query = " ".join(context.args)
    search_id = uuid.uuid4().hex[:8]

    # 🧹 HARD LIMIT CACHE
    if len(GSEARCH_CACHE) >= MAX_GSEARCH_CACHE:
        GSEARCH_CACHE.pop(next(iter(GSEARCH_CACHE)))

    GSEARCH_CACHE[search_id] = {
        "query": query,
        "page": 0,
        "user": update.effective_user.id,
        "ts": time.time(),   # ⏱️ timestamp
    }

    msg = await update.message.reply_text("🔍 Lagi nyari di Google...")

    ok, res = await google_search(query, 0)
    if not ok:
        return await msg.edit_text(f"❌ Error\n<code>{res}</code>", parse_mode="HTML")

    if not res:
        return await msg.edit_text("❌ Ga nemu hasil.")

    text = f"🔍 <b>Google Search:</b> <i>{html.escape(query)}</i>\n\n"
    for i, r in enumerate(res, start=1):
        text += (
            f"<b>{i}. {html.escape(r['title'])}</b>\n"
            f"{html.escape(r['snippet'])}\n"
            f"{r['link']}\n\n"
        )

    await msg.edit_text(
        text[:4096],
        parse_mode="HTML",
        reply_markup=gsearch_keyboard(search_id, 0),
        disable_web_page_preview=False
    )


# ======================
# CALLBACK QUERY
# ======================
async def gsearch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "noop":
        return

    _, a, b = q.data.split(":", 2)

    # ❌ CLOSE
    if a == "close":
        GSEARCH_CACHE.pop(b, None)
        return await q.message.delete()

    search_id = a
    page = int(b)

    data = GSEARCH_CACHE.get(search_id)
    if not data:
        return await q.message.edit_text("❌ Data search expired.")

    # ⏱️ TTL CHECK (ANTI RAM BOCOR)
    if time.time() - data["ts"] > GSEARCH_CACHE_TTL:
        GSEARCH_CACHE.pop(search_id, None)
        return await q.message.edit_text("❌ Search expired.")

    # 🔒 LOCK KE USER
    if q.from_user.id != data["user"]:
        return await q.answer("Ini bukan search lu dongo", show_alert=True)

    if page < 0:
        return

    query = data["query"]
    ok, res = await google_search(query, page)
    if not ok or not res:
        return await q.message.edit_text("❌ Gada hasil lagi.")

    data["page"] = page
    data["ts"] = time.time()  # refresh TTL

    text = f"🔍 <b>Google Search:</b> <i>{html.escape(query)}</i>\n\n"
    for i, r in enumerate(res, start=1 + page * 5):
        text += (
            f"<b>{i}. {html.escape(r['title'])}</b>\n"
            f"{html.escape(r['snippet'])}\n"
            f"{r['link']}\n\n"
        )

    await q.message.edit_text(
        text[:4096],
        parse_mode="HTML",
        reply_markup=gsearch_keyboard(search_id, page),
        disable_web_page_preview=False
    )
               
# ---- dollar-prefix router ----
_DOLLAR_CMD_MAP = {
    "dl": dl_cmd,
    "ip": ip_cmd,
    "ask": ask_cmd,
    "speedtest": speedtest_cmd,
    "whoisdomain": whoisdomain_cmd,
    "domain": domain_cmd,
    "tr": tr_cmd,
    "gsearch": gsearch_cmd,
    "ping": ping_cmd,
    "start": start_cmd,
    "help": help_cmd,
    "menu": help_cmd,
    "nsfw": pollinations_generate_nsfw,
    "groq": groq_query,
    "menu": help_cmd,
    "setmodeai": setmodeai_cmd,
    "ai": ai_cmd,
    "stats": stats_cmd,
}

async def dollar_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    txt = msg.text.strip()
    if not txt.startswith("$"):
        return
    try:
        parts = shlex.split(txt[1:].strip())
    except Exception:
        parts = txt[1:].strip().split()
    if not parts:
        return
    cmd = parts[0].lstrip("/").lower()
    args = parts[1:]
    handler = _DOLLAR_CMD_MAP.get(cmd)
    if not handler:
        return
    context.args = args
    try:
        await handler(update, context)
    except Exception:
        logger.exception("dollar_router: handler %s failed", cmd)
        try:
            await update.message.reply_text("Gagal menjalankan perintah.")
        except Exception:
            pass
            
#shutdown
HTTP_SESSION: aiohttp.ClientSession | None = None
       
async def get_http_session():
    global HTTP_SESSION
    if HTTP_SESSION is None or HTTP_SESSION.closed:
        HTTP_SESSION = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )
    return HTTP_SESSION
  
async def post_shutdown(app):
    global HTTP_SESSION

    # close aiohttp session
    if HTTP_SESSION and not HTTP_SESSION.closed:
        try:
            await HTTP_SESSION.close()
            logger.info("HTTP session closed cleanly")
        except Exception as e:
            logger.warning(f"Failed closing HTTP session: {e}")
            

#main
def main():
    logger.info("Initializing bot...")

    # ======================
    # BUILD APPLICATION
    # ======================
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(20)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(20)
        .build()
    )
    
    app.post_shutdown = post_shutdown

    # ==================================================
    # 🔥 COMMAND HANDLERS
    # ==================================================
    app.add_handler(CommandHandler("start", start_cmd), group=-1)
    app.add_handler(CommandHandler("help", help_cmd), group=-1)
    app.add_handler(CommandHandler("menu", help_cmd), group=-1)
    app.add_handler(CommandHandler("ask", ask_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("ping", ping_cmd), group=-1)

    app.add_handler(CommandHandler("speedtest", speedtest_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("ip", ip_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("whoisdomain", whoisdomain_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("domain", domain_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("dl", dl_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("stats", stats_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("tr", tr_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("gsearch", gsearch_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("asupan", asupan_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("restart", restart_cmd, block=False), group=-1)

    # AI
    app.add_handler(CommandHandler("ai", ai_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("setmodeai", setmodeai_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("groq", groq_query, block=False), group=-1)
    app.add_handler(CommandHandler("nsfw", pollinations_generate_nsfw, block=False), group=-1)

    # ==================================================
    # INLINE CALLBACKS
    # ==================================================
    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(gsearch_callback, pattern=r"^gsearch:"))
    app.add_handler(CallbackQueryHandler(dl_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(asupan_callback, pattern=r"^asupan:"))

    # ==================================================
    # 💲 DOLLAR ROUTER
    # ==================================================
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, dollar_router),
        group=1
    )

    # ======================
    # BANNER (AMAN)
    # ======================
    try:
        banner = r"""
  ____        _   _       ____        _
 |  _ \ _   _| |_| |__   |  _ \  __ _| |_
 | |_) | | | | __| '_ \  | | | |/ _` | __|
 |  _ <| |_| | |_| |_) | | |_| | (_| | |_
 |_| \_\\__,_|\__|_.__/  |____/ \__,_|\__|
"""
        print(banner)
        logger.info("Bot starting...")
    except Exception:
        logger.exception("Banner failed")

    # ======================
    # POST INIT (FINAL & AMAN)
    # ======================
    async def post_init(app):
        try:
            await app.bot.set_my_commands([
                ("start", "Check bot status"),                
                ("help", "Show help menu"),
                ("ping", "Check latency"),
                ("stats", "System statistics"),
                ("dl", "Download video"),
                ("ai", "Ask Gemini"),
                ("ask", "Ask ChatGpt"),
                ("groq", "Ask GroqAi"),
                ("gsearch", "Google search"),
                ("asupan", "Asupan 😋"),
                ("tr", "Translate text"),
                ("speedtest", "Run speed test"),
                ("restart", "Restart bot"),
            ])
        except Exception:
            pass

        # kirim asupan SEKALI pas bot nyala
        await asyncio.sleep(5)

        if not ASUPAN_STARTUP_CHAT_ID:
            logger.warning("[ASUPAN STARTUP] Chat_id is empty")
            return

        try:
            await send_asupan_once(app.bot)
            logger.warning("[ASUPAN STARTUP] Asupan sent")
        except Exception as e:
            logger.warning(f"[ASUPAN STARTUP] Failed: {e}")

    app.post_init = post_init

    # ======================
    # RUN BOT (HARUS PALING AKHIR)
    # ======================
    logger.info("Launching polling loop...")
    print("Launching... (listening for updates)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()