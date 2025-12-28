from telegram import Update
from telegram.ext import ContextTypes
from deep_translator import GoogleTranslator, MyMemoryTranslator, LibreTranslator

from utils.text import bold, code, italic, underline, link, mono

#translator
DEFAULT_LANG = "en"

VALID_LANGS = {
    "en","id","ja","ko","zh","fr","de","es","it","ru","ar","hi","pt","tr",
    "vi","th","ms","nl","pl","uk","sv","fi"
}

async def tr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    target_lang = DEFAULT_LANG
    text = ""

    if args:
        first = args[0].lower()

        if first in VALID_LANGS and len(args) >= 2:
            target_lang = first
            text = " ".join(args[1:])

        elif first in VALID_LANGS and len(args) == 1:
            target_lang = first

        else:
            target_lang = DEFAULT_LANG
            text = " ".join(args)

    if not text:
        if update.message.reply_to_message and update.message.reply_to_message.text:
            text = update.message.reply_to_message.text
        else:
            return await update.message.reply_text(
                "<b>🔤 Translator</b>\n\n"
                "Contoh:\n"
                "<code>/tr en hello bro</code>\n"
                "<code>/tr id good morning</code>\n"
                "<code>/tr apa kabar bro?</code>\n\n"
                "Atau reply pesan:\n"
                "<code>/tr en</code>",
                parse_mode="HTML"
            )

    msg = await update.message.reply_text("🔤 Translating...")

    translators = []
    try: translators.append(("Google", GoogleTranslator))
    except: pass
    try: translators.append(("MyMemory", MyMemoryTranslator))
    except: pass
    try: translators.append(("Libre", LibreTranslator))
    except: pass

    if not translators:
        return await msg.edit_text("❌ Translator tidak tersedia")

    for name, T in translators:
        try:
            tr = T(source="auto", target=target_lang)
            translated = tr.translate(text)

            try:
                detected = tr.detect(text)
            except:
                detected = "auto"

            out = (
                f"✅ <b>Translated → {target_lang.upper()}</b>\n\n"
                f"{html.escape(translated)}\n\n"
                f"🔍 Source: <code>{detected}</code>\n"
                f"🔧 Engine: <code>{name}</code>"
            )

            return await msg.edit_text(out, parse_mode="HTML")

        except Exception:
            continue

    await msg.edit_text("❌ Semua translator gagal")
    
