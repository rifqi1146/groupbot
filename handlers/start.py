from telegram import Update
from telegram.ext import ContextTypes

from handlers.welcome import start_verify_pm

# start
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        arg = context.args[0]
        if arg.startswith("verify_"):
            return await start_verify_pm(update, context)
            
    user = update.effective_user
    name = (user.first_name or "").strip() or "there"
    text = (
        f"👋 Hello {name}!\n\n"
        "Type /help to see the menu."
    )
    await update.message.reply_text(text)