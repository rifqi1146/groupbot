from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes
from utils.text import bold, code, italic, underline, link, mono

#menu/help
def help_main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✨ Features", callback_data="help:features"),
            InlineKeyboardButton("🤐 AI Chat", callback_data="help:ai"),
        ],
        [
            InlineKeyboardButton("🧠 Utilities", callback_data="help:utils"),
            InlineKeyboardButton("🔐 Privacy", callback_data="help:privacy"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="help:settings"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="help:close"),
        ],
    ])

def help_settings_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍜 Asupan", callback_data="help:asupan"),
            InlineKeyboardButton("🗑️ AutoDel", callback_data="help:autodel"),
        ],
        [
            InlineKeyboardButton("⬇️ AutoDL", callback_data="help:autodl"),
            InlineKeyboardButton("😍 Caca", callback_data="help:cacaa"),
        ],
        [
            InlineKeyboardButton("🔞 NSFW", callback_data="help:nsfw"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="help:menu"),
            InlineKeyboardButton("❌ Close", callback_data="help:close"),
        ],
    ])

def help_back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="help:menu")],
        [InlineKeyboardButton("❌ Close", callback_data="help:close")],
    ])

def help_settings_back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="help:settings")],
        [InlineKeyboardButton("❌ Close", callback_data="help:close")],
    ])
    
HELP_TEXT = {
    "help:menu": (
        "📖 <b>Help Menu</b>\n"
        "Select a category to see available commands."
    ),

    "help:features": (
        "✨ <b>Main Features</b>\n\n"
        "• ⬇️ <code>/dl</code> — Download videos from supported platforms\n"
        "• 🍜 <code>/asupan</code> — Random TikTok content\n"
        "• 🌤️ <code>/weather</code> — Get weather information\n"
        "• 🔎 <code>/gsearch</code> — Search on Google\n"
        "• 🌍 <code>/tr</code> — Translate text between languages\n"
        "• 📃 <code>/trlist</code> — List supported languages\n"
        "• 💝 <code>/ship</code> — Choose couple\n"
        "• 🧭 <code>/reminder</code> — Schedule reminder\n"
    ),

    "help:ai": (
        "🤐 <b>AI Chat</b>\n\n"
        "• 💬 <code>/ai</code> — Chat with AI Gemini\n"
        "• 🧠 <code>/ask</code> — ChatGPT\n"
        "• ⚡ <code>/groq</code> — Groq\n"
        "• 🍌 <code>/meta</code> — Meta AI\n"
        "• 😍 <code>/caca</code> — Caca Chat Bot\n"
    ),

    "help:utils": (
        "🛠️ <b>Utilities</b>\n\n"
        "• 🏓 <code>/ping</code> — Check bot response time\n"
        "• 📊 <code>/stats</code> — Bot & system statistics\n"
        "• 🌐 <code>/ip</code> — IP address lookup\n"
        "• 🏷️ <code>/domain</code> — Domain information\n"
        "• 🔍 <code>/whoisdomain</code> — Detailed domain lookup\n"
    ),

    "help:privacy": (
        "🔐 <b>Privasi Pengguna</b>\n\n"
        "Dengan menggunakan bot ini, pengguna memahami dan menyetujui bahwa:\n\n"
        "• Owner bot dapat melihat dan menyimpan riwayat command yang digunakan pengguna\n"
        "• Data yang dicatat meliputi:\n"
        "  - ID pengguna Telegram\n"
        "  - Username (jika ada)\n"
        "  - Command yang digunakan\n"
        "  - Waktu penggunaan (timestamp)\n\n"
        "Data tersebut hanya digunakan untuk keperluan:\n"
        "• Pengembangan\n"
        "• Pemeliharaan\n"
        "• Peningkatan layanan bot\n\n"
        "<b>❗ Jangan kirimkan kata sandi, nomor identitas, atau data sensitive lainnya.</b>\n\n"
        "Dengan melanjutkan penggunaan bot, pengguna dianggap telah menyetujui kebijakan ini."
    ),
}

HELP_TEXT.update({
    "help:settings": (
        "⚙️ <b>Bot Settings</b>\n\n"
        "Pengaturan berikut hanya dapat digunakan oleh <b>Admin Grup</b>.\n\n"
        "Pilih menu di bawah untuk melihat detail per fitur."
    ),

    "help:asupan": (
        "🍜 <b>Asupan Settings</b>\n\n"
        "• <code>/asupann enable</code> — Aktifkan asupan di grup\n"
        "• <code>/asupann disable</code> — Matikan asupan di grup\n"
        "• <code>/asupann status</code> — Cek status asupan\n\n"
    ),

    "help:autodel": (
        "🗑️ <b>Auto Delete Asupan</b>\n\n"
        "• <code>/autodel enable</code> — Aktifkan auto delete asupan\n"
        "• <code>/autodel disable</code> — Matikan auto delete asupan\n"
        "• <code>/autodel status</code> — Cek status auto delete\n\n"
    ),

    "help:autodl": (
        "⬇️ <b>Auto Download Link</b>\n\n"
        "• <code>/autodl enable</code> — Aktifkan auto-detect link\n"
        "• <code>/autodl disable</code> — Matikan auto-detect link\n"
        "• <code>/autodl status</code> — Cek status auto-detect\n\n"
    ),

    "help:cacaa": (
        "😍 <b>Caca Settings</b>\n\n"
        "• <code>/cacaa enable</code> — Aktifkan Caca di grup\n"
        "• <code>/cacaa disable</code> — Matikan Caca di grup\n"
        "• <code>/cacaa status</code> — Cek status Caca\n\n"
    ),
})

HELP_TEXT.update({
    "help:nsfw": (
        "🔞 <b>NSFW Settings</b>\n\n"
        "• <code>/nsfw enable</code> — Aktifkan NSFW di grup\n"
        "• <code>/nsfw disable</code> — Matikan NSFW di grup\n"
        "• <code>/nsfw status</code> — Cek status NSFW\n\n"
    ),
})

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
    
    if data == "help:settings":
        await q.edit_message_text(
            HELP_TEXT["help:settings"],
            reply_markup=help_settings_keyboard(),
            parse_mode="HTML"
        )
        return
        
    #category  
    text = HELP_TEXT.get(data)
    if text:
        if data.startswith("help:asupan") or data.startswith("help:autodel") \
           or data.startswith("help:autodl") or data.startswith("help:cacaa"):
            kb = help_settings_back_keyboard()
        else:
            kb = help_back_keyboard()
    
        await q.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode="HTML"
        )

