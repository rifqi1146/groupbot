#!/usr/bin/env python3
import os
import sys
import time
import signal
import logging
import subprocess
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import ApplicationBuilder, JobQueue

from utils.http import close_http_session
from handlers.commands import register_commands
from handlers.callbacks import register_callbacks
from handlers.messages import register_messages
from utils.startup import startup_tasks
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
    handler.setFormatter(EmojiFormatter("[%(asctime)s] %(message)s", "%H:%M:%S"))

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
        await app.bot.set_my_commands(
            [
                ("start", "Check bot status"),
                ("help", "Show help menu"),
                ("quiz", "random soal"),
                ("ping", "Check latency"),
                ("ship", "Choose couple"),
                ("stats", "System statistics"),
                ("dl", "Download video"),
                ("ai", "Ask Gemini AI"),
                ("ask", "Ask ChatGPT"),
                ("caca", "Chat sama caca 😍"),
                ("groq", "Ask Groq AI"),
                ("gsearch", "Google search"),
                ("asupan", "Asupan 😋"),
                ("tr", "Translate text"),
            ]
        )
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


def _ensure_env_or_exit():
    load_dotenv()

    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    if not api_id or not api_hash:
        print("[!] API_ID atau API_HASH belum diset")
        sys.exit(1)

    return api_id, api_hash


def _start_local_bot_api(api_id: str, api_hash: str):
    tgdata_dir = "tgdata"
    os.makedirs(tgdata_dir, exist_ok=True)

    cmd = [
        "telegram-bot-api",
        f"--api-id={api_id}",
        f"--api-hash={api_hash}",
        "--local",
        "--http-port=8081",
        f"--dir={tgdata_dir}",
    ]

    print("[+] Starting Telegram Bot API...")
    proc = subprocess.Popen(cmd)
    return proc


def main():
    setup_logger()
    log.info("Initializing bot")

    api_id, api_hash = _ensure_env_or_exit()
    bot_api_proc = _start_local_bot_api(api_id, api_hash)

    def shutdown(signum, frame):
        print("\n[!] Shutting down...")
        try:
            if bot_api_proc and bot_api_proc.poll() is None:
                bot_api_proc.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    time.sleep(2)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .base_url("http://127.0.0.1:8081/bot")
        .base_file_url("http://127.0.0.1:8081/file/bot")
        .job_queue(JobQueue())
        .connect_timeout(30)
        .read_timeout(60 * 20)
        .write_timeout(60 * 20)
        .pool_timeout(60)
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

    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        try:
            if bot_api_proc and bot_api_proc.poll() is None:
                bot_api_proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()