#!/usr/bin/env python3

import os
import shlex
import asyncio
import logging
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    JobQueue,
    filters,
)

from utils.http import close_http_session
from handlers.commands import register_commands
from handlers.messages import register_messages
from handlers.callbacks import register_callbacks

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_USERNAME = None

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


async def post_init(app):
    global BOT_USERNAME
    me = await app.bot.get_me()
    BOT_USERNAME = me.username.lower()

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
    ])


async def post_shutdown(app):
    await close_http_session()


def main():
    setup_logger()
    logger.info("🐾 Initializing bot")

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
    logger.info("🐾 Bot core loaded")
    logger.info("🐾 Polling loop started")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()