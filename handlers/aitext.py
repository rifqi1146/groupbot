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
MAX_TEXT_LENGTH = 4000

def esc(text) -> str:
    return html.escape(str(text or "-"))

def _usage_text() -> str:
    return (
        "<b>AI Text Detector</b>\n\n"
        "Reply to a text message:\n"
        "<code>/aitext</code>\n\n"
        "Or use text directly:\n"
        "<code>/aitext your text here</code>"
    )

def _extract_text(msg, args: list[str]) -> str:
    if args:
        return " ".join(args).strip()
    reply = msg.reply_to_message
    if reply:
        text = reply.text or reply.caption or ""
        return text.strip()
    return ""

async def neoxr_get(endpoint: str, params: dict | None = None, timeout: int = 30):
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

def _fmt_number(value, default="-") -> str:
    if value is None:
        return default
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)

def _fmt_list(items, limit: int = 10) -> str:
    if not isinstance(items, list) or not items:
        return "-"
    lines = []
    for i, item in enumerate(items[:limit], 1):
        lines.append(f"{i}. {esc(item)}")
    if len(items) > limit:
        lines.append(f"...and {len(items) - limit} more")
    return "\n".join(lines)

def _format_result(data: dict) -> str:
    special_sentences = data.get("specialSentences") or []
    special_indexes = data.get("specialIndexes") or []
    fake_percentage = data.get("fakePercentage")
    ai_words = data.get("aiWords")
    text_words = data.get("textWords")
    is_human = data.get("isHuman")

    indexes = ", ".join(str(x) for x in special_indexes) if isinstance(special_indexes, list) and special_indexes else "-"

    return (
        "<b>AI Text Detector</b>\n\n"
        f"<b>Human Score:</b> <code>{esc(_fmt_number(is_human))}%</code>\n"
        f"<b>AI Percentage:</b> <code>{esc(_fmt_number(fake_percentage))}%</code>\n"
        f"<b>AI Words:</b> <code>{esc(_fmt_number(ai_words))}</code>\n"
        f"<b>Total Words:</b> <code>{esc(_fmt_number(text_words))}</code>\n"
        f"<b>Special Indexes:</b> <code>{esc(indexes)}</code>\n\n"
        f"📝 <b>Special Sentences:</b>\n{_fmt_list(special_sentences)}"
    )

async def aitext_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

    msg = update.effective_message
    if not msg:
        return

    text = _extract_text(msg, context.args or [])
    if not text:
        return await msg.reply_text(_usage_text(), parse_mode="HTML", reply_to_message_id=msg.message_id)

    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    status = await msg.reply_text(
        "<b>Analyzing text...</b>",
        parse_mode="HTML",
        reply_to_message_id=msg.message_id,
    )

    ok, payload = await neoxr_get("ai-detector", {"text": text})
    if not ok:
        return await status.edit_text(
            f"<b>AI text detection failed</b>\n\n<code>{esc(payload)}</code>",
            parse_mode="HTML",
        )

    if not isinstance(payload, dict):
        return await status.edit_text("Invalid API response.")

    if not payload.get("status"):
        err = payload.get("message") or payload.get("msg") or payload.get("data") or "AI text detection failed."
        return await status.edit_text(
            f"<b>AI text detection failed</b>\n\n<code>{esc(err)}</code>",
            parse_mode="HTML",
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        return await status.edit_text("AI text detector data is empty.")

    await status.edit_text(
        _format_result(data),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )