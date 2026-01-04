import html
import asyncio
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
        lines.append(f"{code} — {LANG_NAMES.get(code)}")
    await update.message.reply_text("\n".join(lines))

async def _translate_google(text, target):
    tr = GoogleTranslator(source="auto", target=target)
    return tr.translate(text), tr.detect(text)

async def _translate_mymemory(text, target):
    tr = MyMemoryTranslator(source="auto", target=target, email="bot@localhost")
    return tr.translate(text), "auto"

async def _translate_libre(text, target):
    tr = LibreTranslator(
        source="auto",
        target=target,
        base_url="https://translate.argosopentech.com"
    )
    return tr.translate(text), "auto"

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
                "Usage:\n"
                "/tr en hello\n"
                "/tr id good morning\n"
                "/trlist"
            )

    msg = await update.message.reply_text("Translating...")

    try:
        translated, detected = await asyncio.to_thread(
            lambda: _translate_google_sync(text, target_lang)
        )
        return await msg.edit_text(
            f"Translated → {target_lang.upper()}\n\n"
            f"{html.escape(translated)}\n\n"
            f"Source: {detected}\n"
            f"Engine: Google"
        )
    except Exception:
        pass

    try:
        translated, _ = await asyncio.to_thread(
            lambda: _translate_mymemory_sync(text, target_lang)
        )
        return await msg.edit_text(
            f"Translated → {target_lang.upper()}\n\n"
            f"{html.escape(translated)}\n\n"
            f"Engine: MyMemory"
        )
    except Exception:
        pass

    try:
        translated, _ = await asyncio.to_thread(
            lambda: _translate_libre_sync(text, target_lang)
        )
        return await msg.edit_text(
            f"Translated → {target_lang.upper()}\n\n"
            f"{html.escape(translated)}\n\n"
            f"Engine: Libre"
        )
    except Exception:
        pass

    await msg.edit_text("❌ Translator service unavailable")


def _translate_google_sync(text, target):
    tr = GoogleTranslator(source="auto", target=target)
    return tr.translate(text), tr.detect(text)

def _translate_mymemory_sync(text, target):
    tr = MyMemoryTranslator(source="auto", target=target, email="bot@localhost")
    return tr.translate(text), "auto"

def _translate_libre_sync(text, target):
    tr = LibreTranslator(
        source="auto",
        target=target,
        base_url="https://translate.argosopentech.com"
    )
    return tr.translate(text), "auto"