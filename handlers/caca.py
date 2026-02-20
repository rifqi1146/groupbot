import time
import re
import os
import asyncio
import random
import html
import logging
from typing import List, Optional

import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes

from handlers.gsearch import google_search
from utils.ai_utils import split_message, sanitize_ai_output, PERSONAS
from utils.config import GROQ_BASE, GROQ_KEY, GROQ_MODEL2, GROQ_TIMEOUT
from utils.http import get_http_session

from utils import caca_db
from utils import caca_memory


logger = logging.getLogger(__name__)


_EMOS = ["🌸", "💖", "🧸", "🎀", "✨", "🌟", "💫"]
_URL_RE = re.compile(r"(https?://[^\s'\"<>]+)", re.I)


def _emo():
    return random.choice(_EMOS)


def _find_urls(text: str) -> List[str]:
    return _URL_RE.findall(text) if text else []


async def _fetch_article(url: str) -> Optional[str]:
    try:
        session = await get_http_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                return None
            html_text = await r.text(errors="ignore")

        soup = BeautifulSoup(html_text, "html.parser")
        for t in soup(["script", "style", "iframe", "noscript"]):
            t.decompose()

        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.text) > 30]
        return ("\n\n".join(ps))[:12000] or None
    except Exception:
        return None


def _cleanup_memory():
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(caca_memory.cleanup())
    except Exception:
        pass


async def _typing_loop(bot, chat_id, stop: asyncio.Event):
    try:
        while not stop.is_set():
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)
    except Exception as e:
        logger.error(f"Error in typing loop: {e}")


async def meta_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _cleanup_memory()

    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id
    chat = update.effective_chat
    em = _emo()

    if chat and chat.type in ("group", "supergroup"):
        groups = caca_db.load_groups()
        if chat.id not in groups:
            return await msg.reply_text(
                "<b>Caca tidak tersedia di grup ini</b>",
                parse_mode="HTML"
            )

    prompt = ""
    use_search = False

    if msg.text and msg.text.startswith("/caca"):
        if context.args and context.args[0].lower() == "search":
            use_search = True
            prompt = " ".join(context.args[1:])
        else:
            prompt = " ".join(context.args)
            await caca_memory.clear(user_id)
            await caca_memory.clear_last_message_id(user_id)

        if not prompt.strip():
            return await msg.reply_text(
                f"{em} Pake gini:\n"
                "/caca <teks>\n"
                "/caca search <teks>\n"
                "atau reply jawaban gue 😒"
            )

    elif msg.reply_to_message:
        history = await caca_memory.get_history(user_id)
        if not history:
            return await msg.reply_text(
                "😒 Gue ga inget ngobrol sama lu.\n"
                "Ketik /caca dulu."
            )
        prompt = (msg.text or "").strip()

    if not prompt:
        return

    stop = asyncio.Event()
    typing = asyncio.create_task(_typing_loop(context.bot, chat.id, stop))

    try:
        search_context = ""

        if use_search:
            try:
                ok, results = await google_search(prompt, limit=5)
                if ok and results:
                    lines = []
                    for r in results:
                        lines.append(
                            f"- {r['title']}\n"
                            f"  {r['snippet']}\n"
                            f"  Sumber: {r['link']}"
                        )
                    search_context = (
                        "Ini hasil search, pake buat nambah konteks, anggap ini adalah sumber terbaru."
                        "Jawab tetap sebagai Caca.\n\n"
                        + "\n\n".join(lines)
                    )
            except Exception:
                pass

        history = await caca_memory.get_history(user_id)

        mode = caca_db.get_mode(user_id)
        system_prompt = PERSONAS.get(mode, PERSONAS["default"])

        messages = [{"role": "system", "content": system_prompt}] + history + [
            {
                "role": "user",
                "content": (f"{search_context}\n\n{prompt}" if search_context else prompt),
            }
        ]

        session = await get_http_session()
        async with session.post(
            f"{GROQ_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={
                "model": GROQ_MODEL2,
                "messages": messages,
                "temperature": 0.9,
                "max_tokens": 2048,
            },
            timeout=aiohttp.ClientTimeout(total=GROQ_TIMEOUT),
        ) as r:
            data = await r.json()
            raw = data["choices"][0]["message"]["content"]

        history += [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw},
        ]

        await caca_memory.set_history(user_id, history)

        stop.set()
        typing.cancel()

        chunks = split_message(sanitize_ai_output(raw), 4000)

        sent = None
        for i, chunk in enumerate(chunks):
            if i == 0:
                sent = await msg.reply_text(chunk, parse_mode="HTML")
            else:
                await msg.reply_text(chunk, parse_mode="HTML")

        if sent:
            await caca_memory.set_last_message_id(user_id, sent.message_id)

    except Exception as e:
        stop.set()
        typing.cancel()
        await caca_memory.clear(user_id)
        await caca_memory.clear_last_message_id(user_id)
        await msg.reply_text(f"{em} Error: {html.escape(str(e))}")


def init_background():
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(caca_memory.init())
        loop.create_task(caca_db.init())
    except Exception:
        pass