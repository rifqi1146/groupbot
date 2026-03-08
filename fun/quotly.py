import io
import os
import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

QUOTE_API_URI = os.getenv("QUOTE_API_URI")

def _entities_to_quote(entities):
    out = []
    for ent in entities or []:
        item = {
            "offset": int(ent.offset),
            "length": int(ent.length),
            "type": str(ent.type),
        }
        if getattr(ent, "url", None):
            item["url"] = ent.url
        if getattr(ent, "language", None):
            item["language"] = ent.language
        if getattr(ent, "custom_emoji_id", None):
            item["custom_emoji_id"] = ent.custom_emoji_id
        out.append(item)
    return out

async def q_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    target = msg.reply_to_message
    if not target:
        return await msg.reply_text("Reply pesan untuk membuat sticker.")

    if not QUOTE_API_URI:
        return await msg.reply_text("QUOTE_API_URI belum diset.")

    source_user = target.from_user
    if not source_user:
        return await msg.reply_text("User tidak ditemukan.")

    text = (target.text or target.caption or "").strip()
    if not text:
        return await msg.reply_text("Pesan itu tidak punya teks.")

    entities = target.entities if target.text else target.caption_entities

    payload = {
        "type": "quote",
        "format": "webp",
        "backgroundColor": "//#292232",
        "width": 512,
        "height": 768,
        "scale": 2,
        "emojiBrand": "apple",
        "messages": [
            {
                "chatId": int(source_user.id),
                "avatar": True,
                "from": {
                    "id": int(source_user.id),
                    "first_name": source_user.first_name,
                    "last_name": source_user.last_name,
                    "username": source_user.username,
                },
                "text": text,
                "entities": _entities_to_quote(entities),
                "replyMessage": {},
            }
        ],
    }

    wait = await msg.reply_text("Sedang membuat sticker...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{QUOTE_API_URI.rstrip('/')}/generate.webp?botToken={context.bot.token}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    return await wait.edit_text(f"Gagal membuat sticker: {resp.status}\n{err[:300]}")
                image_bytes = await resp.read()

        sticker = io.BytesIO(image_bytes)
        sticker.name = "quote.webp"

        kwargs = {}
        if getattr(msg, "message_thread_id", None):
            kwargs["message_thread_id"] = msg.message_thread_id

        await context.bot.send_sticker(
            chat_id=msg.chat_id,
            sticker=sticker,
            reply_to_message_id=target.message_id,
            **kwargs,
        )

        await wait.delete()
    except Exception as e:
        await wait.edit_text(f"Gagal membuat sticker: {e}")