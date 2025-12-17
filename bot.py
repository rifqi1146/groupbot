#!/usr/bin/env python3
# bot.py - sticker tools + blacklist + warns + stats + user cache + Gemini AI (multi-model)
# Recommended: run inside venv with python-telegram-bot==20.3

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
import requests
import aiohttp
import random
import urllib.parse
import html
import dns.resolver

from typing import List, Tuple, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv
from PIL import Image
from telegram.ext import Application
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

# optional psutil for nicer stats; if not available we'll fallback
try:
    import psutil
except Exception:
    psutil = None

#----HTML helper (safe auto-escape)----
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

# ---- setup ----
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Ambil token dari environment variable
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise SystemExit("BOT_TOKEN missing in .env")

app = Application.builder().token(TOKEN).concurrent_updates(True).build()

# ---- files & defaults ----
BL_FILE = "blacklist.json"
WARNS_FILE = "warns.json"
USER_CACHE_FILE = "users.json"
AI_MODE_FILE = "ai_mode.json"
DEFAULT_WARN_THRESHOLD = 3

# ---- image helpers ----
def resize_image_for_sticker(image: Image.Image) -> Image.Image:
    max_size = 512
    w, h = image.size
    ratio = max_size / max(w, h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    img = image.convert("RGBA").resize((new_w, new_h), Image.LANCZOS)
    new_img = Image.new("RGBA", (max_size, max_size), (0, 0, 0, 0))
    paste_x = (max_size - new_w) // 2
    paste_y = (max_size - new_h) // 2
    new_img.paste(img, (paste_x, paste_y), img)
    return new_img

def image_to_webp_bytes(image: Image.Image, quality=95) -> io.BytesIO:
    bio = io.BytesIO()
    image.save(bio, format="WEBP", quality=quality, method=6)
    bio.seek(0)
    return bio

def image_to_png_bytes(image: Image.Image) -> io.BytesIO:
    bio = io.BytesIO()
    image.save(bio, format="PNG")
    bio.seek(0)
    return bio

def make_pack_name_short(base_name: str, bot_username: str) -> str:
    s = (base_name or "pack").lower()
    s = re.sub(r'[^a-z0-9_]', '_', s)
    suffix = f"_by_{bot_username}"
    if not s.endswith(suffix):
        s = s + suffix
    return s[:64]

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

# ---- blacklist ----
def load_blacklist():
    return load_json_file(BL_FILE, {"words": [], "action": "mute", "duration": 5})
def save_blacklist(data):
    save_json_file(BL_FILE, data)
_black = load_blacklist()

# ---- ai mode (per-chat) ----
def load_ai_mode():
    return load_json_file(AI_MODE_FILE, {})
def save_ai_mode(data):
    save_json_file(AI_MODE_FILE, data)
_ai_mode = load_ai_mode()

# ---- warns storage ----
_warns = load_json_file(WARNS_FILE, {})
def save_warns():
    save_json_file(WARNS_FILE, _warns)

def get_chat_warns(chat_id):
    chat_id = str(chat_id)
    return _warns.setdefault(chat_id, {"threshold": DEFAULT_WARN_THRESHOLD, "users": {}})

def incr_warn(chat_id, user_id):
    data = get_chat_warns(chat_id)
    uid = str(user_id)
    count = data["users"].get(uid, 0) + 1
    data["users"][uid] = count
    save_warns()
    return count

def decrement_warn(chat_id, user_id):
    data = get_chat_warns(chat_id)
    uid = str(user_id)
    if uid not in data["users"]:
        return 0
    count = data["users"].get(uid, 0) - 1
    if count <= 0:
        data["users"].pop(uid, None)
        save_warns()
        return 0
    else:
        data["users"][uid] = count
        save_warns()
        return count

def reset_warn(chat_id, user_id=None):
    data = get_chat_warns(chat_id)
    if user_id is None:
        data["users"] = {}
    else:
        uid = str(user_id)
        if uid in data["users"]:
            del data["users"][uid]
    save_warns()

def get_warn_count(chat_id, user_id):
    data = get_chat_warns(chat_id)
    return data["users"].get(str(user_id), 0)

def set_threshold(chat_id, n):
    data = get_chat_warns(chat_id)
    data["threshold"] = n
    save_warns()

# ---- user cache ----
_user_cache = load_json_file(USER_CACHE_FILE, {"by_username": {}, "by_id": {}})
def save_user_cache(cache):
    save_json_file(USER_CACHE_FILE, cache)

def cache_user(user):
    if not user:
        return
    uid = user.id
    now = datetime.utcnow().isoformat()
    if getattr(user, "username", None):
        key = user.username.lower()
        _user_cache.setdefault("by_username", {})
        _user_cache["by_username"][key] = {"id": uid, "seen": now, "name": user.first_name or ""}
    _user_cache.setdefault("by_id", {})
    _user_cache["by_id"][str(uid)] = {"username": getattr(user, "username", None), "seen": now, "name": user.first_name or ""}
    save_user_cache(_user_cache)

async def user_cache_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user and not update.effective_user.is_bot:
            cache_user(update.effective_user)
    except Exception:
        logger.exception("user_cache_handler failed")

# ---- admin helper ----
async def is_user_admin(update: Update, user_id: int) -> bool:
    try:
        member = await update.effective_chat.get_member(user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def ensure_bot_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        me = await context.bot.get_me()
        member = await context.bot.get_chat_member(chat_id, me.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

# ---- resolve user helper ----
async def resolve_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE, arg: str | None = None) -> int | None:
    if update.message and update.message.reply_to_message:
        return update.message.reply_to_message.from_user.id

    if update.message and update.message.entities:
        for ent in update.message.entities:
            if ent.type == "text_mention" and ent.user:
                return ent.user.id

    if not arg:
        return None

    a = arg.strip()
    if a.startswith("@"):
        a = a[1:]

    if a.isdigit():
        try:
            return int(a)
        except Exception:
            return None

    try:
        uc = _user_cache.get("by_username", {})
        if a.lower() in uc:
            return uc[a.lower()]["id"]
    except Exception:
        logger.exception("user cache lookup failed")

    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        for adm in admins:
            u = adm.user
            if u.username and u.username.lower() == a.lower():
                cache_user(u)
                return u.id
    except Exception:
        pass

    return None

import os
import uuid
import time
import asyncio
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

TMP_DIR = "/tmp"


# =========================
# PROGRESS BAR HELPER
# =========================
def progress_bar(percent: float) -> str:
    filled = int(percent // 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty


# =========================
# CORE DOWNLOAD WITH PROGRESS
# =========================
async def _download_media_with_progress(url: str, status_msg):
    uid = str(uuid.uuid4())
    out_tpl = f"{TMP_DIR}/{uid}.%(ext)s"

    cmd = [
        "yt-dlp",
        "-f", "mp4/best",
        "--merge-output-format", "mp4",

        # TikTok no watermark
        "--extractor-args", "tiktok:watermark=0",

        "--no-playlist",
        "--newline",
        "--progress-template",
        "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",

        "-o", out_tpl,
        url
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )

    last_update = 0

    while True:
        line = await proc.stdout.readline()
        if not line:
            break

        try:
            raw = line.decode().strip()
            if "%" not in raw or "|" not in raw:
                continue

            percent_str, speed, eta = raw.split("|")
            percent = float(percent_str.replace("%", "").strip())

            now = time.time()
            if now - last_update >= 2:
                bar = progress_bar(percent)
                await status_msg.edit_text(
                    f"⬇️ <b>Mengunduh media...</b>\n\n"
                    f"<code>{bar} {percent:.1f}%</code>\n"
                    f"🚀 Speed: <b>{speed}</b>\n"
                    f"⏳ ETA: <b>{eta}</b>",
                    parse_mode="HTML"
                )
                last_update = now
        except Exception:
            pass

    await proc.wait()

    if proc.returncode != 0:
        return None

    for f in os.listdir(TMP_DIR):
        if f.startswith(uid):
            return os.path.join(TMP_DIR, f)

    return None


# =========================
# BOT COMMAND /dl
# =========================
async def dl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "<b>Usage:</b>\n"
            "<code>/dl &lt;tiktok | instagram | youtube link&gt;</code>",
            parse_mode="HTML"
        )

    url = context.args[0]

    status = await msg.reply_text(
        "⬇️ <b>Mengunduh media...</b>",
        parse_mode="HTML"
    )

    try:
        file_path = await _download_media_with_progress(url, status)
        if not file_path:
            return await status.edit_text(
                "❌ <b>Gagal mengunduh media</b>",
                parse_mode="HTML"
            )

        size_mb = os.path.getsize(file_path) / (1024 * 1024)

        if size_mb > 1900:
            await context.bot.send_document(
                msg.chat.id,
                document=open(file_path, "rb"),
                caption="✅ <b>Download selesai</b>",
                parse_mode="HTML"
            )
        else:
            await context.bot.send_video(
                msg.chat.id,
                video=open(file_path, "rb"),
                caption="✅ <b>Download selesai</b>",
                parse_mode="HTML"
            )

        os.remove(file_path)
        await status.delete()

    except Exception as e:
        await status.edit_text(
            f"❌ <b>Error:</b> <code>{e}</code>",
            parse_mode="HTML"
        )

# utils_groq_poll18.py
# ---------------- split helper (same logic) ----------------
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

# ===== SPEEDTEST (OOKLA) =====
import asyncio
import json
import time
import platform
import psutil
import statistics
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

SPEED_TITLE = "⚡️🌸 SpeedLab"
EMO = {
    "ok": "✅",
    "bad": "❌",
    "ping": "🏓",
    "download": "⬇️",
    "upload": "⬆️",
}

# ================= ENTRY =================
async def speedtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = "quick"
    if context.args:
        mode = context.args[0].lower()

    if mode in ("adv", "advanced"):
        await speedtest_advanced(update)
    else:
        await speedtest_quick(update)

# ================= CORE =================
async def _run_speedtest() -> dict:
    """
    Run Ookla speedtest and return parsed JSON
    """
    proc = await asyncio.create_subprocess_exec(
        "speedtest",
        "--accept-license",
        "--accept-gdpr",
        "--format=json",
        "--progress=no",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise Exception(stderr.decode() or "speedtest failed")

    return json.loads(stdout.decode())

# ================= QUICK =================
async def speedtest_quick(update: Update):
    msg = await update.effective_message.reply_text(
        f"⏳ {SPEED_TITLE} — Running quick test..."
    )

    try:
        start = time.perf_counter()
        data = await _run_speedtest()
        elapsed = round(time.perf_counter() - start, 2)

        ping = round(data["ping"]["latency"], 2)
        download = round(data["download"]["bandwidth"] * 8 / 1_000_000, 2)
        upload = round(data["upload"]["bandwidth"] * 8 / 1_000_000, 2)

        await msg.edit_text(
            f"{EMO['ok']} {SPEED_TITLE} — Quick Results\n\n"
            f"{EMO['ping']} Ping: <code>{ping} ms</code>\n"
            f"{EMO['download']} Download: <code>{download} Mbps</code>\n"
            f"{EMO['upload']} Upload: <code>{upload} Mbps</code>\n\n"
            f"⏱ Time: {elapsed}s\n"
            f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML",
        )

    except Exception as e:
        await msg.edit_text(
            f"{EMO['bad']} Quick speedtest failed\n<code>{e}</code>",
            parse_mode="HTML",
        )

# ================= ADVANCED =================
async def speedtest_advanced(update: Update):
    msg = await update.effective_message.reply_text(
        f"⏳ {SPEED_TITLE} — Running advanced test..."
    )

    try:
        data = await _run_speedtest()

        # system
        vm = psutil.virtual_memory()
        cpu = psutil.cpu_count(logical=True)
        ram = round(vm.available / 1024**3, 1)

        # network
        isp = data.get("isp", "N/A")
        iface = data.get("interface", {})
        ip = iface.get("externalIp", "N/A")

        # server
        srv = data.get("server", {})
        server_name = srv.get("name", "N/A")
        server_loc = f"{srv.get('location','')} {srv.get('country','')}".strip()
        server_ip = srv.get("ip", "N/A")

        # metrics
        ping = round(data["ping"]["latency"], 2)
        jitter = round(data["ping"]["jitter"], 2)
        download = round(data["download"]["bandwidth"] * 8 / 1_000_000, 2)
        upload = round(data["upload"]["bandwidth"] * 8 / 1_000_000, 2)
        packet_loss = round((data.get("packetLoss") or 0) * 100, 2)

        stability = (
            "Excellent" if jitter < 5 else
            "Good" if jitter < 15 else
            "Poor"
        )

        avg_score = round(statistics.mean([download, upload]), 1)

        await msg.edit_text(
            f"{EMO['ok']} {SPEED_TITLE} — Advanced Results\n\n"
            f"💻 System: {platform.system()} {platform.release()} • "
            f"{cpu} cores • {ram} GB available\n"
            f"🌐 ISP: {isp}\n"
            f"🌍 Public IP: <code>{ip}</code>\n\n"
            f"🛰 Server: {server_name}\n"
            f"📍 Location: {server_loc}\n"
            f"📡 Server IP: <code>{server_ip}</code>\n\n"
            f"{EMO['ping']} Ping: <code>{ping} ms</code>\n"
            f"📉 Jitter: <code>{jitter} ms</code>\n"
            f"📦 Packet Loss: <code>{packet_loss}%</code>\n"
            f"{EMO['download']} Download: <code>{download} Mbps</code>\n"
            f"{EMO['upload']} Upload: <code>{upload} Mbps</code>\n\n"
            f"📊 Stability: <b>{stability}</b>\n"
            f"📈 Overall Score: <b>{avg_score} Mbps</b>\n\n"
            f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="HTML",
        )

    except Exception as e:
        await msg.edit_text(
            f"{EMO['bad']} Advanced speedtest failed\n<code>{e}</code>",
            parse_mode="HTML",
        )

# ===== END SPEEDTEST =====
                                       
#ping
async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = time.perf_counter()

    # kirim pesan awal
    msg = await update.message.reply_text("🏓 <b>Pinging...</b>", parse_mode="HTML")

    end = time.perf_counter()
    ms = int((end - start) * 1000)

    if ms < 150:
        emo = "⚡"
    elif ms < 500:
        emo = "🔥"
    else:
        emo = "🐌"

    await msg.edit_text(
        f"{emo} <b>Pong!</b>\n"
        f"⏱️ <b>Latency:</b> <code>{ms} ms</code>",
        parse_mode="HTML"
    )
    
# ---- GROQ + Pollinations handlers (for python-telegram-bot) ----
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

    # try by paragraphs
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
                # para too long -> split by sentences
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

    # final sanity: ensure nothing > max_length
    final = []
    for c in chunks:
        if len(c) <= max_length:
            final.append(c)
        else:
            for i in range(0, len(c), max_length):
                final.append(c[i:i+max_length])
    return final

# ---- helper: extract prompt safely from update/context ----
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

# ---- GROQ handler (async for python-telegram-bot) ----
# ---- helper: find urls in text ----
import re
from typing import Optional, Tuple, List
from bs4 import BeautifulSoup  # pip install beautifulsoup4

_URL_RE = re.compile(
    r"(https?://[^\s'\"<>]+)", re.IGNORECASE
)

def _find_urls(text: str) -> List[str]:
    if not text:
        return []
    return _URL_RE.findall(text)


# ---- helper: fetch + extract main article text (async) ----
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


# ---- GROQ handler (async for python-telegram-bot) patched with URL fetching + ad cleaning ----
async def groq_query(update, context):
    """
    $groq <prompt>  OR  reply to message with $groq
    If prompt contains a URL, this handler will try to fetch and extract the article,
    auto-clean common ad elements, then ask GROQ to summarize the extracted article.
    If fetch/extract fails, falls back to sending the original prompt to GROQ.
    """
    em = _emo()
    msg = update.message
    if not msg:
        return

    # get prompt from context.args / text after command / reply message
    prompt = _extract_prompt_from_update(update, context)

    # If no prompt -> show help/usage
    if not prompt:
        help_txt = (
            f"{em} {bold('Usage:')}\n"
            f"{code('$groq <pertanyaan atau perintah>')}\n\n"
            "Contoh:\n"
            "$groq ringkaskan isi dari https://example.com/news/12345\n"
            "atau reply ke pesan artikel lalu ketik: $groq\n"
        )
        try:
            await msg.reply_text(help_txt, quote=True, parse_mode='HTML')
        except Exception:
            try:
                await msg.reply_text("Usage: $groq <prompt> or reply to a message with $groq")
            except:
                pass
        return

    # rate limit per-user
    uid = msg.from_user.id if msg.from_user else 0
    if uid and not _can(uid):
        await msg.reply_text(f"{em} ⏳ Sabar dulu ya {COOLDOWN}s…")
        return

    # create thinking placeholder (editable)
    thinking = None
    try:
        thinking = await msg.reply_text(f"{em} ✨ Lagi mikir jawaban…", quote=True)
    except Exception:
        thinking = None

    # sanitize prompt
    if not isinstance(prompt, str):
        prompt = str(prompt)
    prompt = prompt.strip()
    if not prompt:
        if thinking:
            await thinking.edit_text(f"{em} ❌ Prompt kosong.")
        else:
            await msg.reply_text(f"{em} ❌ Prompt kosong.")
        return

    # detect URL(s) in prompt - prefer the first
    urls = _find_urls(prompt)
    used_article = False
    article_title = None
    article_text = None
    if urls:
        first_url = urls[0]
        # quick guard: don't follow non-http(s)
        if first_url.lower().startswith("http"):
            if thinking:
                await thinking.edit_text(f"{em} 🔎 Sedang ambil dan bersihin isi halaman: {first_url}")
            # attempt fetch + extract (with timeout)
            title, text = await _fetch_and_extract_article(first_url)
            if text:
                used_article = True
                article_title = title
                article_text = text
            else:
                # failed to extract — keep going but inform user
                if thinking:
                    await thinking.edit_text(f"{em} ⚠️ Gagal ekstrak artikel dari URL. Mengirim prompt asli ke GROQ.")
                else:
                    await msg.reply_text(f"{em} ⚠️ Gagal ekstrak artikel dari URL. Mengirim prompt asli ke GROQ.")

    # build final prompt
    if used_article and article_text:
        # prepare clean prompt (no style instructions)
        article_source = first_url
        hdr = f"Artikel sumber: {article_source}"
        if article_title:
            hdr = f"{hdr}\nJudul: {article_title}"
        final_user = (
            f"{hdr}\n\n"
            f"--- BEGIN ARTICLE ---\n"
            f"{article_text}\n"
            f"--- END ARTICLE ---\n\n"
            "Tolong buat ringkasan yang rapi dan mudah dipahami dalam bahasa Indonesia:\n"
            "- Sorot poin-poin utama (what, when, where, who, how, numbers jika ada).\n"
            "- Sertakan satu kalimat kesimpulan singkat.\n"
            "- Jangan sertakan HTML, metadata, atau teks iklan.\n"
            "- Output: bullet points lalu satu baris kesimpulan."
        )
        send_prompt = final_user
    else:
        send_prompt = prompt  # no URL or failed extraction — send raw prompt

    # build payload (leave basic settings unchanged)
    url = f"{GROQ_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "user", "content": send_prompt}
        ],
        "temperature": 0.85,
        "top_p": 0.95,
        "max_tokens": 2048,
    }

    # call GROQ
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload, headers=headers, timeout=GROQ_TIMEOUT) as resp:
                text = await resp.text()
                if resp.status not in (200, 201):
                    short = text[:800]
                    if thinking:
                        await thinking.edit_text(f"{em} ❌ Groq error ({resp.status}):\n`{short}`")
                    else:
                        await msg.reply_text(f"{em} ❌ Groq error ({resp.status}):\n`{short}`")
                    return

                try:
                    data = json.loads(text)
                except Exception:
                    data = None

                # extract reply safely
                reply = None
                try:
                    if data and "choices" in data:
                        reply = data["choices"][0]["message"]["content"]
                except Exception:
                    reply = None

                if not reply:
                    reply = (data.get("output_text") if data and isinstance(data, dict) else None) or text or "Ga ada output dari Groq."

                reply = str(reply).strip()
                chunks = split_message(reply, max_length=4000)

                # edit first msg (thinking) or reply with first chunk
                if thinking:
                    await thinking.edit_text(f"{em} {chunks[0]}")
                else:
                    await msg.reply_text(f"{em} {chunks[0]}")

                # send rest as new messages
                for ch in chunks[1:]:
                    await msg.reply_text(ch)
                return

    except asyncio.TimeoutError:
        if thinking:
            await thinking.edit_text(f"{em} ❌ Timeout nyambung Groq.")
        else:
            await msg.reply_text(f"{em} ❌ Timeout nyambung Groq.")
        return
    except Exception as e:
        short = str(e)
        if len(short) > 800:
            short = short[:800] + "..."
        if thinking:
            await thinking.edit_text(f"{em} ❌ Error: {short}")
        else:
            await msg.reply_text(f"{em} ❌ Error: {short}")
        logger.exception("groq_query failed")
        return

# ---- Pollinations NSFW image generator (async) ----
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
        "Bot siap: sticker tools, blacklist, warns, stats, AI.\n"
        "Ketik /help buat lihat menu."
    )
    await update.message.reply_text(text)

# moderation commands (ban/mute/unmute) and warn/unwarn/warns functions:
async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await ensure_bot_admin(context, chat_id):
        return await update.message.reply_text("Saya perlu jadi admin dengan izin ban.")
    arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, arg)
    if not target_id:
        return await update.message.reply_text("Gagal resolve user. Gunakan reply / user_id / @username.")
    try:
        await context.bot.ban_chat_member(chat_id, target_id)
        await update.message.reply_text(f"User {target_id} diban.")
    except Exception as e:
        logger.exception("ban failed")
        await update.message.reply_text(f"Gagal ban: {e}")

async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await ensure_bot_admin(context, chat_id):
        return await update.message.reply_text("Saya perlu jadi admin dengan izin restrict.")
    arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, arg)
    if not target_id:
        return await update.message.reply_text("Gagal resolve user. Gunakan reply / user_id / @username.")
    perms = ChatPermissions(can_send_messages=False)
    try:
        await context.bot.restrict_chat_member(chat_id, target_id, perms)
        await update.message.reply_text(f"User {target_id} dimute.")
    except Exception as e:
        logger.exception("mute failed")
        await update.message.reply_text(f"Gagal mute: {e}")

async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await ensure_bot_admin(context, chat_id):
        return await update.message.reply_text("Saya perlu jadi admin dengan izin restrict.")
    arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, arg)
    if not target_id:
        return await update.message.reply_text("Gagal resolve user. Gunakan reply / user_id / @username.")
    perms = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )
    try:
        await context.bot.restrict_chat_member(chat_id, target_id, perms)
        await update.message.reply_text(f"User {target_id} diunmute.")
    except Exception as e:
        logger.exception("unmute failed")
        await update.message.reply_text(f"Gagal unmute: {e}")

async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, arg)
    if not target_id:
        return await update.message.reply_text("Gagal resolve user. Gunakan reply / user_id / @username.")
    chat_id = update.effective_chat.id
    try:
        new_warn = incr_warn(chat_id, target_id)
        threshold = get_chat_warns(chat_id).get("threshold", DEFAULT_WARN_THRESHOLD)
        await update.message.reply_text(f"⚠️ Warn ditambahkan untuk {target_id}. ({new_warn}/{threshold})")
        if new_warn >= threshold:
            try:
                await context.bot.ban_chat_member(chat_id, target_id)
                await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=False)
                await update.message.reply_text(f"User {target_id} reached warn threshold ({threshold}) → kicked.")
            except Exception:
                logger.exception("kick on threshold failed")
                await update.message.reply_text("Gagal kick user pada threshold.")
            reset_warn(chat_id, target_id)
    except Exception as e:
        logger.exception("warn_cmd failed")
        await update.message.reply_text(f"Gagal menambahkan warn: {e}")

async def unwarn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, arg)
    if not target_id:
        return await update.message.reply_text("Gagal resolve user. Gunakan reply / user_id / @username.")
    chat_id = update.effective_chat.id
    try:
        new_count = decrement_warn(chat_id, target_id)
        if new_count == 0:
            await update.message.reply_text(f"Warn dihapus untuk {target_id}. Saat ini 0 warn.")
        else:
            await update.message.reply_text(f"Warn dikurangi untuk {target_id}. Sisa: {new_count}.")
    except Exception as e:
        logger.exception("unwarn_cmd failed")
        await update.message.reply_text(f"Gagal mengurangi warn: {e}")

async def warns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, arg)
    if not target_id:
        return await update.message.reply_text("Masukkan user valid (reply / user_id / @username).")
    count = get_warn_count(update.effective_chat.id, target_id)
    await update.message.reply_text(f"User {target_id} has {count} warn(s).")

async def resetwarn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, arg)
    if not target_id:
        return await update.message.reply_text("Masukkan user valid (reply / @username / id).")
    reset_warn(update.effective_chat.id, target_id)
    await update.message.reply_text(f"Warns reset for {target_id}.")

async def setwarnthreshold_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /setwarnthreshold <angka>")
    try:
        n = max(1, int(context.args[0]))
    except Exception:
        return await update.message.reply_text("Masukkan angka integer.")
    set_threshold(update.effective_chat.id, n)
    await update.message.reply_text(f"Warn threshold set to {n} for this chat.")

# ---- interactive help menu ----
def help_keyboard():
    kb = [
        [
            InlineKeyboardButton("✨ Features", callback_data="help:features"),
            InlineKeyboardButton("🔧 Admin", callback_data="help:admin"),
        ],
        [
            InlineKeyboardButton("🚫 Blacklist", callback_data="help:blacklist"),
            InlineKeyboardButton("⚠️ Warns", callback_data="help:warns"),
        ],
        [
            InlineKeyboardButton("👤 Creator", callback_data="help:creator"),
            InlineKeyboardButton("🔙 Back", callback_data="help:back"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="help:close"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


# ===========================
# MAIN HELP COMMAND
# ===========================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 <b>Help Menu</b>\n"
        "Pilih kategori di bawah ya✨\n"
    )
    await update.message.reply_text(text, reply_markup=help_keyboard(), parse_mode="HTML")


# ===========================
# HELP CALLBACK
# ===========================
async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data or ""

    def esc(s: str) -> str:
        return html.escape(s or "")

    # ===========================
    # CLOSE BUTTON
    # ===========================
    if data == "help:close":
        try:
            await query.message.delete()
        except:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except:
                pass
        return

    # ===========================
    # FEATURES
    # ===========================
    if data == "help:features":
        text = (
    "✨ " + bold("Features") + "\n"
    "• 🏓 /ping — Cek latency bot\n"
    "• ⬇️ /dl — Download video TikTok / Instagram / YouTube\n"
    "• ⚡ /speedtest — Cek kecepatan internet bot (quick / adv)\n\n"

            

            "🤖 " + bold("AI & Search") + "\n"
            "• /ai — Tanya AI (default model)\n"
            "• /openai — Tanya OpenAI\n"
            "• /groq — Tanya Groq AI\n"
            "• /deepseek — Tanya DeepSeek\n"
            "• /ai flash|pro|lite — Paksa model AI\n"
            "• /setmodeai — Set default model AI\n\n"

            "🧠 " + bold("Utilities") + "\n"
            "• /whois @username — Info user cache\n"
            "• /stats — Info sistem (CPU / RAM / Storage)\n"
            "• /info — Info user Telegram\n\n"

            "🔞 " + bold("NSFW") + "\n"
            "• /nsfw — Generate gambar NSFW"
        )

        await query.edit_message_text(
            text,
            reply_markup=help_keyboard(),
            parse_mode="HTML"
        )
        return

    # ===========================
    # ADMIN
    # ===========================
    if data == "help:admin":
        text = (
            "🔧 " + bold("Admin Tools") + "\n\n"
            "• /ban — Ban user (reply / id)\n"
            "• /mute — Mute user\n"
            "• /unmute — Unmute user\n"
            "• /warn — Tambah warn\n"
            "• /unwarn — Kurangi warn\n"
            "• /warns — Lihat total warn\n"
            "• /resetwarn — Reset warn\n"
            "• /setwarnthreshold — Atur batas warn"
        )
        await query.edit_message_text(text, reply_markup=help_keyboard(), parse_mode="HTML")
        return

    # ===========================
    # BLACKLIST
    # ===========================
    if data == "help:blacklist":
        bl = load_blacklist()
        words = bl.get("words", [])
        sample = ", ".join(words[:12]) if words else "Belum ada"
        sample_esc = esc(sample)

        text = (
            "🚫 " + bold("Blacklist System") + "\n\n"
            f"<i>Kata terdaftar:</i> {sample_esc}\n\n"
            f"• {code('/addbad <kata>')} — Tambah kata\n"
            f"• {code('/rmbad <kata>')} — Hapus kata\n"
            f"• {code('/listbad')} — Lihat semua\n"
            f"• {code('/setaction mute|ban')} — Aksi\n"
            f"• {code('/setduration <menit>')} — Durasi"
        )
        await query.edit_message_text(text, reply_markup=help_keyboard(), parse_mode="HTML")
        return

    # ===========================
    # WARNS
    # ===========================
    if data == "help:warns":
        text = (
            "⚠️ " + bold("Warn System") + "\n\n"
            "• /warn — Tambah warn\n"
            "• /unwarn — Kurangi warn\n"
            "• /warns — Cek warn\n"
            "• /resetwarn — Reset warn\n"
            "• /setwarnthreshold — Set batas"
        )
        await query.edit_message_text(text, reply_markup=help_keyboard(), parse_mode="HTML")
        return

    # ===========================
    # CREATOR
    # ===========================
    if data == "help:creator":
        text = (
            "👤 " + bold("Creator") + "\n\n"
            "Bot dibuat oleh ꦠꦾꦎꦴꦭꦶꦪ\n"
            f"Contact: {code('@hirohitokiyoshi')}\n\n"
            "<i>Promote bot sebagai admin untuk fitur penuh.</i>"
        )
        await query.edit_message_text(text, reply_markup=help_keyboard(), parse_mode="HTML")
        return

    # ===========================
    # CREATOR
    # ===========================
    if data == "help:creator":
        text = (
            "👤 " + bold("Creator") + "\n"
            "Bot ini dibuat sama ꦠꦾꦎꦴꦭꦶꦪ\n\n"
            f"Contact: {code('@hirohitokiyoshi')}\n\n"
            "Tip: Promote bot sebagai admin untuk fitur penuh."
        )
        await query.edit_message_text(text, reply_markup=help_keyboard(), parse_mode="HTML")
        return

    # ===========================
    # BACK
    # ===========================
    if data == "help:back":
        text = (
            "📋 " + bold("Help Menu") + "\n"
            "Pilih kategori di bawah untuk detail."
        )
        await query.edit_message_text(text, reply_markup=help_keyboard(), parse_mode="HTML")
        return

# ---- blacklist helpers & handler ----
def build_blacklist_regex(words):
    if not words:
        return None
    escaped = [re.escape(w) for w in words if w]
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    return re.compile(pattern, flags=re.IGNORECASE)

async def do_temporary_unrestrict(chat_id, user_id, duration_minutes, context):
    await asyncio.sleep(duration_minutes * 60)
    try:
        perms = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
        )
        await context.bot.restrict_chat_member(chat_id, user_id, permissions=perms)
    except Exception:
        return

async def _blacklist_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if update.effective_user.is_bot:
        return
    uid = update.effective_user.id
    if await is_user_admin(update, uid):
        return
    data = load_blacklist()
    regex = build_blacklist_regex(data.get("words", []))
    if not regex:
        return
    text = update.message.text
    if not regex.search(text):
        return
    chat_id = update.effective_chat.id
    action = data.get("action", "mute")
    duration = int(data.get("duration", 5))
    try:
        new_warn = incr_warn(chat_id, uid)
        threshold = get_chat_warns(chat_id).get("threshold", DEFAULT_WARN_THRESHOLD)
        await update.message.reply_text(f"⚠️ Kata terlarang terdeteksi. Warn {new_warn}/{threshold}.")
        if new_warn >= threshold:
            try:
                await context.bot.ban_chat_member(chat_id, uid)
                await context.bot.unban_chat_member(chat_id, uid, only_if_banned=False)
                await update.message.reply_text(f"User reached warn threshold ({threshold}) → kicked.")
            except Exception:
                logger.exception("kick on threshold failed")
                await update.message.reply_text("Gagal kick user pada threshold.")
            reset_warn(chat_id, uid)
            return
        if action == "mute":
            perms = ChatPermissions(can_send_messages=False)
            until = datetime.utcnow() + timedelta(minutes=duration)
            await context.bot.restrict_chat_member(chat_id, uid, permissions=perms, until_date=until)
            await update.message.reply_text(f"User muted for {duration} minute(s) due to prohibited word.")
            asyncio.create_task(do_temporary_unrestrict(chat_id, uid, duration, context))
        else:
            until = datetime.utcnow() + timedelta(minutes=duration)
            await context.bot.ban_chat_member(chat_id, uid, until_date=until)
            await update.message.reply_text(f"User temporarily banned for {duration} minute(s) due to prohibited word.")
            async def unban_later():
                await asyncio.sleep(duration * 60)
                try:
                    await context.bot.unban_chat_member(chat_id, uid, only_if_banned=True)
                except Exception:
                    pass
            asyncio.create_task(unban_later())
    except Exception as e:
        logger.exception("blacklist action failed")
        await update.message.reply_text(f"Gagal melakukan tindakan: {e}")

# ---- blacklist admin commands ----
async def addbad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /addbad kata")
    word = context.args[0].strip().lower()
    if word in _black["words"]:
        return await update.message.reply_text("Kata sudah ada di blacklist.")
    _black["words"].append(word)
    save_blacklist(_black)
    await update.message.reply_text(f"Ditambahkan ke blacklist: {word}")

async def rmbad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /rmbad kata")
    word = context.args[0].strip().lower()
    try:
        _black["words"].remove(word)
        save_blacklist(_black)
        await update.message.reply_text(f"Dihapus dari blacklist: {word}")
    except ValueError:
        await update.message.reply_text("Kata tidak ditemukan.")

async def listbad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    words = _black.get("words", [])
    if not words:
        return await update.message.reply_text("Belum ada kata di blacklist.")
    await update.message.reply_text("Blacklist:\n" + ", ".join(words))

async def setaction_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /setaction mute|ban")
    action = context.args[0].lower()
    if action not in ("mute", "ban"):
        return await update.message.reply_text("Action must be 'mute' or 'ban'.")
    _black["action"] = action
    save_blacklist(_black)
    await update.message.reply_text(f"Action set to: {action}")

async def setduration_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /setduration <minutes>")
    try:
        mins = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Masukkan angka menit.")
    _black["duration"] = max(1, mins)
    save_blacklist(_black)
    await update.message.reply_text(f"Duration set to {_black['duration']} minutes")

# --- Helper & stats (Style B + progress bars) ---
import os, platform, shutil, time, html
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
    ram = get_ram_info()
    storage = get_storage_info()
    cpu_cores = get_cpu_cores()
    kernel = get_kernel_version()
    os_name = get_os_name()
    python_ver = get_python_version()
    uptime = get_pretty_uptime()

    lines = []
    lines.append("<b>📈 System Stats</b>")
    lines.append("")  # blank

    # RAM
    if ram:
        ram_used = humanize_bytes(ram["used"])
        ram_total = humanize_bytes(ram["total"])
        ram_pct = ram["percent"]
        lines.append("<b>🧠 RAM</b>")
        lines.append(f"  {ram_used} / {ram_total}  ({ram_pct:.1f}%)")
        lines.append(f"  {progress_bar(ram_pct)}")
    else:
        lines.append("<b>🧠 RAM</b>  Info unavailable")

    lines.append("")  # blank

    # Storage (prefer order)
    if storage:
        prefer = ["/data", "/sdcard", "/storage", "/"]
        lines.append("<b>💾 Storage</b>")
        shown = set()
        for m in prefer:
            if m in storage:
                v = storage[m]
                pct = (v["used"] / v["total"] * 100) if v["total"] else 0.0
                lines.append(f"  {html.escape(m)}")
                lines.append(f"    {humanize_bytes(v['used'])} / {humanize_bytes(v['total'])}  ({pct:.1f}%)")
                lines.append(f"    {progress_bar(pct)}")
                shown.add(m)
        for mount, v in storage.items():
            if mount in shown:
                continue
            pct = (v["used"] / v["total"] * 100) if v["total"] else 0.0
            lines.append(f"  {html.escape(mount)}")
            lines.append(f"    {humanize_bytes(v['used'])} / {humanize_bytes(v['total'])}  ({pct:.1f}%)")
            lines.append(f"    {progress_bar(pct)}")
    else:
        lines.append("<b>💾 Storage</b>  Info unavailable")

    lines.append("")  # blank

    # CPU / kernel / python / uptime
    lines.append(f"<b>⚙️ CPU Cores</b>: {cpu_cores}")
    lines.append(f"<b>🐧 Kernel</b>: {html.escape(kernel)}")
    lines.append(f"<b>🖥️ OS</b>: {html.escape(os_name)}")
    lines.append(f"<b>🐍 Python</b>: {html.escape(python_ver)}")
    lines.append(f"<b>⏱️ Uptime</b>: {html.escape(uptime)}")

    out = "\n".join(lines)
    try:
        await update.message.reply_text(out, parse_mode='HTML')
    except Exception:
        await update.message.reply_text(out)

# --- Konfigurasi API Hugging Face ---
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
HF_MODEL_DEFAULT = os.getenv("HF_MODEL_DEFAULT", "openai/gpt-oss-120b:fastest")
HF_MODEL_DEEPSEEK = os.getenv("HF_MODEL_DEEPSEEK", "deepseek-ai/DeepSeek-R1:fastest")

if not HF_API_TOKEN:
    raise ValueError("HF_API_TOKEN environment variable is missing!")

# --- Fungsi Request ke Hugging Face Router (v1/chat/completions) ---
def ask_ai_hf(prompt: str, model_name: str) -> (bool, str):
    if not HF_API_TOKEN:
        return False, "HF_API_TOKEN environment variable is missing!"

    if not prompt:
        return False, "Tidak ada prompt."

    url = "https://router.huggingface.co/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "stream": False,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict) and 'choices' in result and len(result['choices']) > 0:
            message_content = result['choices'][0].get('message', {}).get('content', '')
            if message_content:
                return True, message_content.strip()
            else:
                 return True, f"Respons dari Hugging Face (chat) tidak ditemukan konten: {result}"
        else:
             return True, f"Respons dari Hugging Face (chat) tidak sesuai format: {result}"
    except requests.exceptions.HTTPError as he:
        logger.error(f"HTTP Error request ke Hugging Face: {he}")
        if he.response is not None:
            error_detail = he.response.text
            logger.error(f"Response Body: {error_detail}")
            status_code = he.response.status_code
            if status_code == 401:
                return False, f"Error otentikasi ke Hugging Face (401 Unauthorized). Cek token dan kuota API lu. Error: {error_detail}"
            elif status_code == 404:
                 return False, f"Model '{model_name}' tidak ditemukan atau tidak dapat diakses melalui endpoint chat ini. Error: {error_detail}"
            elif status_code == 503:
                return False, "Model sedang overload atau maintenance. Coba lagi nanti."
            elif status_code == 422:
                return False, f"Permintaan ke Hugging Face tidak valid (mungkin model tidak support chat): {error_detail}"
            elif status_code == 429:
                return False, "Kuota request Hugging Face habis atau terlalu cepat. Tunggu sebentar."
            else:
                return False, f"Error HTTP {status_code} dari Hugging Face: {error_detail}"
        return False, f"HTTP Error saat menghubungi Hugging Face: {he}"
    except requests.exceptions.RequestException as e:
        logger.error(f"Request Exception saat request ke Hugging Face: {e}")
        return False, f"Error request ke Hugging Face: {e}"
    except Exception as e:
        logger.error(f"Error tak terduga dari Hugging Face: {e}")
        return False, f"Error tak terduga: {e}"

# --- Handler Command OpenAI (via HF Router) ---
async def ai_openai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the '/openai' command to query a default Hugging Face model (e.g., OSS).
    Splits response if it's too long.
    For a regular bot (python-telegram-bot).
    """
    chat_id = str(update.effective_chat.id)
    prompt = ""

    if context.args:
        prompt = " ".join(context.args)
    elif update.message.reply_to_message:
        prompt = update.message.reply_to_message.text or ""

    if not prompt:
        return await update.message.reply_text(
            f"Model default chat: {HF_MODEL_DEFAULT}\n"
            "Contoh:\n"
            "/openai apa itu machine learning?\n"
            "/openai jelaskan konsep AI"
        )

    loading = await update.message.reply_text("⏳ Memproses permintaan ke OpenAI...")

    ok, answer = ask_ai_hf(prompt, HF_MODEL_DEFAULT)

    if not ok:
        try:
            await loading.edit_text(f"❗ Error: {answer}")
        except Exception:
            await update.message.reply_text(f"❗ Error: {answer}")
        return

    message_parts = split_message(answer)

    for i, part in enumerate(message_parts):
        if i == 0:
            header = f"💡 Jawaban (OpenAI)"
            final = f"{header}\n\n{part}"
            try:
                await loading.edit_text(final[:4000])
            except Exception:
                await update.message.reply_text(final[:4000])
        else:
            await update.message.reply_text(part[:4000])

# --- Handler Command DeepSeek (via HF Router) ---
async def ai_deepseek_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prompt = ""

    if context.args:
        prompt = " ".join(context.args)
    elif update.message.reply_to_message:
        prompt = update.message.reply_to_message.text or ""

    if not prompt:
        return await update.message.reply_text(
            f"Model default chat: {HF_MODEL_DEEPSEEK}\n"
            "Contoh:\n"
            "/deepseek apa itu machine learning?\n"
            "/deepseek jelaskan konsep AI"
        )

    loading = await update.message.reply_text("⏳ Memproses permintaan ke DeepSeek...")

    ok, answer = ask_ai_hf(prompt, HF_MODEL_DEEPSEEK)

    if not ok:
        try:
            await loading.edit_text(f"❗ Error: {answer}")
        except Exception:
            await update.message.reply_text(f"❗ Error: {answer}")
        return

    message_parts = split_message(answer)

    for i, part in enumerate(message_parts):
        if i == 0:
            header = f"💡 Jawaban (DeepSeek)"
            final = f"{header}\n\n{part}"
            try:
                await loading.edit_text(final[:4000])
            except Exception:
                await update.message.reply_text(final[:4000])
        else:
            await update.message.reply_text(part[:4000])

# ---- GEMINI ONLY (multi-model) ----
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODELS = {
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
    "lite": "gemini-2.0-flash-lite-001",
}

def ask_ai_gemini(prompt: str, model: str = "gemini-2.5-flash") -> (bool, str):
    if not GEMINI_API_KEY:
        return False, "API key Gemini belum diset. Set GEMINI_API_KEY di .env"

    if not prompt:
        return False, "Tidak ada prompt."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return True, "Model merespon tapi tanpa candidates."
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return True, parts[0].get("text", "").strip()
        return True, json.dumps(candidates[0], ensure_ascii=False)
    except requests.exceptions.HTTPError:
        try:
            return False, f"Gagal memanggil Gemini: {r.status_code} {r.text}"
        except Exception:
            return False, "Gagal memanggil Gemini (HTTP error)."
    except Exception as e:
        return False, f"Gagal memanggil Gemini: {e}"

# ---- set default model per chat ----
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

# ---- AI command ----
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

    ok, answer = ask_ai_gemini(prompt, model=model_name)
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

# ---- extra user commands ----
async def syncadmins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_user_admin(update, update.effective_user.id):
        return await update.message.reply_text("Hanya admin.")
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        count = 0
        for adm in admins:
            cache_user(adm.user)
            count += 1
        await update.message.reply_text(f"✅ Sukses sinkron {count} admin ke cache.")
    except Exception as e:
        logger.exception("syncadmins failed")
        await update.message.reply_text(f"Gagal sinkron admins: {e}")

async def whois_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /whois @username")
    a = context.args[0].lstrip("@").lower()
    uc = _user_cache.get("by_username", {})
    if a in uc:
        info = uc[a]
        await update.message.reply_text(
            f"🔎 Ditemukan di cache\n"
            f"Username : @{a}\n"
            f"User ID  : {info['id']}\n"
            f"Nama     : {info.get('name')}\n"
            f"Seen     : {info.get('seen')}"
        )
    else:
        await update.message.reply_text("Gak ada data username itu di cache. Coba /syncadmins atau tunggu orang itu ngomong dulu.")

async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Text-only user info (no profile photo).
    Sends placeholder "Mengambil info..." then edits it into full info (HTML).
    """
    try:
        msg = update.message
        if not msg:
            return

        # placeholder
        try:
            placeholder = await msg.reply_text("🔎 Mengambil info user...", quote=True)
        except Exception:
            placeholder = None

        # resolve target user
        target = None
        if msg.reply_to_message:
            target = msg.reply_to_message.from_user
        elif context.args:
            arg = context.args[0]
            uid = None
            if arg.startswith("@"):
                arg = arg[1:]
            if arg.isdigit():
                uid = int(arg)
            else:
                uc = _user_cache.get("by_username", {})
                if arg.lower() in uc:
                    uid = uc[arg.lower()]["id"]
            if uid:
                try:
                    member = await context.bot.get_chat_member(update.effective_chat.id, uid)
                    target = member.user
                except Exception:
                    try:
                        # fallback: get_chat (may return user-like chat)
                        profile = await context.bot.get_chat(uid)
                        # profile could be a Chat object; construct a minimal user-like object if possible
                        class _U: pass
                        u = _U()
                        u.id = profile.id
                        u.first_name = getattr(profile, "first_name", None) or getattr(profile, "title", None) or ""
                        u.last_name = getattr(profile, "last_name", None) or ""
                        u.username = getattr(profile, "username", None)
                        u.is_bot = False
                        target = u
                    except Exception:
                        target = None

        if not target and update.effective_user:
            target = update.effective_user

        if not target:
            if placeholder:
                await placeholder.edit_text("⚠️ Gagal resolve user. Reply ke pesan atau berikan @username / id.")
            else:
                await msg.reply_text("⚠️ Gagal resolve user. Reply ke pesan atau berikan @username / id.")
            return

        # cache user for future
        try:
            cache_user(target)
        except Exception:
            pass

        uid = getattr(target, "id", "—")
        first = getattr(target, "first_name", "") or ""
        last = getattr(target, "last_name", "") or ""
        name = (first + (" " + last if last else "")).strip() or "—"
        username = f"@{getattr(target, 'username', None)}" if getattr(target, "username", None) else "—"
        is_bot = getattr(target, "is_bot", False)
        # some User objects expose 'is_premium' / 'language_code'
        is_premium = getattr(target, "is_premium", False)
        lang_code = getattr(target, "language_code", None) or "—"

        # seen (from our cache)
        seen = "—"
        try:
            entry = _user_cache.get("by_id", {}).get(str(uid))
            if entry:
                seen = entry.get("seen", "—")
        except Exception:
            seen = "—"

        # profile photo count
        photo_count = 0
        try:
            photos = await context.bot.get_user_profile_photos(uid, limit=1)
            photo_count = getattr(photos, "total_count", 0) or 0
        except Exception:
            photo_count = 0

        # chat-specific status (admin/creator/member)
        chat_status = "—"
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, uid)
            chat_status = getattr(member, "status", "—")
        except Exception:
            chat_status = "—"

        # bio / about (via get_chat may contain description for some users)
        bio = None
        try:
            chat_obj = await context.bot.get_chat(uid)
            bio = getattr(chat_obj, "description", None) or getattr(chat_obj, "bio", None)
        except Exception:
            bio = None

        # more environment info we can provide (bot-side)
        try:
            me = await context.bot.get_me()
            bot_username = getattr(me, "username", "—")
        except Exception:
            bot_username = "—"

        # helper to escape HTML
        def esc(x):
            return html.escape(str(x)) if x is not None else "—"

        # build full report (HTML)
        lines = []
        lines.append(f"{bold('👤 User Info')}")
        lines.append("")  # spacer
        lines.append(f"{bold('Name')}: {esc(name)}")
        lines.append(f"{bold('Username')}: {esc(username)}")
        lines.append(f"{bold('User ID')}: <code>{esc(uid)}</code>")
        lines.append(f"{bold('Bot account')}: {'Yes' if is_bot else 'No'}")
        # optional flags
        lines.append(f"{bold('Premium')}: {'Yes' if is_premium else 'No'}")
        lines.append(f"{bold('Language')}: {esc(lang_code)}")
        lines.append(f"{bold('Seen')}: {esc(seen)}")
        lines.append(f"{bold('Profile photos')}: {photo_count}")
        lines.append(f"{bold('Chat status')}: {esc(chat_status)}")
        if bio:
            lines.append(f"{bold('Bio')}: {esc(bio)}")
        report = "\n".join(lines)

        # final: edit placeholder to report (text-only)
        if placeholder:
            try:
                await placeholder.edit_text(report, parse_mode="HTML")
                return
            except Exception:
                # fallback: new message
                await msg.reply_text(report, parse_mode="HTML")
                return
        else:
            await msg.reply_text(report, parse_mode="HTML")
            return

    except Exception:
        logger.exception("info_cmd failed")
        try:
            await update.message.reply_text("Gagal ambil info user.")
        except Exception:
            pass

# ---- dollar-prefix router ----
_DOLLAR_CMD_MAP = {
    "dl": dl_cmd,
    "speedtest": speedtest_cmd,
    "ping": ping_cmd,
    "deepseek": ai_deepseek_cmd,
    "openai": ai_openai_cmd,
    "start": start_cmd,
    "help": help_cmd,
    "nsfw": pollinations_generate_nsfw,
    "groq": groq_query,
    "menu": help_cmd,
    "setmodeai": setmodeai_cmd,
    "ai": ai_cmd,
    "info": info_cmd,
    "ban": ban_cmd,
    "mute": mute_cmd,
    "unmute": unmute_cmd,
    "warn": warn_cmd,
    "unwarn": unwarn_cmd,
    "warns": warns_cmd,
    "resetwarn": resetwarn_cmd,
    "setwarnthreshold": setwarnthreshold_cmd,
    "addbad": addbad_cmd,
    "rmbad": rmbad_cmd,
    "listbad": listbad_cmd,
    "setaction": setaction_cmd,
    "setduration": setduration_cmd,
    "stats": stats_cmd,
    "syncadmins": syncadmins_cmd,
    "whois": whois_cmd,
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

# ======================
# MAIN ENTRY
# ======================
def main():
    logger.info("Initializing bot...")

    # ======================
    # BUILD APPLICATION
    # ======================
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # ======================
    # CORE COMMANDS
    # ======================
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", help_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("speedtest", speedtest_cmd))
    app.add_handler(CommandHandler("dl", dl_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("whois", whois_cmd))

    # ======================
    # AI COMMANDS
    # ======================
    app.add_handler(CommandHandler("ai", ai_cmd))
    app.add_handler(CommandHandler("setmodeai", setmodeai_cmd))
    app.add_handler(CommandHandler("openai", ai_openai_cmd))
    app.add_handler(CommandHandler("groq", groq_query))
    app.add_handler(CommandHandler("deepseek", ai_deepseek_cmd))
    app.add_handler(CommandHandler("nsfw", pollinations_generate_nsfw))

    # ======================
    # ADMIN / MODERATION
    # ======================
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))

    # ======================
    # WARN SYSTEM
    # ======================
    app.add_handler(CommandHandler("warn", warn_cmd))
    app.add_handler(CommandHandler("unwarn", unwarn_cmd))
    app.add_handler(CommandHandler("warns", warns_cmd))
    app.add_handler(CommandHandler("resetwarn", resetwarn_cmd))
    app.add_handler(CommandHandler("setwarnthreshold", setwarnthreshold_cmd))

    # ======================
    # BLACKLIST ADMIN
    # ======================
    app.add_handler(CommandHandler("addbad", addbad_cmd))
    app.add_handler(CommandHandler("rmbad", rmbad_cmd))
    app.add_handler(CommandHandler("listbad", listbad_cmd))
    app.add_handler(CommandHandler("setaction", setaction_cmd))
    app.add_handler(CommandHandler("setduration", setduration_cmd))

    # ======================
    # ADMIN UTILITIES
    # ======================
    app.add_handler(CommandHandler("syncadmins", syncadmins_cmd))

    # ======================
    # INLINE CALLBACKS
    # ======================
    app.add_handler(
        CallbackQueryHandler(help_callback, pattern=r"^help:")
    )

    # ======================
    # PRIORITY MESSAGE PIPELINE
    # ======================

    # 0️⃣ cache semua user dulu
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, user_cache_handler),
        group=1
    )

    # 1️⃣ $router (contoh: $groq, $ai)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, dollar_router),
        group=0
    )

    # 2️⃣ auto blacklist detector
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _blacklist_process),
        group=2
    )

    # 3️⃣ fallback (biar ga error)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: None),
        group=99
    )

    # ======================
    # STARTUP INFO
    # ======================
    try:
        bl = load_blacklist()
        warns_data = load_json_file(WARNS_FILE, {})

        banner = r"""
  ____        _   _       ____        _
 |  _ \ _   _| |_| |__   |  _ \  __ _| |_
 | |_) | | | | __| '_ \  | | | |/ _` | __|
 |  _ <| |_| | |_| |_) | | |_| | (_| | |_
 |_| \_\\__,_|\__|_.__/  |____/ \__,_|\__|
"""
        print(banner)
        logger.info("Bot starting...")
        logger.info(f"Blacklist words: {len(bl.get('words', []))}")
        logger.info(f"Chats with warns: {len(warns_data)}")

    except Exception:
        logger.exception("Startup info failed")

    # ======================
    # SAFE set_my_commands (ASYNC)
    # ======================
    async def _set_commands(app):
        cmds = [
            ("start", "Check bot status"),
            ("help", "Show help menu"),
            ("ping", "Check latency"),
            ("speedtest", "Network speed test"),
            ("dl", "Download video (TT/IG/YT)"),
            ("info", "User information"),
            ("stats", "System statistics"),
        ]
        try:
            await app.bot.set_my_commands(cmds)
        except Exception:
            logger.exception("set_my_commands failed")

    app.post_init = _set_commands

    # ======================
    # RUN BOT
    # ======================
    logger.info("Launching polling loop...")
    print("Launching... (listening for updates)")
    app.run_polling(close_loop=False)


# ======================
# ENTRY POINT
# ======================
if __name__ == "__main__":
    main()