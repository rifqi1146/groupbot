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
from handlers.nsfw import (
    enablensfw_cmd,
    disablensfw_cmd,
    nsfwlist_cmd,
    pollinations_generate_nsfw,
)

from handlers.networking import (
    whoisdomain_cmd,
    ip_cmd,
    domain_cmd,
)

from handlers.start import start_cmd
from handlers.tr import tr_cmd
from handlers.gsearch import gsearch_cmd, gsearch_callback
from handlers.stats import stats_cmd
from handlers.help import help_cmd, help_callback
from handlers.speedtest import speedtest_cmd
from handlers.ping import ping_cmd
from handlers.weather import weather_cmd
from handlers.dl import (
    dl_cmd,
    dl_callback,
    dlask_callback,
    auto_dl_detect,
)

from handlers.helpowner import (
    helpowner_cmd,
    helpowner_callback,
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