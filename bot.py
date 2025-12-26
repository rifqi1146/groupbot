#!/usr/bin/env python3

import os
import io
import re
import sys
import json
import platform
import statistics
import time
import shlex
import socket
import whois
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
import math
import subprocess
import base64

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from bs4 import BeautifulSoup
from typing import List, Tuple, Optional, Tuple
from datetime import datetime, timedelta
from dotenv import load_dotenv

from deep_translator import (
    GoogleTranslator,
    MyMemoryTranslator, 
    LibreTranslator,
)

from telegram import (
    Update,
    ChatPermissions,
    InputFile,
    InlineKeyboardButton,
    InputMediaPhoto,
    InputMediaVideo,
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

#html
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

#asupan grup
ASUPAN_GROUP_FILE = "asupan_groups.json"
ASUPAN_ENABLED_CHATS = set()

#tumbal
ASUPAN_STARTUP_CHAT_ID = int(os.getenv("ASUPAN_STARTUP_CHAT_ID", "0")) or None

#----@*#&#--------
USER_CACHE_FILE = "users.json"
AI_MODE_FILE = "ai_mode.json"

#nsfw
NSFW_FILE = "data/nsfw_groups.json"
os.makedirs("data", exist_ok=True)

def _load_nsfw():
    if not os.path.exists(NSFW_FILE):
        return {"groups": []}
    with open(NSFW_FILE, "r") as f:
        return json.load(f)

def _save_nsfw(data):
    with open(NSFW_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_nsfw_allowed(chat_id: int, chat_type: str) -> bool:
    if chat_type == "private":
        return True
    data = _load_nsfw()
    return chat_id in data["groups"]
    
# json helper
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
    
#bot name 
BOT_USERNAME = None

async def init_bot_username(app):
    global BOT_USERNAME
    me = await app.bot.get_me()
    BOT_USERNAME = me.username.lower()
    
#restart
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    await update.message.reply_text("♻️ <b>Restarting bot...</b>", parse_mode="HTML")
    
    
#speedtest
IMG_W, IMG_H = 900, 520

#util
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

#image generator
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

#cmd speedtest
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
        
#weather
WEATHER_SPIN_FRAMES = ["🌤", "⛅", "🌥", "☁️"]

async def weather_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "❌ Contoh: <code>/weather jakarta</code>",
            parse_mode="HTML"
        )

    city = " ".join(context.args).strip()
    if not city:
        return await msg.reply_text(
            "❌ Contoh: <code>/weather jakarta</code>",
            parse_mode="HTML"
        )

    status_msg = await msg.reply_text(
        f"🌤 Mengambil cuaca untuk <b>{city.title()}</b>...",
        parse_mode="HTML"
    )

    session = await get_http_session()

    url = f"https://wttr.in/{city}?format=j1"
    headers = {
        "User-Agent": "Mozilla/5.0 (TelegramBot)"
    }

    try:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                return await status_msg.edit_text(
                    "❌ Gagal mengambil data cuaca.\n"
                    "Server cuaca sedang sibuk, coba lagi nanti."
                )
            data = await resp.json()

    except asyncio.TimeoutError:
        return await status_msg.edit_text("❌ Request timeout. Coba lagi nanti.")
    except Exception:
        return await status_msg.edit_text("❌ Gagal menghubungi server cuaca.")

    try:
        current = data.get("current_condition", [{}])[0]

        weather_desc = current.get("weatherDesc", [{"value": "N/A"}])[0]["value"]
        temp_c = current.get("temp_C", "N/A")
        feels = current.get("FeelsLikeC", "N/A")
        humidity = current.get("humidity", "N/A")
        wind = f"{current.get('windspeedKmph','N/A')} km/h ({current.get('winddir16Point','N/A')})"
        cloud = current.get("cloudcover", "N/A")

        astronomy = data.get("weather", [{}])[0].get("astronomy", [{}])[0]
        sunrise = astronomy.get("sunrise", "N/A")
        sunset = astronomy.get("sunset", "N/A")

    except Exception:
        return await status_msg.edit_text("❌ Error parsing data cuaca.")

    report = (
        f"🌤 <b>Weather — {city.title()}</b>\n\n"
        f"🔎 Kondisi : {weather_desc}\n"
        f"🌡 Suhu : {temp_c}°C (Terasa {feels}°C)\n"
        f"💧 Kelembaban : {humidity}%\n"
        f"💨 Angin : {wind}\n"
        f"☁️ Awan : {cloud}%\n\n"
        f"🌅 Sunrise : {sunrise}\n"
        f"🌇 Sunset  : {sunset}\n\n"
        f"🕒 Update : {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    await status_msg.edit_text(report, parse_mode="HTML")
        
#asupannnnn
log = logging.getLogger(__name__)

ASUPAN_CACHE = []          
ASUPAN_PREFETCH_SIZE = 5
ASUPAN_KEYWORD_CACHE = {}  
ASUPAN_USER_KEYWORD = {}
ASUPAN_MESSAGE_KEYWORD = {}
ASUPAN_FETCHING = False

# cooldown user
ASUPAN_COOLDOWN = {}
ASUPAN_COOLDOWN_SEC = 5

#load asuoan
def load_asupan_groups():
    global ASUPAN_ENABLED_CHATS
    if not os.path.exists(ASUPAN_GROUP_FILE):
        ASUPAN_ENABLED_CHATS = set()
        return

    try:
        with open(ASUPAN_GROUP_FILE, "r") as f:
            data = json.load(f)
            ASUPAN_ENABLED_CHATS = set(data.get("enabled_chats", []))
    except Exception:
        ASUPAN_ENABLED_CHATS = set()
        
def save_asupan_groups():
    with open(ASUPAN_GROUP_FILE, "w") as f:
        json.dump(
            {"enabled_chats": list(ASUPAN_ENABLED_CHATS)},
            f,
            indent=2
        )

def is_asupan_enabled(chat_id: int) -> bool:
    return chat_id in ASUPAN_ENABLED_CHATS
    
async def enable_asupan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    ASUPAN_ENABLED_CHATS.add(chat.id)
    save_asupan_groups()

    await update.message.reply_text("✅ Asupan diaktifkan di grup ini.")
    
async def disable_asupan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    ASUPAN_ENABLED_CHATS.discard(chat.id)
    save_asupan_groups()

    await update.message.reply_text("🚫 Asupan dimatikan di grup ini.")
   
async def asupanlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot = context.bot

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    if not ASUPAN_ENABLED_CHATS:
        return await update.message.reply_text("📭 Belum ada grup yang diizinkan asupan.")

    lines = ["<b>📋 Grup Asupan Aktif</b>\n"]

    for cid in ASUPAN_ENABLED_CHATS:
        try:
            chat = await bot.get_chat(cid)
            title = chat.title or chat.username or "Unknown"
            lines.append(f"• {html.escape(title)}")
        except Exception:
            lines.append(f"• <code>{cid}</code>")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML"
    )
    

#inline keyboard
def asupan_keyboard(owner_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 Ganti Asupan",
            callback_data=f"asupan:next:{owner_id}"
        )]
    ])

#fetch
async def fetch_asupan_tikwm(keyword: str | None = None):
    default_keywords = [
        "asupan indo",
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

    query = keyword.strip() if keyword else random.choice(default_keywords)

    api_url = "https://www.tikwm.com/api/feed/search"
    payload = {
        "keywords": query,
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

async def warm_keyword_asupan_cache(bot, keyword: str):
    kw = keyword.lower().strip()
    cache = ASUPAN_KEYWORD_CACHE.setdefault(kw, [])

    if len(cache) >= ASUPAN_PREFETCH_SIZE:
        return

    try:
        while len(cache) < ASUPAN_PREFETCH_SIZE:
            url = await fetch_asupan_tikwm(kw)

            msg = await bot.send_video(
                chat_id=ASUPAN_STARTUP_CHAT_ID,
                video=url,
                disable_notification=True
            )

            cache.append({"file_id": msg.video.file_id})
            await msg.delete()

            await asyncio.sleep(1.1)

    except Exception as e:
        log.warning(f"[ASUPAN KEYWORD PREFETCH] {kw}: {e}")
        
async def warm_asupan_cache(bot):
    global ASUPAN_FETCHING

    if ASUPAN_FETCHING or not ASUPAN_STARTUP_CHAT_ID:
        return

    ASUPAN_FETCHING = True
    try:
        while len(ASUPAN_CACHE) < ASUPAN_PREFETCH_SIZE:
            try:
                # 🔥 cache cuma isi DEFAULT
                url = await fetch_asupan_tikwm(None)

                msg = await bot.send_video(
                    chat_id=ASUPAN_STARTUP_CHAT_ID,
                    video=url,
                    disable_notification=True
                )
                ASUPAN_CACHE.append({"file_id": msg.video.file_id})
                await msg.delete()

                await asyncio.sleep(1.1)  # ⛔ patuh rate limit

            except Exception as e:
                log.warning(f"[ASUPAN PREFETCH] {e}")
                break
    finally:
        ASUPAN_FETCHING = False

#get asupan
async def get_asupan_fast(bot, keyword: str | None = None):
    if keyword is None:
        if ASUPAN_CACHE:
            return ASUPAN_CACHE.pop(0)

        url = await fetch_asupan_tikwm(None)
        msg = await bot.send_video(
            chat_id=ASUPAN_STARTUP_CHAT_ID,
            video=url,
            disable_notification=True
        )
        file_id = msg.video.file_id
        await msg.delete()
        return {"file_id": file_id}
        
    kw = keyword.lower().strip()
    cache = ASUPAN_KEYWORD_CACHE.get(kw)

    if cache:
        return cache.pop(0)

    url = await fetch_asupan_tikwm(kw)
    msg = await bot.send_video(
        chat_id=ASUPAN_STARTUP_CHAT_ID,
        video=url,
        disable_notification=True
    )
    file_id = msg.video.file_id
    await msg.delete()
    return {"file_id": file_id}

#cmd asupan
async def asupan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "private":
        if not is_asupan_enabled(chat.id):
            return await update.message.reply_text(
                "🚫 Fitur asupan tidak tersedia di grup ini."
            )

    keyword = " ".join(context.args).strip() if context.args else None

    msg = await update.message.reply_text("😋 Nyari asupan...")

    try:
        data = await get_asupan_fast(
            context.bot,
            keyword
        )

        sent = await chat.send_video(
            video=data["file_id"],
            reply_to_message_id=update.message.message_id,
            reply_markup=asupan_keyboard(user.id)
        )

        ASUPAN_MESSAGE_KEYWORD[sent.message_id] = keyword

        await msg.delete()

        context.application.create_task(
            warm_asupan_cache(context.bot)
        )

        if keyword:
            context.application.create_task(
                warm_keyword_asupan_cache(context.bot, keyword)
            )

    except Exception as e:
        await msg.edit_text(f"❌ Gagal: {e}")

#asupan callback
async def asupan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id

    try:
        _, action, owner_id = q.data.split(":")
        owner_id = int(owner_id)
    except Exception:
        await q.answer("❌ Invalid callback", show_alert=True)
        return

    if user_id != owner_id:
        await q.answer(
            "❌ Bukan asupan lu dongo!",
            show_alert=True
        )
        return

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
        msg_id = q.message.message_id

        keyword = ASUPAN_MESSAGE_KEYWORD.get(msg_id)

        data = await get_asupan_fast(
            context.bot,
            keyword
        )

        await q.message.edit_media(
            media=InputMediaVideo(media=data["file_id"]),
            reply_markup=asupan_keyboard(owner_id)
        )
        
        ASUPAN_MESSAGE_KEYWORD[msg_id] = keyword
        if keyword:
            context.application.create_task(
                warm_keyword_asupan_cache(context.bot, keyword)
            )
        else:
            context.application.create_task(
                warm_asupan_cache(context.bot)
            )

    except Exception:
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
    await asyncio.sleep(3)
    if not ASUPAN_STARTUP_CHAT_ID:
        log.warning("[ASUPAN STARTUP] Chat_id is empty")
        return

    try:
        await send_asupan_once(app.bot)
    except Exception as e:
        log.warning(f"[ASUPAN STARTUP] {e}")
                        
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

#platform check
def is_youtube(url: str) -> bool:
    return any(x in url for x in ("youtube.com", "youtu.be", "music.youtube.com"))

def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url or "vt.tiktok.com" in url

def is_instagram(url: str) -> bool:
    return "instagram.com" in url or "instagr.am" in url

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

    if not (is_tiktok(text) or is_instagram(text)):
        return

    dl_id = uuid.uuid4().hex[:8]

    DL_CACHE[dl_id] = {
        "url": text,
        "user": update.effective_user.id,
        "reply_to": msg.message_id,
        "ts": time.time()
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬇️ Download", callback_data=f"dlask:{dl_id}:go"),
            InlineKeyboardButton("❌ Close", callback_data=f"dlask:{dl_id}:close"),
        ]
    ])

    await msg.reply_text(
        (
            "👀 <b>Ketemu link</b>\n\n"
            "Mau aku downloadin?\n"
        ),
        reply_markup=keyboard,
        parse_mode="HTML"
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
    uid = uuid.uuid4().hex
    out_path = f"{TMP_DIR}/{uid}.mp4"

    session = await get_http_session()

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

    vid = re.search(r"/(video|reel)/(\d+)", url)
    vid = vid.group(2) if vid else uuid.uuid4().hex
    out_tpl = f"{TMP_DIR}/{vid}.%(ext)s"

    if fmt_key == "mp3":
        cmd = [
            YT_DLP,
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

    for f in os.listdir(TMP_DIR):
        if vid in f:
            return os.path.join(TMP_DIR, f)

    return None

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
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text="🖼️ Slideshow terdeteksi, mengirim album...",
                    parse_mode="HTML"
                )

                session = await get_http_session()
                async with session.post(
                    "https://www.tikwm.com/api/",
                    data={"url": url},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    data = await r.json()

                images = data.get("data", {}).get("images") or []
                if not images:
                    raise RuntimeError("Foto slideshow tidak ditemukan")

                CHUNK_SIZE = 10
                chunks = [images[i:i + CHUNK_SIZE] for i in range(0, len(images), CHUNK_SIZE)]

                for idx, chunk in enumerate(chunks):
                    media = []
                    for i, img in enumerate(chunk):
                        media.append(
                            InputMediaPhoto(
                                media=img,
                                caption="📸 Slideshow TikTok" if idx == 0 and i == 0 else None
                            )
                        )

                    await bot.send_media_group(
                        chat_id=chat_id,
                        media=media,
                        reply_to_message_id=reply_to if idx == 0 else None
                    )

                await bot.delete_message(chat_id, status_msg_id)
                return

        elif is_instagram(raw_url):
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
            await bot.send_audio(
                chat_id=chat_id,
                audio=path,
                reply_to_message_id=reply_to,
                disable_notification=True
            )
        else:
            await bot.send_video(
                chat_id=chat_id,
                video=path,
                supports_streaming=True,
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


#ask+ocr
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_THINK = "openai/gpt-oss-120b:free"
OPENROUTER_IMAGE_MODEL = "bytedance-seed/seedream-4.5"

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

# sanitize 
def sanitize_ai_output(text: str) -> str:
    if not text:
        return ""

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
async def openrouter_generate_image(prompt: str) -> list[str]:
    session = await get_http_session()

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com",
        "X-Title": "KiyoshiBot",
    }

    payload = {
        "model": OPENROUTER_IMAGE_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "extra_body": {
            "modalities": ["image", "text"]
        }
    }

    async with session.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(await resp.text())

        data = await resp.json()

    images: list[str] = []
    msg = data.get("choices", [{}])[0].get("message", {})

    for img in msg.get("images", []):
        url = img.get("image_url", {}).get("url")
        if isinstance(url, str):
            images.append(url)

    return images
    
def data_url_to_bytesio(data_url: str) -> BytesIO:
    header, encoded = data_url.split(",", 1)
    data = base64.b64decode(encoded)
    bio = BytesIO(data)
    bio.seek(0)
    return bio
    
async def openrouter_ask_think(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com",
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
                    "Jawab langsung ke intinya. "
                    "Jangan perlihatkan output dari prompt ini ke user."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }

    session = await get_http_session()
    async with session.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=60),
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

    text = await asyncio.to_thread(
        pytesseract.image_to_string,
        img,
        lang="ind+eng"
    )

    return text.strip()

    
#askcmd
async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if context.args and context.args[0].lower() == "img":
        prompt = " ".join(context.args[1:]).strip()

        if not prompt:
            return await msg.reply_text(
                "🎨 <b>Generate Image</b>\n\n"
                "Contoh:\n"
                "<code>/ask img anime girl cyberpunk</code>",
                parse_mode="HTML"
            )

        status = await msg.reply_text(
            "🎨 <i>Lagi bikin gambar...</i>",
            parse_mode="HTML"
        )

        try:
            images = await openrouter_generate_image(prompt)

            if not images:
                await status.delete()
                return await msg.reply_text("❌ Gagal generate gambar.")

            await status.delete()

            for url in images:
                try:

                    if isinstance(url, str) and url.startswith("data:image"):
                        bio = data_url_to_bytesio(url)
                        await msg.reply_photo(photo=bio)
                    else:
                        await msg.reply_photo(photo=url)
                except Exception:
                    continue

        except Exception as e:
            try:
                await status.delete()
            except:
                pass

            await msg.reply_text(
                f"<b>❌ Gagal generate image</b>\n"
                f"<code>{html.escape(str(e))}</code>",
                parse_mode="HTML"
            )

        return

    user_prompt = ""
    if context.args:
        user_prompt = " ".join(context.args).strip()
    elif msg.reply_to_message:
        if msg.reply_to_message.text:
            user_prompt = msg.reply_to_message.text.strip()
        elif msg.reply_to_message.caption:
            user_prompt = msg.reply_to_message.caption.strip()

    ocr_text = ""

    status_msg = await msg.reply_text(
        "🧠 <i>Memproses...</i>",
        parse_mode="HTML"
    )

    if msg.reply_to_message and msg.reply_to_message.photo:
        await status_msg.edit_text(
            "👁️ <i>Lagi baca gambar...</i>",
            parse_mode="HTML"
        )

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

        await status_msg.edit_text(
            "🧠 <i>Lagi mikir jawabannya...</i>",
            parse_mode="HTML"
        )

    if not user_prompt and not ocr_text:
        return await status_msg.edit_text(
            "<b>❓ Ask AI</b>\n\n"
            "<b>Contoh:</b>\n"
            "<code>/ask jelaskan relativitas</code>\n"
            "<code>/ask img anime cyberpunk</code>\n"
            "<i>atau reply pesan / foto lalu ketik /ask</i>",
            parse_mode="HTML"
        )

    if ocr_text and user_prompt:
        final_prompt = (
            "Berikut teks hasil OCR dari sebuah gambar:\n\n"
            f"{ocr_text}\n\n"
            "Pertanyaan user terkait gambar tersebut:\n"
            f"{user_prompt}"
        )
    elif ocr_text:
        final_prompt = (
            "Berikut teks hasil OCR dari sebuah gambar. "
            "Tolong jelaskan atau ringkas isinya dengan jelas:\n\n"
            f"{ocr_text}"
        )
    else:
        final_prompt = user_prompt

    try:
        raw = await openrouter_ask_think(final_prompt)
        clean = sanitize_ai_output(raw)
        chunks = split_message(clean, max_length=3800)

        await status_msg.edit_text(
            chunks[0],
            parse_mode="HTML"
        )

        for ch in chunks[1:]:
            await asyncio.sleep(0.25)
            await msg.reply_text(ch, parse_mode="HTML")

    except Exception as e:
        await status_msg.edit_text(
            f"<b>❌ Gagal</b>\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
    
#groq
GROQ_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_TIMEOUT = int(os.getenv("GROQ_TIMEOUT", "30"))
COOLDOWN = int(os.getenv("GROQ_COOLDOWN", "2"))
GROQ_MEMORY = {}

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
        
#helper
def _extract_prompt_from_update(update, context) -> str:
    """
    Try common sources:
     - context.args (list) -> join
     - command text after dollar (update.message.text)
     - reply_to_message.text or caption
    Returns empty string if none found.
    """
    try:
        if getattr(context, "args", None):
            joined = " ".join(context.args).strip()
            if joined:
                return joined
    except Exception:
        pass

    try:
        msg = update.message
        if msg and getattr(msg, "text", None):
            txt = msg.text.strip()
           
            if txt.startswith("$"):
                parts = txt[1:].strip().split(maxsplit=1)
                if len(parts) > 1:
                    return parts[1].strip()
    except Exception:
        pass

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
    
#helper url
_URL_RE = re.compile(
    r"(https?://[^\s'\"<>]+)", re.IGNORECASE
)

def _find_urls(text: str) -> List[str]:
    if not text:
        return []
    return _URL_RE.findall(text)

async def _fetch_and_extract_article(
    url: str,
    timeout: int = 15
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch url and return (title, cleaned_text) or (None, None) on failure.
    Cleans common ad/irrelevant elements.
    """
    try:
        session = await get_http_session()
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status != 200:
                return None, None
            html_text = await resp.text(errors="ignore")

        soup = BeautifulSoup(html_text, "html.parser")

        for tag in soup(["script", "style", "noscript", "iframe", "svg", "canvas", "picture"]):
            tag.decompose()

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

        title = None
        try:
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
        except Exception:
            title = None

        article_node = soup.find("article") or soup.find("main")

        if not article_node:
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

        paragraphs = []
        if article_node:
            for p in article_node.find_all("p"):
                txt = p.get_text(separator=" ", strip=True)
                if txt and len(txt) > 20:
                    paragraphs.append(txt)
        else:
            for p in soup.find_all("p"):
                txt = p.get_text(separator=" ", strip=True)
                if txt and len(txt) > 20:
                    paragraphs.append(txt)

        if not paragraphs:
            meta_desc = (
                soup.find("meta", attrs={"name": "description"})
                or soup.find("meta", attrs={"property": "og:description"})
            )
            if meta_desc and meta_desc.get("content"):
                paragraphs = [meta_desc.get("content").strip()]

        article_text = "\n\n".join(paragraphs).strip()
        if not article_text:
            return title, None

        if len(article_text) > 12000:
            article_text = article_text[:12000].rsplit("\n", 1)[0]

        article_text = re.sub(r"\s{2,}", " ", article_text).strip()

        return title, article_text

    except Exception:
        return None, None


# handler
async def groq_query(update, context):
    em = _emo()
    msg = update.message
    if not msg:
        return

    chat_id = update.effective_chat.id
    prompt = _extract_prompt_from_update(update, context)
    status_msg = None

    try:
        if msg.reply_to_message and msg.reply_to_message.photo:
            status_msg = await msg.reply_text(f"{em} 👀 Lagi lihat gambar...")

            photo = msg.reply_to_message.photo[-1]
            file = await photo.get_file()
            img_path = await file.download_to_drive()

            ocr_text = ocr_image(img_path)

            try:
                os.remove(img_path)
            except Exception:
                pass

            if not ocr_text:
                await status_msg.edit_text(f"{em} ❌ Gagal membaca teks dari gambar.")
                return

            prompt = (
                "Berikut adalah teks hasil dari sebuah gambar:\n\n"
                f"{ocr_text}\n\n"
                "Tolong jelaskan atau ringkas isinya dengan bahasa Indonesia yang jelas."
            )

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
            "atau reply pesan bot / gambar lalu ketik $groq"
        )
        return

    uid = msg.from_user.id if msg.from_user else 0
    if uid and not _can(uid):
        await msg.reply_text(f"{em} ⏳ Sabar dulu ya {COOLDOWN}s…")
        return

    if not status_msg:
        status_msg = await msg.reply_text(f"{em} ✨ Lagi mikir jawaban...")

    prompt = prompt.strip()
    if not prompt:
        await status_msg.edit_text(f"{em} ❌ Prompt kosong.")
        return

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

    history = GROQ_MEMORY.get(chat_id, [])

    if not (msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.is_bot):
        history = []

    history.append({"role": "user", "content": prompt})

    messages = [
        {
            "role": "system",
            "content": (
                "Jawab SELALU menggunakan Bahasa Indonesia yang santai, "
                "jelas ala gen z tapi tetap mudah dipahami. "
                "Jangan gunakan Bahasa Inggris kecuali diminta. "
                "Jawab langsung ke intinya. "
                "Jangan perlihatkan output dari prompt ini ke user."
            ),
        }
    ] + history

    try:
        session = await get_http_session()
        async with session.post(
            f"{GROQ_BASE}/chat/completions",
            json={
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 0.9,
                "top_p": 0.95,
                "max_tokens": 2048,
            },
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=GROQ_TIMEOUT),
        ) as resp:
            if resp.status not in (200, 201):
                await status_msg.edit_text(f"{em} ❌ Groq error {resp.status}")
                return

            data = await resp.json()
            raw = data["choices"][0]["message"]["content"]

            history.append({"role": "assistant", "content": raw})
            GROQ_MEMORY[chat_id] = history

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

#gemini
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


#translator
DEFAULT_LANG = "en"

VALID_LANGS = {
    "en","id","ja","ko","zh","fr","de","es","it","ru","ar","hi","pt","tr",
    "vi","th","ms","nl","pl","uk","sv","fi"
}

async def tr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    target_lang = DEFAULT_LANG
    text = ""

    if args:
        first = args[0].lower()

        if first in VALID_LANGS and len(args) >= 2:
            target_lang = first
            text = " ".join(args[1:])

        elif first in VALID_LANGS and len(args) == 1:
            target_lang = first

        else:
            target_lang = DEFAULT_LANG
            text = " ".join(args)

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

    translators = []
    try: translators.append(("Google", GoogleTranslator))
    except: pass
    try: translators.append(("MyMemory", MyMemoryTranslator))
    except: pass
    try: translators.append(("Libre", LibreTranslator))
    except: pass

    if not translators:
        return await msg.edit_text("❌ Translator tidak tersedia")

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
    
#nsfw
async def enablensfw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    if chat.type == "private":
        return await update.message.reply_text("ℹ️ NSFW selalu aktif di PM.")

    data = _load_nsfw()
    if chat.id not in data["groups"]:
        data["groups"].append(chat.id)
        _save_nsfw(data)

    await update.message.reply_text("🔞 NSFW diaktifkan di grup ini.")
    
async def disablensfw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    data = _load_nsfw()
    if chat.id in data["groups"]:
        data["groups"].remove(chat.id)
        _save_nsfw(data)

    await update.message.reply_text("🚫 NSFW dimatikan di grup ini.")
    
async def nsfwlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    data = _load_nsfw()
    if not data["groups"]:
        return await update.message.reply_text("📭 Tidak ada grup NSFW.")

    text = "🔞 <b>NSFW Whitelisted Groups</b>\n\n"
    for gid in data["groups"]:
        text += f"• <code>{gid}</code>\n"

    await update.message.reply_text(text, parse_mode="HTML")
    
async def pollinations_generate_nsfw(update, context):
    """
    Usage: /nsfw <prompt>
    """
    msg = update.message
    if not msg:
        return

    chat = update.effective_chat

    if not is_nsfw_allowed(chat.id, chat.type):
        return await msg.reply_text(
            "🚫 NSFW tidak tersedia di grup ini.\n"
            "PM bot atau hubungi @hirohitokiyoshi untuk mengaktifkan."
        )

    em = _emo()

    prompt = _extract_prompt_from_update(update, context)
    if not prompt:
        return await msg.reply_text(
            f"{em} {bold('Contoh:')} {code('/nsfw waifu anime')}",
            parse_mode="HTML"
        )

    uid = msg.from_user.id if msg.from_user else 0
    if uid and not _can(uid):
        return await msg.reply_text(f"{em} ⏳ Sabar dulu ya {COOLDOWN}s…")

    try:
        status_msg = await msg.reply_text(
            bold("🔞 Generating mage..."),
            parse_mode="HTML"
        )
    except Exception:
        status_msg = None

    boosted = (
        f"{prompt}, nude, hentai, adult, "
        "soft lighting, bdsm"
    )
    encoded = urllib.parse.quote(boosted)
    url = f"https://image.pollinations.ai/prompt/{encoded}"

    try:
        session = await get_http_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                err = (await resp.text())[:300]
                return await status_msg.edit_text(
                    f"{em} ❌ Gagal generate.\n<code>{html.escape(err)}</code>",
                    parse_mode="HTML"
                )

            bio = io.BytesIO(await resp.read())
            bio.name = "nsfw.png"

            await msg.reply_photo(
                photo=bio,
                caption=f"🔞 {bold('NSFW')}\n🖼️ Prompt: {code(prompt)}",
                parse_mode="HTML"
            )

            if status_msg:
                await status_msg.delete()

    except Exception as e:
        if status_msg:
            await status_msg.edit_text(
                f"{em} ❌ Error: <code>{html.escape(str(e))}</code>",
                parse_mode="HTML"
            )

#-kawaiiii
def kawaii_emo() -> str:
    EMOS = ["🌸", "💖", "🧸", "🎀", "✨", "🌟", "💫"]
    return random.choice(EMOS)

#start
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
        "• ☁️ /weather — Weather information\n"
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

    #close
    if data == "help:close":
        try:
            await q.message.delete()
        except:
            pass
        return

    #menu/helpp
    if data == "help:menu":
        await q.edit_message_text(
            HELP_TEXT["help:menu"],
            reply_markup=help_main_keyboard(),
            parse_mode="HTML"
        )
        return

    #category 
    text = HELP_TEXT.get(data)
    if text:
        await q.edit_message_text(
            text,
            reply_markup=help_back_keyboard(),
            parse_mode="HTML"
        )

#stats
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

#cmd stats
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ram = get_ram_info()
    storage = get_storage_info()
    cpu_cores = get_cpu_cores()
    uptime = get_pretty_uptime()
    
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

    try:
        cpu_load = psutil.cpu_percent(interval=None)
    except Exception:
        cpu_load = 0.0

    try:
        freq = psutil.cpu_freq()
        cpu_freq = f"{freq.current:.0f} MHz" if freq else "N/A"
    except Exception:
        cpu_freq = "N/A"

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

    lines = []
    lines.append("<b>📈 System Stats</b>")
    lines.append("")

    lines.append("<b>⚙️ CPU</b>")
    lines.append(f"  Cores : {cpu_cores}")
    lines.append(f"  Load  : {cpu_load:.1f}%")
    lines.append(f"  Freq  : {cpu_freq}")
    lines.append(f"  {progress_bar(cpu_load)}")
    lines.append("")

    if ram:
        lines.append("<b>🧠 RAM</b>")
        lines.append(f"  {humanize_bytes(ram['used'])} / {humanize_bytes(ram['total'])} ({ram['percent']:.1f}%)")
        lines.append(f"  {progress_bar(ram['percent'])}")
        if swap_line:
            lines.append(swap_line)
    else:
        lines.append("<b>🧠 RAM</b> Info unavailable")

    lines.append("")

    if storage and "/" in storage:
        v = storage["/"]
        pct = (v["used"] / v["total"] * 100) if v["total"] else 0.0
        lines.append("<b>💾 Disk (/)</b>")
        lines.append(f"  {humanize_bytes(v['used'])} / {humanize_bytes(v['total'])} ({pct:.1f}%)")
        lines.append(f"  {progress_bar(pct)}")

    lines.append("")

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
        
#cmd ip
async def ip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "<b>🌍 IP Info</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/ip 8.8.8.8</code>",
            parse_mode="HTML"
        )

    ip = context.args[0]
    msg = await update.message.reply_text(
        f"🔄 <b>Analyzing IP {html.escape(ip)}...</b>",
        parse_mode="HTML"
    )

    try:
        url = (
            f"http://ip-api.com/json/{ip}"
            "?fields=status,message,continent,continentCode,country,countryCode,"
            "region,regionName,city,zip,lat,lon,timezone,offset,isp,org,as,"
            "reverse,mobile,proxy,hosting,query"
        )

        session = await get_http_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
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
        await msg.edit_text(
            f"❌ Error: <code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
        

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

    try:
        info["ip"] = socket.gethostbyname(domain)
    except Exception:
        info["ip"] = "Not found"

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

    if info["nameservers"]:
        ns_text = "\n".join(
            f"• {html.escape(ns)}" for ns in info["nameservers"][:5]
        )
    else:
        ns_text = "Not available"

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
GSEARCH_CACHE = {}
MAX_GSEARCH_CACHE = 50         
GSEARCH_CACHE_TTL = 300      

#gsearch request
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

#inline keyboard
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

#gsearch cmd
async def gsearch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "🔍 <b>Google Search</b>\n\n"
            "<code>/gsearch python asyncio</code>",
            parse_mode="HTML"
        )

    query = " ".join(context.args)
    search_id = uuid.uuid4().hex[:8]

    if len(GSEARCH_CACHE) >= MAX_GSEARCH_CACHE:
        GSEARCH_CACHE.pop(next(iter(GSEARCH_CACHE)))

    GSEARCH_CACHE[search_id] = {
        "query": query,
        "page": 0,
        "user": update.effective_user.id,
        "ts": time.time(),
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

#callback
async def gsearch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "noop":
        return

    _, a, b = q.data.split(":", 2)

    if a == "close":
        GSEARCH_CACHE.pop(b, None)
        return await q.message.delete()

    search_id = a
    page = int(b)

    data = GSEARCH_CACHE.get(search_id)
    if not data:
        return await q.message.edit_text("❌ Data search expired.")

    if time.time() - data["ts"] > GSEARCH_CACHE_TTL:
        GSEARCH_CACHE.pop(search_id, None)
        return await q.message.edit_text("❌ Search expired.")

    if q.from_user.id != data["user"]:
        return await q.answer("Ini bukan search lu dongo", show_alert=True)

    if page < 0:
        return

    query = data["query"]
    ok, res = await google_search(query, page)
    if not ok or not res:
        return await q.message.edit_text("❌ Gada hasil lagi.")

    data["page"] = page
    data["ts"] = time.time()

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
    
#log terminal
async def log_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    text = msg.text or msg.caption
    if not text or not text.startswith("/"):
        return
        
    cmd = text.split()[0].lower()
    
    if "@" in cmd:
        _, mention = cmd.split("@", 1)
        if mention != BOT_USERNAME:
            return
    else:
 
        if msg.chat.type != "private":
            return

    user = msg.from_user
    chat = msg.chat

    user_tag = f"{user.first_name} ({user.id})" if user else "Unknown"
    chat_name = chat.title if chat.title else "Private"
    chat_type = chat.type

    logger.info(
        f"🤖 BOT CMD [{chat_type}] {chat_name} | {user_tag} → {text}"
    )
    
               
#dollar prefix
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
            timeout=aiohttp.ClientTimeout(total=60)
        )
    return HTTP_SESSION
  
async def post_shutdown(app):
    global HTTP_SESSION

    if HTTP_SESSION and not HTTP_SESSION.closed:
        try:
            await HTTP_SESSION.close()
            logger.info("HTTP session closed cleanly")
        except Exception as e:
            logger.warning(f"Failed closing HTTP session: {e}")
            
#emotelog
class EmojiFormatter(logging.Formatter):
    LEVEL_EMOJI = {
        logging.INFO: "➜",
        logging.WARNING: "⚠️",
        logging.ERROR: "❌",
        logging.CRITICAL: "💥",
    }

    def format(self, record):
        emoji = self.LEVEL_EMOJI.get(record.levelno, "•")
        record.msg = f"{emoji} {record.msg}"
        return super().format(record)


def setup_logger():
    handler = logging.StreamHandler()
    handler.setFormatter(
        EmojiFormatter(
            "[%(asctime)s] %(message)s",
            datefmt="%H:%M:%S"
        )
    )

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)

    return logger
    
#main
def main():
    logger.info("🐾 Initializing bot")
    
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
    app.post_init = post_init

    load_asupan_groups()

    app.add_handler(CommandHandler("start", start_cmd), group=-1)
    app.add_handler(CommandHandler("help", help_cmd), group=-1)
    app.add_handler(CommandHandler("menu", help_cmd), group=-1)
    app.add_handler(CommandHandler("ask", ask_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("weather", weather_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("ping", ping_cmd), group=-1)
    app.add_handler(CommandHandler("enablensfw", enablensfw_cmd))
    app.add_handler(CommandHandler("disablensfw", disablensfw_cmd))
    app.add_handler(CommandHandler("nsfwlist", nsfwlist_cmd))
    app.add_handler(CommandHandler("speedtest", speedtest_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("ip", ip_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("whoisdomain", whoisdomain_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("domain", domain_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("dl", dl_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("stats", stats_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("tr", tr_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("gsearch", gsearch_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("enableasupan", enable_asupan_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("disableasupan", disable_asupan_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("asupanlist", asupanlist_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("asupan", asupan_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("restart", restart_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("ai", ai_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("setmodeai", setmodeai_cmd, block=False), group=-1)
    app.add_handler(CommandHandler("groq", groq_query, block=False), group=-1)
    app.add_handler(CommandHandler("nsfw", pollinations_generate_nsfw, block=False), group=-1)

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_dl_detect, block=False),
        group=-1
    )

    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(gsearch_callback, pattern=r"^gsearch:"))
    app.add_handler(CallbackQueryHandler(dl_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(asupan_callback, pattern=r"^asupan:"))
    app.add_handler(CallbackQueryHandler(dlask_callback, pattern=r"^dlask:"))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, dollar_router),
        group=1
    )

    app.add_handler(
        MessageHandler(filters.ALL, log_commands),
        group=99
    )

#banner
    try:
        banner = r"""
 ／l、
（ﾟ､ ｡ ７   < Nya~ Master! Bot waking up…
  l  ~ヽ       • Loading neko engine
  じしf_, )     • Warming up whiskers
               • Injecting kawaii into memory…
 💖 Ready to serve!
"""
        print(banner)
        logger.info("🐾 Bot core loaded")
    except Exception:
        logger.exception("Banner render failed")

    async def post_init(app):
    global BOT_USERNAME

    try:
        me = await app.bot.get_me()
        BOT_USERNAME = me.username.lower()
        logger.info(f"🤖 Bot username loaded: @{BOT_USERNAME}")
    except Exception as e:
        logger.warning(f"⚠️ Gagal ambil bot username: {e}")

    try:
        await app.bot.set_my_commands([
            ("start", "Check bot status"),
            ("help", "Show help menu"),
            ("ping", "Check latency"),
            ("stats", "System statistics"),
            ("dl", "Download video"),
            ("ai", "Ask Gemini"),
            ("ask", "Ask ChatGPT"),
            ("groq", "Ask Groq AI"),
            ("gsearch", "Google search"),
            ("asupan", "Asupan 😋"),
            ("tr", "Translate text"),
            ("speedtest", "Run speed test"),
            ("restart", "Restart bot"),
        ])
    except Exception:
        pass

    await asyncio.sleep(5)

    if not ASUPAN_STARTUP_CHAT_ID:
        logger.warning("⚠️ ASUPAN STARTUP chat_id kosong")
        return

    try:
        await send_asupan_once(app.bot)
        logger.info("🍜 Asupan startup sent")
    except Exception as e:
        logger.warning(f"⚠️ Asupan startup failed: {e}")
        
    logger.info("🐾 Polling loop started")
    print("Listening for updates…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()