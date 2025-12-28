import os
import sys
import html

from telegram import Update
from telegram.ext import ContextTypes

from utils.config import OWNER_ID


async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    await update.message.reply_text(
        "♻️ <b>Restarting bot...</b>",
        parse_mode="HTML"
    )

    # flush biar log ga ilang
    sys.stdout.flush()
    sys.stderr.flush()

    # restart process
    os.execv(sys.executable, [sys.executable] + sys.argv)
