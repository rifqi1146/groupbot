from telegram import Update
from telegram.ext import ContextTypes
import aiohttp

from utils.http import get_http_session
from utils.storage import load_json_file

NSFW_FILE = "data/nsfw_groups.json"


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

    tags = [t.lower() for t in context.args] if context.args else []

    params = {
        "limit": 1,
        "is_nsfw": True,
    }

    if tags:
        params["included_tags"] = ",".join(tags)

    headers = {
        "User-Agent": "Mozilla/5.0 (TelegramBot)"
    }

    session = await get_http_session()
    async with session.get(
        "https://api.waifu.im/search",
        params=params,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            return await msg.reply_text(
                f"❌ API Error ({resp.status})\n<code>{text}</code>",
                parse_mode="HTML"
            )

        data = await resp.json()

    images = data.get("images")
    if not images:
        return await msg.reply_text("❌ Waifu tidak ditemukan 😭")

    img = images[0]

    caption = "💖 <b>Waifu</b>\n"
    if tags:
        caption += f"🏷 Tag: <code>{', '.join(tags)}</code>\n"

    artist = img.get("artist") or {}
    if artist.get("name"):
        caption += f"🎨 Artist: <b>{artist['name']}</b>\n"

    if img.get("source"):
        caption += f"🔗 <a href='{img['source']}'>Source</a>"

    await msg.reply_photo(
        photo=img["url"],
        caption=caption,
        parse_mode="HTML"
    )