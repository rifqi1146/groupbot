from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from utils.config import OWNER_ID
from utils.text import bold, code, italic, underline, link, mono


def helpowner_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Close", callback_data="helpowner:close")]
    ])


async def helpowner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message

    if not user or user.id != OWNER_ID:
        return await msg.reply_text("❌ Owner only.")

    text = (
        "👑 <b>Owner Commands</b>\n\n"
        "⚡ <b>System</b>\n"
        "• <code>/speedtest</code>\n"
        "• <code>/autodel</code>\n"
        "• <code>/wlc</code>\n"
        "• <code>/restart</code>\n\n"
        "🧠 <b>NSFW Control</b>\n"
        "• <code>/enablensfw</code>\n"
        "• <code>/disablensfw</code>\n"
        "• <code>/nsfwlist</code>\n\n"
        "🍜 <b>Asupan Control</b>\n"
        "• <code>/enableasupan</code>\n"
        "• <code>/disableasupan</code>\n"
        "• <code>/asupanlist</code>\n"
    )

    await msg.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=helpowner_keyboard()
    )


async def helpowner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query

    if q.data != "helpowner:close":
        return

    try:
        await q.message.delete()
    except Exception:
        pass

