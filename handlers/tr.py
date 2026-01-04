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
                "Usage:\n"
                "/tr en hello\n"
                "/tr id good morning"
            )

    msg = await update.message.reply_text("🔤 Translating...")

    try:
        translated = await asyncio.to_thread(
            lambda: GoogleTranslator(source="auto", target=target).translate(text)
        )

        await msg.edit_text(
            f"Translated → {target.upper()}\n\n"
            f"{html.escape(translated)}\n\n"
            f"Engine: Google",
            parse_mode="HTML"
        )

    except Exception as e:
        await msg.edit_text(f"❌ Translate failed\n<code>{html.escape(str(e))}</code>", parse_mode="HTML")