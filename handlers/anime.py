import os
import html
import inspect
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from handlers.join import require_join_or_block
from utils.http import get_http_session

NEOXR_ANIME_API = os.getenv("NEOXR_ANIME_API", "https://api.neoxr.eu/api/anime").strip()
ANIME_LIMIT = int(os.getenv("ANIME_LIMIT", "3"))

def _clean_text(value: str, default: str = "-") -> str:
    text = str(value or "").strip()
    return text if text else default

async def _shared_http_session():
    session = get_http_session()
    if inspect.isawaitable(session):
        session = await session
    return session

async def _fetch_anime(query: str) -> list[dict]:
    api_key = os.getenv("NEOXR_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("NEOXR_API_KEY is not set in the environment.")
    session = await _shared_http_session()
    params = {"q": query, "apikey": api_key}
    async with session.get(NEOXR_ANIME_API, params=params) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"API error {resp.status}: {text[:500]}")
        try:
            data = await resp.json(content_type=None)
        except Exception:
            raise RuntimeError(f"Invalid API JSON: {text[:500]}")
    if not data.get("status"):
        raise RuntimeError(data.get("message") or "Anime not found.")
    results = data.get("data") or []
    if not isinstance(results, list):
        return []
    return [x for x in results if isinstance(x, dict)][:ANIME_LIMIT]

def _build_anime_text(results: list[dict]) -> str:
    lines = ["<b>🎬 Anime Search Results</b>", ""]
    for i, item in enumerate(results, 1):
        title = _clean_text(item.get("title"), "Untitled")
        score = _clean_text(item.get("score"), "N/A")
        anime_type = _clean_text(item.get("type"), "Unknown")
        lines.append(f"{i}. <b>{html.escape(title)}</b>")
        lines.append(f"   Type: {html.escape(anime_type)}")
        lines.append(f"   Score: {html.escape(score)}")
        lines.append("")
    return "\n".join(lines).strip()

def _build_anime_keyboard(results: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, item in enumerate(results, 1):
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        rows.append([InlineKeyboardButton(f"Open {i}", url=url)])
    return InlineKeyboardMarkup(rows)

async def anime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    msg = update.effective_message
    query = " ".join(context.args).strip()
    if not query:
        return await msg.reply_text(
            "🎬 <b>Anime Command</b>\n\n"
            "Use this format:\n"
            "<code>/anime &lt;anime title&gt;</code>",
            parse_mode="HTML",
        )
    status = await msg.reply_text(
        "⏳ <b>Searching anime...</b>",
        reply_to_message_id=msg.message_id,
        parse_mode="HTML",
    )
    try:
        results = await _fetch_anime(query)
        if not results:
            raise RuntimeError("Anime not found.")
        await status.edit_text(
            _build_anime_text(results),
            reply_markup=_build_anime_keyboard(results),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        await status.edit_text(
            f"<b>Failed to search anime</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )