#!/usr/bin/env python3

import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, JobQueue

from utils.http import close_http_session
from handlers.commands import register_commands
from handlers.callbacks import register_callbacks
from handlers.messages import register_messages
from handlers.startup import startup_tasks
from utils.config import BOT_TOKEN
BOT_USERNAME = None

class EmojiFormatter(logging.Formatter):
    EMOJI = {
        logging.INFO: "➜",
        logging.WARNING: "⚠️",
        logging.ERROR: "❌",
        logging.CRITICAL: "💥",
    }

    def format(self, record):
        emoji = self.EMOJI.get(record.levelno, "•")
        record.msg = f"{emoji} {record.msg}"
        return super().format(record)


def setup_logger():
    handler = logging.StreamHandler()
    handler.setFormatter(
        EmojiFormatter("[%(asctime)s] %(message)s", "%H:%M:%S")
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)


log = logging.getLogger(__name__)


async def post_init(app):
    global BOT_USERNAME

    try:
        me = await app.bot.get_me()
        BOT_USERNAME = me.username.lower()
        log.info(f"🤖 Bot username loaded: @{BOT_USERNAME}")
    except Exception as e:
        log.warning(f"⚠️ Failed to get bot username: {e}")

    try:
        await app.bot.set_my_commands([
            ("start", "Check bot status"),
            ("help", "Show help menu"),
            ("ping", "Check latency"),
            ("stats", "System statistics"),
            ("dl", "Download video"),
            ("ai", "Ask AI"),
            ("ask", "Ask ChatGPT"),
            ("groq", "Ask Groq AI"),
            ("gsearch", "Google search"),
            ("asupan", "Asupan 😋"),
            ("tr", "Translate text"),
        ])
        log.info("📜 Bot commands set")
    except Exception as e:
        log.warning(f"⚠️ Failed to set bot commands: {e}")

    try:
        cmds = await app.bot.get_my_commands()
        app.bot_data["commands"] = cmds
        log.info("🧠 Cached bot commands: " + ", ".join(c.command for c in cmds))
    except Exception as e:
        log.warning(f"⚠️ Failed to cache bot commands: {e}")

    await startup_tasks(app)
    log.info("🚀 Startup tasks executed")


async def post_shutdown(app):
    await close_http_session()
    log.info("HTTP session closed")


def main():
    setup_logger()
    log.info("Initializing bot")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
        .connect_timeout(20)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(20)
        .build()
    )

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    register_commands(app)
    register_messages(app)
    register_callbacks(app)

    banner = r"""
 ／l、
（ﾟ､ ｡ ７   < Nya~ Master! Bot waking up…
  l  ~ヽ       • Loading neko engine
  じしf_, )     • Warming up whiskers
               • Injecting kawaii into memory…
 💖 Ready to serve!
"""
    print(banner)

    log.info("Handlers registered")
    log.info("Polling started")

    app.run_polling(allowed_updates=Update.ALL_TYPES)
    
  
if __name__ == "__main__":
    main()