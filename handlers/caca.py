import time
import re
import asyncio
import random
import html
from typing import List, Tuple, Optional

import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes

from rag.adalah_pokoknya.retriever import retrieve_context
from rag.adalah_pokoknya.prompt import build_rag_prompt
from rag.adalah_pokoknya.loader import load_local_contexts
from handlers.gsearch import google_search

from utils.ai_utils import split_message, sanitize_ai_output
from utils.config import (
    GROQ_BASE,
    GROQ_KEY,
    GROQ_MODEL2,
    GROQ_TIMEOUT,
    COOLDOWN,
)
from utils.http import get_http_session

LOCAL_CONTEXTS = load_local_contexts()

META_MEMORY = {}         # user_id -> {"history": [...], "last_used": ts}
_META_ACTIVE_USERS = {}  # user_id -> last_bot_message_id

MEMORY_EXPIRE = 60 * 60 * 24  # 24 jam

_EMOS = ["🌸", "💖", "🧸", "🎀", "✨", "🌟", "💫"]
_last_req = {}

def _emo():
    return random.choice(_EMOS)

def _can(uid: int) -> bool:
    now = time.time()
    if now - _last_req.get(uid, 0) < COOLDOWN:
        return False
    _last_req[uid] = now
    return True

def _cleanup_memory():
    now = time.time()
    expired = [
        uid for uid, v in META_MEMORY.items()
        if now - v["last_used"] > MEMORY_EXPIRE
    ]
    for uid in expired:
        META_MEMORY.pop(uid, None)
        _META_ACTIVE_USERS.pop(uid, None)

async def _typing_loop(bot, chat_id, stop_event: asyncio.Event):
    try:
        while not stop_event.is_set():
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
    except Exception:
        pass

_URL_RE = re.compile(r"(https?://[^\s'\"<>]+)", re.IGNORECASE)

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
        text = "\n\n".join(ps)[:12000]
        return text.strip() or None
    except Exception:
        return None

async def build_rag(user_prompt: str, use_search: bool) -> str:
    ctx = await retrieve_context(user_prompt, LOCAL_CONTEXTS, top_k=3)
    if use_search:
        try:
            ok, results = await google_search(user_prompt, limit=5)
            if ok:
                ctx += [
                    f"[WEB]\n{r['title']}\n{r['snippet']}\nSumber: {r['link']}"
                    for r in results
                ]
        except:
            pass
    return build_rag_prompt(user_prompt, ctx)

async def meta_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _cleanup_memory()

    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id
    chat_id = update.effective_chat.id
    em = _emo()
    prompt = ""
    use_search = False

    if msg.text and msg.text.startswith("/caca"):
        if context.args and context.args[0].lower() == "search":
            use_search = True
            prompt = " ".join(context.args[1:])
        else:
            prompt = " ".join(context.args)

        META_MEMORY.pop(user_id, None)
        _META_ACTIVE_USERS.pop(user_id, None)

        if not prompt.strip():
            return await msg.reply_text(
                f"{em} Pake gini:\n"
                "/caca <teks>\n"
                "/caca search <teks>\n"
                "atau reply jawaban gue 😒"
            )

    elif msg.reply_to_message:
        if user_id not in _META_ACTIVE_USERS:
            return await msg.reply_text(
                "😒 Gue ga inget pernah ngobrol sama lu.\n"
                "Ketik /caca dulu.",
                parse_mode="HTML"
            )
        prompt = msg.text.strip()

    if not prompt:
        return

    if not _can(user_id):
        return await msg.reply_text(f"{em} Sabar napa…")

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _typing_loop(context.bot, chat_id, stop_typing)
    )

    try:
        rag_prompt = await build_rag(prompt, use_search)

        urls = _find_urls(prompt)
        if urls:
            art = await _fetch_article(urls[0])
            if art:
                rag_prompt = f"Artikel:\n{art}\n\nJawab singkat & nyebelin."

        mem = META_MEMORY.get(user_id, {"history": []})
        history = mem["history"]

        messages = [
            {
                "role": "system",
                "content": (
                    "Lu adalah caca\n"
                    "Cewe yang ngeselin\n"
                    "Lu adalah cewe umur 20 tahun\n"
                    "Jawab selalu pakai emoji\n"
                    "Jangan pernah perkenalin diri lu secara lengkap, kecuali diminta\n"                    
                    "Kalo ada yg menyapa hai, jawab singkat saja, misal hai, lu jawab Gue Caca, mau apa lu? agak ngeselin gapapa\n"
                    "Jangan pernah perkenalin diri lu secara lengkap, kecuali diminta"
                ),
            }
        ] + history + [{"role": "user", "content": rag_prompt}]

        session = await get_http_session()
        async with session.post(
            f"{GROQ_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
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

        history.append({"role": "user", "content": rag_prompt})
        history.append({"role": "assistant", "content": raw})

        META_MEMORY[user_id] = {
            "history": history,
            "last_used": time.time(),
        }

        clean = sanitize_ai_output(raw)
        chunks = split_message(clean, 4000)

        stop_typing.set()
        typing_task.cancel()

        await msg.reply_text(chunks[0], parse_mode="HTML")
        _META_ACTIVE_USERS[user_id] = msg.message_id + 1

        for c in chunks[1:]:
            await msg.reply_text(c, parse_mode="HTML")

    except Exception as e:
        stop_typing.set()
        typing_task.cancel()
        META_MEMORY.pop(user_id, None)
        _META_ACTIVE_USERS.pop(user_id, None)
        await msg.reply_text(f"{em} Error: {html.escape(str(e))}")