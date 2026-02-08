from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes
import aiohttp
import time

from utils.http import get_http_session
from utils.storage import load_json_file

NSFW_FILE = "data/nsfw_groups.json"

_WAIFU_LAST_TAG = {}
_WAIFU_HISTORY = {}
_WAIFU_TS = {}

EXPIRE_SEC = 30 * 60

def _load_nsfw():
    return load_json_file(NSFW_FILE, {"groups": []})

def _cleanup(chat_id):
    now = time.time()
    ts = _WAIFU_TS.get(chat_id)
    if not ts or now - ts > EXPIRE_SEC:
        _WAIFU_HISTORY.pop(chat_id, None)
        _WAIFU_LAST_TAG.pop(chat_id, None)
        _WAIFU_TS.pop(chat_id, None)

def _push(chat_id, img):
    _cleanup(chat_id)
    _WAIFU_HISTORY.setdefault(chat_id, []).append(img)
    _WAIFU_TS[chat_id] = time.time()

def _pop(chat_id):
    _cleanup(chat_id)
    hist = _WAIFU_HISTORY.get(chat_id, [])
    if len(hist) < 2:
        return None
    hist.pop()
    return hist[-1]

def _build_caption(img, tag):
    cap = "💖 <b>Waifu</b>\n"
    if tag:
        cap += f"🏷 Tag: <code>{tag}</code>\n"
    artist = img.get("artist") or {}
    if artist.get("name"):
        cap += f"🎨 Artist: <b>{artist['name']}</b>"
    return cap

def _build_kb(img):
    rows = [[
        InlineKeyboardButton("⏪ Pref", callback_data="waifu_pref"),
        InlineKeyboardButton("▶️ Next", callback_data="waifu_next")
    ]]
    if img.get("source"):
        rows.append([InlineKeyboardButton("🔗 Source", url=img["source"])])
    return InlineKeyboardMarkup(rows)

async def waifu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not chat:
        return

    nsfw = _load_nsfw()
    if chat.type in ("group", "supergroup") and chat.id not in nsfw["groups"]:
        return await msg.reply_text("❌ NSFW tidak diaktifkan di grup ini.")

    if not context.args:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏷️ Daftar Tag Waifu",
                    url="https://www.waifu.im/tags"
                )
            ]
        ])
    
        return await msg.reply_text(
            "💖 <b>Waifu Command</b>\n\n"
            "• <code>/waifu random</code>\n"
            "• <code>/waifu maid</code>\n"
            "• <code>/waifu raiden-shogun</code>\n\n"
            "Klik tombol di bawah untuk lihat tag 👇",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )

    keyword = context.args[0].lower()
    tag = None if keyword == "random" else keyword
    _WAIFU_LAST_TAG[chat.id] = tag
    _cleanup(chat.id)

    params = {
    "IsNsfw": "All",
    "Gif": "False"
    }
    
    if tag:
        params["IncludedTags"] = tag

    session = await get_http_session()
    async with session.get(
        "https://api.waifu.im/images",
        params=params,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as resp:
        if resp.status != 200:
            return await msg.reply_text(f"❌ API Error ({resp.status})")
        data = await resp.json()

    images = data.get("items")
    if not images:
        return await msg.reply_text("❌ Waifu tidak ditemukan 😭")

    img = images[0]
    _push(chat.id, img)

    await msg.reply_photo(
        photo=img["url"],
        caption=_build_caption(img, tag),
        parse_mode="HTML",
        reply_markup=_build_kb(img)
    )

async def waifu_next_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    chat_id = q.message.chat_id
    _cleanup(chat_id)
    tag = _WAIFU_LAST_TAG.get(chat_id)

    params = {
    "IsNsfw": "All",
    "Gif": "False"
    }
    
    if tag:
        params["IncludedTags"] = tag

    session = await get_http_session()
    async with session.get(
        "https://api.waifu.im/images",
        params=params,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as resp:
        if resp.status != 200:
            return await q.answer("API error 😭", show_alert=True)
        data = await resp.json()

    images = data.get("items")
    if not images:
        return await q.answer("Waifu kosong 😭", show_alert=True)

    img = images[0]
    _push(chat_id, img)

    await q.message.edit_media(
        media=InputMediaPhoto(
            media=img["url"],
            caption=_build_caption(img, tag),
            parse_mode="HTML"
        ),
        reply_markup=_build_kb(img)
    )

async def waifu_pref_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    chat_id = q.message.chat_id
    img = _pop(chat_id)
    if not img:
        return await q.answer("Ga ada waifu sebelumnya 😭", show_alert=True)

    tag = _WAIFU_LAST_TAG.get(chat_id)

    await q.message.edit_media(
        media=InputMediaPhoto(
            media=img["url"],
            caption=_build_caption(img, tag),
            parse_mode="HTML"
        ),
        reply_markup=_build_kb(img)
    )