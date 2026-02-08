import os
import sys
import asyncio
import subprocess
import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.config import OWNER_ID


def _get_changelog():

    try:
        log = subprocess.run(
            ["git", "log", "HEAD..origin/main", "--pretty=format:%s"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )
        if not log.stdout.strip():
            return None

        lines = log.stdout.strip().splitlines()
        return "\n".join(f"• {html.escape(line)}" for line in lines)

    except Exception:
        return None


async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user

    if not user or user.id not in OWNER_ID:
        return await msg.reply_text("❌ Owner only.")

    status = await msg.reply_text("🔄 Cek update...")

    subprocess.run(
        ["git", "fetch"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    check = subprocess.run(
        ["git", "status", "-uno"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True
    )

    if "behind" not in check.stdout:
        return await status.edit_text("✅ Bot sudah versi terbaru.")

    changelog = _get_changelog()

    pull = subprocess.run(
        ["git", "pull"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if pull.returncode != 0:
        return await status.edit_text(
            f"❌ Git pull gagal:\n<code>{html.escape(pull.stderr)}</code>",
            parse_mode="HTML"
        )

    text = "✅ <b>Update berhasil!</b>\n\n"

    if changelog:
        text += "📝 <b>Changelog:</b>\n"
        text += changelog + "\n\n"
    else:
        text += "📝 <i>Tidak ada changelog.</i>\n\n"

    text += "Restart bot sekarang?"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("♻️ Restart Bot", callback_data="update_restart"),
            InlineKeyboardButton("❌ Batal", callback_data="update_cancel"),
        ]
    ])

    await status.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb
    )
    
async def update_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if not user or user.id not in OWNER_ID:
        await query.answer("❌ Lu bukan owner.", show_alert=True)
        return

    if query.data == "update_cancel":
        await query.answer("❎ Dibatalkan.")
        await query.message.edit_reply_markup(None)
        return

    if query.data == "update_restart":
        await query.answer("♻️ Restarting...")
        await query.message.edit_text(
            "♻️ <b>Update sukses, restarting bot...</b>",
            parse_mode="HTML"
        )

        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
        