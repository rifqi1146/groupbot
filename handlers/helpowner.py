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
        "👑 <b>Owner Commands</b>\n"
        "<i>Administrative & system-level controls</i>\n\n"

        "⚙️ <b>System Management</b>\n"
        "• <code>/speedtest</code> — run server speed test\n"
        "• <code>/broadcast</code> — announcement \n"
        "• <code>/autodel</code> — manage auto delete asupan settings\n"
        "• <code>/wlc</code> — configure welcome message\n"
        "• <code>/restart</code> — restart the bot\n\n"

        "🍜 <b>Asupan Management</b>\n"
        "• <code>/enableasupan</code> — enable asupan feature\n"
        "• <code>/disableasupan</code> — disable asupan feature\n"
        "• <code>/asupanlist</code> — list asupan-enabled chats\n"
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

