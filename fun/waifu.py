from telegram import Update
from telegram.ext import ContextTypes
import aiohttp

from utils.http import get_http_session
from utils.storage import load_json_file

NSFW_FILE = "data/nsfw.json"


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

    if context.args:
        tags = [t.lower() for t in context.args]
    else:
        tags = []

    params = {
        "limit": 1,
        "is_nsfw": "true",
    }

    if tags:
        params["included_tags"] = tags

    url = "https://api.waifu.im/search"

    session = await get_http_session()
    async with session.get(
        url,
        params=params,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as resp:
        if resp.status != 200:
            return await msg.reply_text("❌ Gagal ambil waifu 😭")

        data = await resp.json()

    images = data.get("images")
    if not images:
        if tags:
            return await msg.reply_text(
                f"❌ Waifu dengan tag <b>{', '.join(tags)}</b> tidak ditemukan.",
                parse_mode="HTML"
            )
        return await msg.reply_text("❌ Waifu tidak ditemukan.")

    img = images[0]

    img_url = img.get("url")
    artist = img.get("artist", {})
    artist_name = artist.get("name", "Unknown")
    artist_twitter = artist.get("twitter")
    source = img.get("source")

    caption = "💖 <b>Waifu</b>\n"
    if tags:
        caption += f"🏷 Tag: <code>{', '.join(tags)}</code>\n"
    caption += f"🎨 Artist: <b>{artist_name}</b>\n"

    if artist_twitter:
        caption += f"🐦 <a href='{artist_twitter}'>Twitter</a>\n"
    if source:
        caption += f"🔗 <a href='{source}'>Source</a>"

    await msg.reply_photo(
        photo=img_url,
        caption=caption,
        parse_mode="HTML"
    )