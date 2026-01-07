from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes
from utils.text import bold, code, italic, underline, link, mono

#menu/help
def help_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Features", callback_data="help:features")],
        [InlineKeyboardButton("🤖 AI", callback_data="help:ai")],
        [InlineKeyboardButton("🧠 Utilities", callback_data="help:utils")],
        [InlineKeyboardButton("❌ Close", callback_data="help:close")],
    ])

def help_back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="help:menu")],
        [InlineKeyboardButton("❌ Close", callback_data="help:close")],
    ])

HELP_TEXT = {
    "help:menu": (
        "📖 <b>Help Menu</b>\n"
        "Select a category to see available commands."
    ),

    "help:features": (
        "✨ <b>Main Features</b>\n\n"
        "• 🏓 <code>/ping</code> — check bot response time\n"
        "• ⬇️ <code>/dl</code> — download videos from supported platforms\n"
        "• 🍜 <code>/asupan</code> — random TikTok content\n"
        "• 🌤️ <code>/weather</code> — get weather information\n"
        "• 🔎 <code>/gsearch</code> — search on Google\n"
        "• 🌍 <code>/tr</code> — translate text between languages\n"
        "• 📃 <code>/trlist</code> — list supported languages\n"
    ),

    "help:ai": (
        "🤖 <b>AI Commands</b>\n\n"
        "• 💬 <code>/ai</code> — chat with AI (default mode)\n"
        "• 🧠 <code>/ask</code> — ChatGPT\n"
        "• ⚡ <code>/groq</code> — Groq\n"
        "• 🧪 <code>/ai flash | pro | lite</code> — switch AI model\n"
        "• ⚙️ <code>/setmodeai</code> — set default AI model\n"
    ),

    "help:utils": (
        "🛠️ <b>Utilities</b>\n\n"
        "• 📊 <code>/stats</code> — bot & system statistics\n"
        "• 🌐 <code>/ip</code> — IP address lookup\n"
        "• 🏷️ <code>/domain</code> — domain information\n"
        "• 🔍 <code>/whoisdomain</code> — detailed domain lookup\n"
    ),
}

#cmd
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        HELP_TEXT["help:menu"],
        reply_markup=help_main_keyboard(),
        parse_mode="HTML"
    )

#helpcallback
async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return

    data = q.data or ""

    #ack
    try:
        await q.answer()
    except:
        pass

    #close
    if data == "help:close":
        try:
            await q.message.delete()
        except:
            pass
        return

    #menu/helpp
    if data == "help:menu":
        await q.edit_message_text(
            HELP_TEXT["help:menu"],
            reply_markup=help_main_keyboard(),
            parse_mode="HTML"
        )
        return

    #category 
    text = HELP_TEXT.get(data)
    if text:
        await q.edit_message_text(
            text,
            reply_markup=help_back_keyboard(),
            parse_mode="HTML"
        )

