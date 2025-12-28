from telegram import Update
from telegram.ext import ContextTypes

#start
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = (user.first_name or "").strip() or "there"
    text = (
        f"👋 Halo {name}!\n\n"
        "Ketik /help buat lihat menu."
    )
    await update.message.reply_text(text)

