import subprocess
import asyncio
import os
import sys
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID

async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user

    if not user or user.id not in OWNER_ID:
        return await msg.reply_text("❌ Owner only.")

    status = await msg.reply_text("🔄 Cek update...")

    fetch = subprocess.run(
        ["git", "fetch"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    check = subprocess.run(
        ["git", "status", "-uno"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if "behind" not in check.stdout:
        return await status.edit_text("✅ Bot sudah versi terbaru.")

    pull = subprocess.run(
        ["git", "pull"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if pull.returncode != 0:
        return await status.edit_text(
            f"❌ Git pull gagal:\n<code>{pull.stderr}</code>",
            parse_mode="HTML"
        )

    await status.edit_text("♻️ Update sukses, restart bot...")

    await asyncio.sleep(1)

    os.execv(sys.executable, [sys.executable] + sys.argv)