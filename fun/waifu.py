from telegram import Update
from telegram.ext import ContextTypes
import aiohttp
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from utils.http import get_http_session
from utils.storage import load_json_file

NSFW_FILE = "data/nsfw_groups.json"
_WAIFU_LAST_TAG = {}

def _load_nsfw():
    return load_json_file(NSFW_FILE, {"groups": []})

async def waifu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not chat:
        return

    nsfw = _load_nsfw()
    if chat.type in ("group", "supergroup"):
        if chat.id not in nsfw["groups"]:
            return await msg.reply_text("❌ NSFW tidak diaktifkan di grup ini.")

    if not context.args:
        return await msg.reply_text(
            "💖 <b>Waifu Command</b>\n\n"
            "• <code>/waifu random</code> → waifu random\n"
            "• <code>/waifu maid</code> → waifu tag maid\n"
            "• <code>/waifu raiden-shogun</code>\n\n"
            "Pakai tag dari <a href='https://docs.waifu.im/reference/tags'>waifu.im</a>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    keyword = context.args[0].lower()
    tag = None if keyword == "random" else keyword
    _WAIFU_LAST_TAG[chat.id] = tag

    params = {
        "is_nsfw": "true",
        "limit": 1
    }
    if tag:
        params["included_tags"] = tag

    session = await get_http_session()
    async with session.get(
        "https://api.waifu.im/search",
        params=params,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as resp:
        if resp.status != 200:
            return await msg.reply_text(f"❌ API Error ({resp.status})")

        data = await resp.json()

    images = data.get("images")
    if not images:
        return await msg.reply_text("❌ Waifu tidak ditemukan 😭")

    img = images[0]

    caption = "💖 <b>Waifu</b>\n"
    if tag:
        caption += f"🏷 Tag: <code>{tag}</code>\n"

    artist = img.get("artist") or {}
    if artist.get("name"):
        caption += f"🎨 Artist: <b>{artist['name']}</b>"

    buttons = [
        [
            InlineKeyboardButton("▶️ Next", callback_data="waifu_next")
        ]
    ]

    if img.get("source"):
        buttons[0].append(
            InlineKeyboardButton("🔗 Source", url=img["source"])
        )

    keyboard = InlineKeyboardMarkup(buttons)

    await msg.reply_photo(
        photo=img["url"],
        caption=caption,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    
async def waifu_next_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    tag = _WAIFU_LAST_TAG.get(chat_id)

    params = {
        "is_nsfw": "true",
        "limit": 1
    }
    if tag:
        params["included_tags"] = tag

    session = await get_http_session()
    async with session.get(
        "https://api.waifu.im/search",
        params=params,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as resp:
        if resp.status != 200:
            return await query.edit_message_caption("❌ API Error")

        data = await resp.json()

    images = data.get("images")
    if not images:
        return await query.edit_message_caption("❌ Waifu tidak ditemukan 😭")

    img = images[0]

    caption = "💖 <b>Waifu</b>\n"
    if tag:
        caption += f"🏷 Tag: <code>{tag}</code>\n"

    artist = img.get("artist") or {}
    if artist.get("name"):
        caption += f"🎨 Artist: <b>{artist['name']}</b>"

    buttons = [
        [
            InlineKeyboardButton("▶️ Next", callback_data="waifu_next")
        ]
    ]
    if img.get("source"):
        buttons[0].append(
            InlineKeyboardButton("🔗 Source", url=img["source"])
        )

    await query.message.edit_media(
        media={
            "type": "photo",
            "media": img["url"],
            "caption": caption,
            "parse_mode": "HTML"
        },
        reply_markup=InlineKeyboardMarkup(buttons)
    )