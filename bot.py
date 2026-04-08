#!/usr/bin/env python3

import os
import socket
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, JobQueue

from utils.http import close_http_session
from handlers.commands import register_commands
from handlers.callbacks import register_callbacks
from handlers.messages import register_messages
from utils.startup import startup_tasks
from utils.config import BOT_TOKEN

BOT_USERNAME = None

LOCAL_BOT_API_HOST = os.getenv("LOCAL_BOT_API_HOST", "127.0.0.1")
LOCAL_BOT_API_PORT = int(os.getenv("LOCAL_BOT_API_PORT", "8081"))
PREFER_LOCAL_BOT_API = os.getenv("PREFER_LOCAL_BOT_API", "1").strip().lower() not in ("0", "false", "no")


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


def _local_bot_api_available(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _build_application():
    builder = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
        .concurrent_updates(True)
        .connect_timeout(30)
        .read_timeout(60 * 20)
        .write_timeout(60 * 20)
        .pool_timeout(60)
    )

    if PREFER_LOCAL_BOT_API and _local_bot_api_available(LOCAL_BOT_API_HOST, LOCAL_BOT_API_PORT):
        base = f"http://{LOCAL_BOT_API_HOST}:{LOCAL_BOT_API_PORT}"
        log.info(f"✓ Using local Telegram Bot API at {base}")
        builder = (
            builder
            .base_url(f"{base}/bot")
            .base_file_url(f"{base}/file/bot")
        )
    else:
        if PREFER_LOCAL_BOT_API:
            log.warning("Local Telegram Bot API unavailable, falling back to official Telegram Bot API")
        else:
            log.info("✓ Local Telegram Bot API disabled, using official Telegram Bot API")

    return builder.build()


async def post_init(app):
    global BOT_USERNAME

    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning(f"Failed to clear webhook/pending updates: {e}")

    try:
        me = await app.bot.get_me()
        BOT_USERNAME = (me.username or "").lower()
        if BOT_USERNAME:
            log.info(f"✓ Bot username loaded: @{BOT_USERNAME}")
        else:
            log.info("✓ Bot username loaded")
    except Exception as e:
        log.warning(f"Failed to get bot username: {e}")

    try:
        await app.bot.set_my_commands([
            ("start", "Check bot status"),
            ("donate", "Support bot"),
            ("help", "Show help menu"),
            ("settings", "User setting"),
            ("quiz", "random soal"),
            ("ping", "Check latency"),
            ("ship", "Choose couple"),
            ("stats", "System statistics"),
            ("dl", "Download video"),
            ("manga", "Baca Manga"),
            ("ask", "Ask Gemini AI"),
            ("music", "Search music"),
            ("caca", "Chat sama caca 😍"),
            ("groq", "Ask Groq AI"),
            ("gsearch", "Google search"),
            ("asupan", "Asupan 😋"),
            ("tr", "Translate text"),
        ])
        log.info("✓ Bot commands set")
    except Exception as e:
        log.warning(f"Failed to set bot commands: {e}")

    try:
        cmds = await app.bot.get_my_commands()
        app.bot_data["commands"] = cmds
        log.info("✓ Cached bot commands: " + ", ".join(c.command for c in cmds))
    except Exception as e:
        log.warning(f"Failed to cache bot commands: {e}")

    await startup_tasks(app)
    log.info("✓ Startup tasks executed")


async def post_shutdown(app):
    await close_http_session()
    log.info("HTTP session closed")


def main():
    setup_logger()
    log.info("Initializing bot")

    app = _build_application()

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

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()