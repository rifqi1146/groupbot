from telegram import Update
from telegram.ext import ContextTypes
from fun.ship import add_user

async def user_collector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    add_user(chat.id, msg.from_user)