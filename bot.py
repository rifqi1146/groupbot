#!/usr/bin/env python3

import os
import sys
import json
import time
import shlex
import shutil
import asyncio
import logging
import uuid
import aiohttp
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    JobQueue,
    filters,
)

# Utils 
from utils.commands import BOT_COMMANDS
from utils.http import get_http_session, close_http_session

# Core ai
from handlers.ai import (
    ask_cmd,
    ai_cmd,
    setmodeai_cmd,
    groq_query,
)

# Ytta aja bg
from handlers.nsfw import (
    enablensfw_cmd,
    disablensfw_cmd,
    nsfwlist_cmd,
    pollinations_generate_nsfw,
)

# Networking 
from handlers.networking import (
    whoisdomain_cmd,
    ip_cmd,
    domain_cmd,
)

# Misc
from handlers.start import start_cmd
from handlers.orangefox import orangefox_cmd
from handlers.logger import log_commands
from handlers.tr import tr_cmd
from handlers.restart import restart_cmd
from handlers.gsearch import gsearch_cmd, gsearch_callback
from handlers.stats import stats_cmd
from handlers.help import help_cmd, help_callback
from handlers.speedtest import speedtest_cmd
from handlers.ping import ping_cmd
from handlers.weather import weather_cmd

# Downloader 
from handlers.dl import (
    dl_cmd,
    dl_callback,
    dlask_callback,
    auto_dl_detect,
)

# OwnerCmd
from handlers.helpowner import (
    helpowner_cmd,
    helpowner_callback,
)

# Welcome
from handlers.welcome import (
    wlc_cmd,
    welcome_handler,
    load_welcome_chats,
)

#Asupan
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

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

# Constants / Globals
USER_CACHE_FILE = "users.json"
BOT_USERNAME = None

# JSON Helpers
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

# Bot Identity
async def init_bot_username(app):
    global BOT_USERNAME
    me = await app.bot.get_me()
    BOT_USERNAME = me.username.lower()

# Emoji Logger
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
        EmojiFormatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    return root

# Dollar Command Router
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
    "disablensfw": disablensfw_cmd,
    "nsfwlist": nsfwlist_cmd,
    "wlc": wlc_cmd,
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
    context.args = parts[1:]

    handler = _DOLLAR_CMD_MAP.get(cmd)
    if not handler:
        return

    try:
        await handler(update, context)
    except Exception:
        logger.exception("dollar_router: handler %s failed", cmd)
        try:
            await msg.reply_text("Gagal menjalankan perintah.")
        except Exception:
            pass

# Post Init / Shutdown
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
        logger.info("🧠 Cached bot commands: " + ", ".join(c.command for c in cmds))
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


async def post_shutdown(app):
    try:
        await close_http_session()
    except Exception:
        logger.exception("Failed during post_shutdown")

# Main
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

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    load_asupan_groups()
    load_welcome_chats()
    load_autodel_groups()

    # ---- Commands
    app.add_handler(CommandHandler("start", start_cmd), group=-1)
    app.add_handler(CommandHandler("orangefox", orangefox_cmd), group=-1)
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

    # ---- Messages
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_handler),
        group=-1,
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_dl_detect, block=False),
        group=-1,
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, dollar_router),
        group=1,
    )

    app.add_handler(
        MessageHandler(filters.ALL, log_commands),
        group=99,
    )

    # ---- Callbacks
    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(gsearch_callback, pattern=r"^gsearch:"))
    app.add_handler(CallbackQueryHandler(dl_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(asupan_callback, pattern=r"^asupan:"))
    app.add_handler(CallbackQueryHandler(dlask_callback, pattern=r"^dlask:"))
    app.add_handler(CallbackQueryHandler(helpowner_callback, pattern=r"^helpowner:"))

    # ---- Banner
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