from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import subprocess
import os
import sys
import asyncio

async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user

    if not user or user.id not in OWNER_ID:
        return await msg.reply_text("❌ Owner only.")

    status = await msg.reply_text("🔄 Cek update...")

    subprocess.run(["git", "fetch"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    check = subprocess.run(
        ["git", "status", "-uno"],
        stdout=subprocess.PIPE,
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

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("♻️ Restart Bot", callback_data="update_restart"),
            InlineKeyboardButton("❌ Batal", callback_data="update_cancel"),
        ]
    ])

    await status.edit_text(
        "✅ <b>Update ditemukan & berhasil di-pull.</b>\n\n"
        "Restart bot sekarang?",
        parse_mode="HTML",
        reply_markup=kb
    )
    
async def update_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    await query.answer()

    if not user or user.id not in OWNER_ID:
        return await query.edit_message_text("❌ Owner only.")

    if query.data == "update_cancel":
        return await query.edit_message_text("🚫 Update dibatalkan.")

    if query.data == "update_restart":
        await query.edit_message_text(
            "♻️ <b>Restarting bot...</b>",
            parse_mode="HTML"
        )

        await asyncio.sleep(1)

        os.execv(sys.executable, [sys.executable] + sys.argv)