import html
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from deep_translator import GoogleTranslator

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

LANG_FLAGS = {
    "en": "🇬🇧",
    "id": "🇮🇩",
    "ja": "🇯🇵",
    "ko": "🇰🇷",
    "zh": "🇨🇳",
    "fr": "🇫🇷",
    "de": "🇩🇪",
    "es": "🇪🇸",
    "it": "🇮🇹",
    "ru": "🇷🇺",
    "ar": "🇸🇦",
    "hi": "🇮🇳",
    "pt": "🇵🇹",
    "tr": "🇹🇷",
    "vi": "🇻🇳",
    "th": "🇹🇭",
    "ms": "🇲🇾",
    "nl": "🇳🇱",
    "pl": "🇵🇱",
    "uk": "🇺🇦",
    "sv": "🇸🇪",
    "fi": "🇫🇮",
}

async def trlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["<b>Supported Languages</b>\n"]
    for code in sorted(VALID_LANGS):
        name = LANG_NAMES.get(code, code.upper())
        flag = LANG_FLAGS.get(code, "🏳️")
        lines.append(f"{flag} <code>{code}</code> — {name}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML"
    )


async def tr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    target = DEFAULT_LANG
    text = ""

    if args:
        first = args[0].lower()
        if first in VALID_LANGS and len(args) > 1:
            target = first
            text = " ".join(args[1:])
        elif first in VALID_LANGS:
            target = first
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
                "Reply message:\n"
                "<code>/tr en</code>",
                parse_mode="HTML"
            )

    msg = await update.message.reply_text("Translating...")

    try:
        translated = await asyncio.to_thread(
            lambda: GoogleTranslator(source="auto", target=target).translate(text)
        )

        flag = LANG_FLAGS.get(target, "🏳️")

        await msg.edit_text(
            f"<b>Translation Result</b>\n\n"
            f"Target: {flag} <b>{target.upper()}</b>\n\n"
            f"{html.escape(translated)}\n\n"
            f"Engine: <code>Google Translate</code>",
            parse_mode="HTML"
        )

    except Exception as e:
        await msg.edit_text(
            f"<b>Translator unavailable</b>\n"
            f"<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )