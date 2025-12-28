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
from handlers.ai import (
    ask_cmd,
    ai_cmd,
    setmodeai_cmd,
    groq_query,
)
from utils.config import OWNER_ID, ASUPAN_STARTUP_CHAT_ID
from handlers.speedtest import speedtest_cmd
from handlers.weather import weather_cmd
from handlers.dl import (
    dl_cmd,
    dl_callback,
    dlask_callback,
    auto_dl_detect,
)
from handlers.asupan import (
    asupan_cmd,
    asupan_callback,
    ASUPAN_STARTUP_CHAT_ID, 
    send_asupan_once,
    enable_asupan_cmd,
    disable_asupan_cmd,
    asupanlist_cmd,
    autodel_cmd,
    load_asupan_groups,
    load_autodel_groups,
    startup_tasks,
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
    JobQueue,
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

#----@*#&#--------
USER_CACHE_FILE = "users.json"

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

#bot name 
BOT_USERNAME = None

async def init_bot_username(app):
    global BOT_USERNAME
    me = await app.bot.get_me()
    BOT_USERNAME = me.username.lower()
    
#restart
async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    await update.message.reply_text("♻️ <b>Restarting bot...</b>", parse_mode="HTML")
    
#cmd owner
def helpowner_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Close", callback_data="helpowner:close")]
    ])
    
async def helpowner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message

    if not user or user.id != OWNER_ID:
        return await msg.reply_text("❌ Owner only.")

    text = (
        "👑 <b>Owner Commands</b>\n\n"
        "⚡ <b>System</b>\n"
        "• <code>/speedtest</code>\n"
        "• <code>/autodel</code>\n"
        "• <code>/wlc</code>\n"
        "• <code>/restart</code>\n\n"
        "🧠 <b>NSFW Control</b>\n"
        "• <code>/enablensfw</code>\n"
        "• <code>/disablensfw</code>\n"
        "• <code>/nsfwlist</code>\n\n"
        "🍜 <b>Asupan Control</b>\n"
        "• <code>/enableasupan</code>\n"
        "• <code>/disableasupan</code>\n"
        "• <code>/asupanlist</code>\n"
    )

    await msg.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=helpowner_keyboard()
    )
    
async def helpowner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query

    if q.data != "helpowner:close":
        return

    try:
        await q.message.delete()
    except Exception:
        pass
                

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
                   
#welcome 
WELCOME_ENABLED_CHATS = set()
WELCOME_FILE = "welcome_chats.json"

def load_welcome_chats():
    global WELCOME_ENABLED_CHATS
    if not os.path.exists(WELCOME_FILE):
        WELCOME_ENABLED_CHATS = set()
        return
    try:
        with open(WELCOME_FILE, "r") as f:
            data = json.load(f)
            WELCOME_ENABLED_CHATS = set(data.get("chats", []))
    except Exception:
        WELCOME_ENABLED_CHATS = set()

def save_welcome_chats():
    with open(WELCOME_FILE, "w") as f:
        json.dump({"chats": list(WELCOME_ENABLED_CHATS)}, f, indent=2)
      
async def wlc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    if not context.args:
        return await update.message.reply_text(
            "Gunakan:\n"
            "<code>/wlc on</code>\n"
            "<code>/wlc off</code>",
            parse_mode="HTML"
        )

    mode = context.args[0].lower()

    if mode == "on":
        WELCOME_ENABLED_CHATS.add(chat.id)
        save_welcome_chats()
        await update.message.reply_text("✅ Welcome message diaktifkan.")
    elif mode == "off":
        WELCOME_ENABLED_CHATS.discard(chat.id)
        save_welcome_chats()
        await update.message.reply_text("🚫 Welcome message dimatikan.")
    else:
        await update.message.reply_text("❌ Gunakan <code>on</code> atau <code>off</code>.", parse_mode="HTML")
          
async def welcome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat

    if chat.id not in WELCOME_ENABLED_CHATS:
        return

    for user in msg.new_chat_members:
        username = f"@{user.username}" if user.username else "—"
        fullname = user.full_name
        chatname = chat.title or "this group"

        caption = (
            f"👋 <b>Hai {fullname}</b>\n"
            f"Selamat datang di <b>{chatname}</b> ✨\n\n"
            f"🧾 <b>User Information</b>\n"
            f"🆔 ID       : <code>{user.id}</code>\n"
            f"👤 Name     : {fullname}\n"
            f"🔖 Username : {username}\n\n"
        )

        try:
            photos = await context.bot.get_user_profile_photos(user.id, limit=1)
            if photos.total_count > 0:
                await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=photos.photos[0][-1].file_id,
                    caption=caption,
                    parse_mode="HTML"
                )
            else:
                await msg.reply_text(caption, parse_mode="HTML")
        except Exception:
            await msg.reply_text(caption, parse_mode="HTML")
                
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

BOT_COMMANDS = {
    "start",
    "help",
    "menu",
    "helpowner",
    "ask",
    "weather",
    "ping",
    "enablensfw",
    "disablensfw",
    "nsfwlist",
    "speedtest",
    "ip",
    "whoisdomain",
    "domain",
    "dl",
    "stats",
    "tr",
    "gsearch",
    "enableasupan",
    "disableasupan",
    "asupanlist",
    "asupan",
    "wlc",
    "restart",
    "ai",
    "setmodeai",
    "groq",
    "nsfw",
}

#log terminal
async def log_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    is_slash = text.startswith("/")
    is_dollar = text.startswith("$")
    if not (is_slash or is_dollar):
        return

    raw = text[1:].split()[0].lower()
    bot_cmds = set(_DOLLAR_CMD_MAP.keys())

    if is_slash and raw not in bot_cmds:
        return

    if is_dollar and raw not in bot_cmds:
        return

    user = msg.from_user
    name = user.first_name if user else "Unknown"
    uid = user.id if user else "—"

    chat = update.effective_chat
    chat_type = chat.type.upper()
    chat_name = chat.title if chat.title else "Private"

    args = text[len(raw) + 1:].strip()

    log_text = (
        f"👀 <b>Command LOG</b>\n"
        f"👤 <b>Nama</b> : {name}\n"
        f"🆔 <b>ID</b> : <code>{uid}</code>\n"
        f"🏷 <b>Chat</b> : {chat_type} | {chat_name}\n"
        f"⌨️ <b>Command</b> : <code>{text}</code>"
    )

    try:
        await context.bot.send_message(
            chat_id=ASUPAN_STARTUP_CHAT_ID,
            text=log_text,
            parse_mode="HTML",
            disable_notification=True
        )
    except Exception:
        pass
        
#log
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
    
#dollar prefix
_DOLLAR_CMD_MAP = {
    "start": start_cmd,
    "help": help_cmd,
    "menu": help_cmd,
    "helpowner": helpowner_cmd,
    "ping": ping_cmd,
    "restart": restart_cmd,
    "ask": ask_cmd,
    "ai": ai_cmd,
    "groq": groq_query,
    "setmodeai": setmodeai_cmd,
    "weather": weather_cmd,
    "speedtest": speedtest_cmd,
    "ip": ip_cmd,
    "stats": stats_cmd,
    "autodel": autodel_cmd,
    "tr": tr_cmd,
    "gsearch": gsearch_cmd,
    "dl": dl_cmd,
    "domain": domain_cmd,
    "whoisdomain": whoisdomain_cmd,
    "asupan": asupan_cmd,
    "asupanlist": asupanlist_cmd,
    "enableasupan": enable_asupan_cmd,
    "disableasupan": disable_asupan_cmd,
    "nsfw": pollinations_generate_nsfw,
    "enablensfw": enablensfw_cmd,
    "wlc": wlc_cmd,
    "disablensfw": disablensfw_cmd,
    "nsfwlist": nsfwlist_cmd,
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
            
#post init
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
        ])
    except Exception:
        pass

    try:
        cmds = await app.bot.get_my_commands()
        app.bot_data["commands"] = cmds
        logger.info(
            "🧠 Cached bot commands: "
            + ", ".join(c.command for c in cmds)
        )
    except Exception as e:
        logger.warning(f"⚠️ Gagal cache bot commands: {e}")

    await asyncio.sleep(5)

    if not ASUPAN_STARTUP_CHAT_ID:
        logger.warning("⚠️ ASUPAN STARTUP chat_id kosong")
        return

    try:
        await send_asupan_once(app.bot)
        logger.info("🍜 Asupan startup sent")
    except Exception as e:
        logger.warning(f"⚠️ Asupan startup failed: {e}")
        
#main
def main():
    logger.info("🐾 Initializing bot")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(20)
        .job_queue(JobQueue())
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(20)
        .build()
    )

    app.post_shutdown = post_shutdown
    app.post_init = post_init

    load_asupan_groups()
    
    load_welcome_chats()
    
    load_autodel_groups()

    #cmd handler
    app.add_handler(CommandHandler("start", start_cmd), group=-1)
    app.add_handler(CommandHandler("autodel", autodel_cmd), group=-1)
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
    app.add_handler(CommandHandler("helpowner", helpowner_cmd), group=-1)
    app.add_handler(CommandHandler("wlc", wlc_cmd), group=-1)

    #massage handler
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_handler),
         group=-1
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_dl_detect, block=False),
        group=-1
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, dollar_router),
        group=1
    )

    app.add_handler(
        MessageHandler(filters.ALL, log_commands),
        group=99
    )

    #callback
    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(gsearch_callback, pattern=r"^gsearch:"))
    app.add_handler(CallbackQueryHandler(dl_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(asupan_callback, pattern=r"^asupan:"))
    app.add_handler(CallbackQueryHandler(dlask_callback, pattern=r"^dlask:"))
    app.add_handler(CallbackQueryHandler(helpowner_callback, pattern=r"^helpowner:"))

    #bannner
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

    logger.info("🐾 Polling loop started")
    print("Listening for updates…")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()