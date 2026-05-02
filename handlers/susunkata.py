import html
import json
import aiohttp
import asyncio
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from handlers.join import require_join_or_block
from utils.http import get_http_session
from utils.config import NEOXR_API_KEY

log = logging.getLogger(__name__)
BASE_URL = "https://api.neoxr.eu/api"
GAME_TTL = 300
SUSUNKATA_GAMES = {}

def esc(text) -> str:
    return html.escape(str(text or "-"))

def _game_key(chat_id: int, message_id: int) -> tuple[int, int]:
    return int(chat_id), int(message_id)

def _normalize_answer(text: str) -> str:
    return "".join(str(text or "").upper().split())

def _cleanup_games():
    now = time.time()
    expired = [key for key, game in SUSUNKATA_GAMES.items() if now - game.get("created_at", now) > GAME_TTL]
    for key in expired:
        SUSUNKATA_GAMES.pop(key, None)

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

def _format_question(data: dict) -> str:
    tipe = data.get("tipe")
    pertanyaan = data.get("pertanyaan")
    return (
        "<b>Susun Kata</b>\n\n"
        f"<b>Type:</b> <code>{esc(tipe)}</code>\n"
        f"<b>Question:</b> <code>{esc(pertanyaan)}</code>\n\n"
        "Reply to this message with the correct word."
    )

async def susunkata_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return

    _cleanup_games()
    ok, payload = await neoxr_get("whatword")
    if not ok:
        return await msg.reply_text(
            f"<b>Failed to get question</b>\n\n<code>{esc(payload)}</code>",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )
    if not isinstance(payload, dict) or not payload.get("status"):
        err = payload.get("message") or payload.get("msg") or "Failed to get question."
        return await msg.reply_text(
            f"<b>Failed to get question</b>\n\n<code>{esc(err)}</code>",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        return await msg.reply_text("Question data is empty.", reply_to_message_id=msg.message_id)

    answer = _normalize_answer(data.get("jawaban"))
    if not answer:
        return await msg.reply_text("Answer data is empty.", reply_to_message_id=msg.message_id)

    sent = await msg.reply_text(
        _format_question(data),
        parse_mode="HTML",
        reply_to_message_id=msg.message_id,
    )
    SUSUNKATA_GAMES[_game_key(chat.id, sent.message_id)] = {
        "answer": answer,
        "raw_answer": str(data.get("jawaban") or "").strip(),
        "question": str(data.get("pertanyaan") or "").strip(),
        "type": str(data.get("tipe") or "").strip(),
        "created_at": time.time(),
        "creator_id": msg.from_user.id if msg.from_user else 0,
    }

async def susunkata_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or not msg.reply_to_message:
        return
    if not msg.text:
        return

    _cleanup_games()
    key = _game_key(chat.id, msg.reply_to_message.message_id)
    game = SUSUNKATA_GAMES.get(key)
    if not game:
        return

    answer = _normalize_answer(msg.text)
    if answer != game["answer"]:
        return

    SUSUNKATA_GAMES.pop(key, None)
    await msg.reply_text(
        "<b>Correct Answer!</b>\n\n"
        f"<b>Winner:</b> <a href=\"tg://user?id={user.id}\">{esc(user.full_name)}</a>\n"
        f"<b>Answer:</b> <code>{esc(game['raw_answer'])}</code>",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=msg.message_id,
    )