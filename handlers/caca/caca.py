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
from utils.system_prompt import split_message, sanitize_ai_output, PERSONAS
from utils.http import get_http_session

from database import caca_db
from utils import caca_memory


logger = logging.getLogger(__name__)

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_AUTH_TOKEN = os.getenv("CLOUDFLARE_AUTH_TOKEN", "").strip()
CLOUDFLARE_MODEL = "@cf/moonshotai/kimi-k2.5"
CLOUDFLARE_TIMEOUT = int(os.getenv("CLOUDFLARE_TIMEOUT", "60"))

_EMOS = ["🌸", "💖", "🧸", "🎀", "✨", "🌟", "💫"]
_URL_RE = re.compile(r"(https?://[^\s'\"<>]+)", re.I)


def _emo():
    return random.choice(_EMOS)


def _parse_html(html_text: str) -> Optional[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "iframe", "noscript"]):
        t.decompose()

    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.text) > 30]
    return ("\n\n".join(ps))[:12000] or None


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
    except Exception:
        pass


async def meta_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _cleanup_memory()

    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id
    chat = update.effective_chat
    em = _emo()

    if chat and chat.type in ("group", "supergroup"):
        groups = await caca_db.load_groups()
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
                if ok:
                    if results:
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
                    else:
                        logger.info(f"Google Search returned no results for query: {prompt}")
                else:
                    logger.warning(f"Google Search failed for query '{prompt}': {results}")
            except Exception as e:
                logger.error(f"Unexpected error during Google Search for '{prompt}': {e}", exc_info=True)

        history = await caca_memory.get_history(user_id)

        mode = caca_db.get_mode(user_id)
        system_prompt = PERSONAS.get(mode, PERSONAS["default"])

        messages = [{"role": "system", "content": system_prompt}] + history + [
            {
                "role": "user",
                "content": (f"{search_context}\n\n{prompt}" if search_context else prompt),
            }
        ]

        if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_AUTH_TOKEN:
            raise RuntimeError("CLOUDFLARE_ACCOUNT_ID atau CLOUDFLARE_AUTH_TOKEN belum diset")

        session = await get_http_session()
        async with session.post(
            f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_MODEL}",
            headers={"Authorization": f"Bearer {CLOUDFLARE_AUTH_TOKEN}"},
            json={
                "messages": messages,
                "temperature": 0.9,
                "max_completion_tokens": 2048,
                "chat_template_kwargs": {
                    "enable_thinking": False,
                    "clear_thinking": True,
                },
            },
            timeout=aiohttp.ClientTimeout(total=CLOUDFLARE_TIMEOUT),
        ) as r:
            data = await r.json(content_type=None)

            if r.status >= 400:
                raise RuntimeError(
                    data.get("errors", [{}])[0].get("message")
                    or data.get("error")
                    or f"Cloudflare HTTP {r.status}"
                )

            if data.get("success") is False:
                raise RuntimeError(
                    data.get("errors", [{}])[0].get("message")
                    or data.get("error")
                    or "Cloudflare request failed"
                )

            result = data.get("result") or {}

            raw = (
                result.get("response")
                or result.get("output_text")
                or result.get("text")
                or (
                    result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content")
                    if isinstance(result.get("choices"), list) and result.get("choices")
                    else None
                )
            )

            if not raw:
                raise RuntimeError(f"Unexpected Cloudflare response: {data}")

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
    loop = asyncio.get_event_loop()
    loop.create_task(caca_memory.init())
    loop.create_task(caca_db.init())