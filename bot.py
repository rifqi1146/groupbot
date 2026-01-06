#!/usr/bin/env python3

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, JobQueue

from utils.http import close_http_session
from handlers.commands import register_commands
from handlers.callbacks import register_callbacks
from handlers.messages import register_messages
from handlers.startup import startup_tasks

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

async def post_init(app):
    await startup_tasks(app)

async def post_shutdown(app):
    await close_http_session()

def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
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
    log.info("Polling started")

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()