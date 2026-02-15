from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.config import DONATE_URL


async def donate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if not DONATE_URL:
        return await msg.reply_text(
            "Donate link is not configured.",
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Donate (QRIS)", url=DONATE_URL)]
    ])

    text = (
        "<b>Support the Bot</b>\n\n"
        "If you enjoy using this bot and would like to support its development, "
        "you can donate through the button below."
    )

    await msg.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
    )