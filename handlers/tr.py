import html
from telegram import Update
from telegram.ext import ContextTypes
from deep_translator import GoogleTranslator, MyMemoryTranslator, LibreTranslator

DEFAULT_LANG = "en"

VALID_LANGS = {
    "en","id","ja","ko","zh","fr","de","es","it","ru","ar","hi","pt","tr",
    "vi","th","ms","nl","pl","uk","sv","fi"
}

LANG_NAMES = {
    "en": "English",
    "id": "Indonesian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "pt": "Portuguese",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "ms": "Malay",
    "nl": "Dutch",
    "pl": "Polish",
    "uk": "Ukrainian",
    "sv": "Swedish",
    "fi": "Finnish",
}

async def trlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["Supported Languages:\n"]
    for code in sorted(VALID_LANGS):
        name = LANG_NAMES.get(code, code.upper())
        lines.append(f"{code} — {name}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML"
    )
    
async def tr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    target_lang = DEFAULT_LANG
    text = ""

    if args:
        first = args[0].lower()
        if first in VALID_LANGS and len(args) > 1:
            target_lang = first
            text = " ".join(args[1:])
        elif first in VALID_LANGS:
            target_lang = first
        else:
            text = " ".join(args)

    if not text:
        if update.message.reply_to_message and update.message.reply_to_message.text:
            text = update.message.reply_to_message.text
        else:
            return await update.message.reply_text(
                "<b>Translator</b>\n\n"
                "Usage:\n"
                "<code>/tr en hello</code>\n"
                "<code>/tr id good morning</code>\n"
                "<code>/tr apa kabar?</code>\n\n"
                "Or reply message:\n"
                "<code>/tr en</code>",
                parse_mode="HTML"
            )

    msg = await update.message.reply_text("Translating...")

    try:
        tr = GoogleTranslator(source="auto", target=target_lang)
        translated = tr.translate(text)
        detected = tr.detect(text)

        return await msg.edit_text(
            f"Translated → {target_lang.upper()}\n\n"
            f"{html.escape(translated)}\n\n"
            f"Source: <code>{detected}</code>\n"
            f"Engine: <code>Google</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    try:
        tr = MyMemoryTranslator(source="auto", target=target_lang)
        translated = tr.translate(text)

        return await msg.edit_text(
            f"Translated → {target_lang.upper()}\n\n"
            f"{html.escape(translated)}\n\n"
            f"Engine: <code>MyMemory</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    try:
        tr = LibreTranslator(
            source="auto",
            target=target_lang,
            base_url="https://libretranslate.com"
        )
        translated = tr.translate(text)

        return await msg.edit_text(
            f"Translated → {target_lang.upper()}\n\n"
            f"{html.escape(translated)}\n\n"
            f"Engine: <code>Libre</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await msg.edit_text("❌ All translators failed")