import html
import json
import aiohttp
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from handlers.join import require_join_or_block
from utils.http import get_http_session
from utils.config import NEOXR_API_KEY

log = logging.getLogger(__name__)
BASE_URL = "https://api.neoxr.eu/api"

def esc(text) -> str:
    return html.escape(str(text or "-"))

async def neoxr_get(endpoint: str, params: dict | None = None, timeout: int = 20):
    if not NEOXR_API_KEY:
        return False, "NEOXR_API_KEY is not set in .env"
    params = dict(params or {})
    params["apikey"] = NEOXR_API_KEY
    session = await get_http_session()
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            raw = await resp.text()
            if resp.status != 200:
                return False, f"HTTP {resp.status}: {raw[:500]}"
            try:
                return True, json.loads(raw)
            except Exception:
                return False, f"Invalid JSON: {raw[:500]}"
    except asyncio.TimeoutError:
        return False, "Request timeout. The API may be slow or busy."
    except Exception as e:
        return False, str(e)

def format_quote(data: dict) -> str:
    anime = data.get("anime")
    character = data.get("character")
    quotes = data.get("quotes")
    return (
        "🎴 <b>Anime Quote</b>\n\n"
        f"👤 <b>Character:</b> <code>{esc(character)}</code>\n"
        f"🥳 <b>Anime:</b> <code>{esc(anime)}</code>\n\n"
        f"❝ {esc(quotes)} ❞"
    )

async def quoteanime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    msg = update.message
    if not msg:
        return
    ok, payload = await neoxr_get("quotesnime")
    if not ok:
        return await msg.reply_text(
            f"Failed to fetch anime quote.\n\n<code>{esc(payload)}</code>",
            parse_mode="HTML",
        )
    if not isinstance(payload, dict):
        return await msg.reply_text("Invalid API response.")
    if not payload.get("status"):
        err = payload.get("message") or payload.get("msg") or payload.get("data") or "Anime quote not found."
        return await msg.reply_text(
            f"Failed to fetch anime quote.\n\n<code>{esc(err)}</code>",
            parse_mode="HTML",
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        return await msg.reply_text("Anime quote data is empty.")
    await msg.reply_text(
        format_quote(data),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )