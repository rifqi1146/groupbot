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
        "📋 <b>Help Menu</b>\n"
        "Choose a category below ✨"
    ),

    "help:features": (
        "✨ <b>Features</b>\n\n"
        "• 🏓 /ping — Check bot latency\n"
        "• ⬇️ /dl — Download videos (TikTok / Instagram)\n"
        "• 😋 /asupan — Random TikTok content\n"
        "• ☁️ /weather — Weather information\n"
        "• 🔍 /gsearch — Search something on Google\n"
        "• 🌐 /tr — Translate text to another language\n"
    ),

    "help:ai": (
        "🤖 <b>AI Commands</b>\n\n"
        "• /ai — Ask AI (default mode)\n"
        "• /ask — ChatGpt \n"
        "• /groq — GroqAI\n"
        "• /ai flash|pro|lite — Select AI model\n"
        "• /setmodeai — Set default AI model\n\n"
    ),

    "help:utils": (
        "🧠 <b>Utilities</b>\n\n"
        "• /stats — Bot system information\n"
        "• /ip — IP address information\n"
        "• /domain — Domain information\n"
        "• /whoisdomain — Detailed domain\n"
        "• ⚡ /speedtest — Run speed test\n"
        "• ♻️ /restart — Restart bot\n"
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

