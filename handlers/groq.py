import re
import json
import time
import html
import random
import asyncio
import logging
from typing import List, Tuple, Optional

import aiohttp
from bs4 import BeautifulSoup

from telegram import Update
from telegram.ext import ContextTypes

from rag.retriever import retrieve_context
from rag.prompt import build_rag_prompt
from rag.loader import load_local_contexts
from handlers.gsearch import google_search

LOCAL_CONTEXTS = load_local_contexts()

from utils.ai_utils import (
    split_message,
    sanitize_ai_output,
)

from utils.config import (
    GROQ_MEMORY,
    COOLDOWN,
    GROQ_TIMEOUT,
    GROQ_MODEL,
    GROQ_BASE,
    GROQ_KEY,
)

from utils.http import get_http_session

GROQ_MEMORY = {}        
_GROQ_ACTIVE_USERS = {}   


#groq
_EMOS = ["🌸", "💖", "🧸", "🎀", "✨", "🌟", "💫"]
def _emo(): return random.choice(_EMOS)

_last_req = {}

def _can(uid: int) -> bool:
    now = time.time()
    if now - _last_req.get(uid, 0) < COOLDOWN:
        return False
    _last_req[uid] = now
    return True
        
#helper
async def build_groq_rag_prompt(
    user_prompt: str,
    use_search: bool = False
) -> str:
    # ambil konteks lokal
    contexts = await retrieve_context(
        user_prompt,
        LOCAL_CONTEXTS,
        top_k=3
    )

    # optional google search
    if use_search:
        try:
            ok, results = await google_search(user_prompt, limit=5)
            if ok and results:
                web_ctx = [
                    f"[WEB]\n{r['title']}\n{r['snippet']}\nSumber: {r['link']}"
                    for r in results
                ]
                contexts += web_ctx
        except Exception:
            pass

    # build final RAG prompt
    return build_rag_prompt(user_prompt, contexts)

#helper url
_URL_RE = re.compile(
    r"(https?://[^\s'\"<>]+)", re.IGNORECASE
)

def _find_urls(text: str) -> List[str]:
    if not text:
        return []
    return _URL_RE.findall(text)

async def _fetch_and_extract_article(
    url: str,
    timeout: int = 15
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch url and return (title, cleaned_text) or (None, None) on failure.
    Cleans common ad/irrelevant elements.
    """
    try:
        session = await get_http_session()
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status != 200:
                return None, None
            html_text = await resp.text(errors="ignore")

        soup = BeautifulSoup(html_text, "html.parser")

        for tag in soup(["script", "style", "noscript", "iframe", "svg", "canvas", "picture"]):
            tag.decompose()

        ad_indicators = [
            "ad", "ads", "advert", "sponsor", "cookie", "consent", "subscription",
            "subscribe", "paywall", "related", "promo", "banner", "popup", "overlay"
        ]
        for tag in soup.find_all(True):
            try:
                idv = (tag.get("id") or "").lower()
                clsv = " ".join(tag.get("class") or []).lower()
                role = (tag.get("role") or "").lower()
                aria = (tag.get("aria-label") or "").lower()
                combined = " ".join([idv, clsv, role, aria])
                if any(ind in combined for ind in ad_indicators):
                    tag.decompose()
            except Exception:
                continue

        title = None
        try:
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
        except Exception:
            title = None

        article_node = soup.find("article") or soup.find("main")

        if not article_node:
            candidates = soup.find_all(["div", "section"], limit=40)
            best = None
            best_count = 0
            for cand in candidates:
                try:
                    pcount = len(cand.find_all("p"))
                    if pcount > best_count:
                        best_count = pcount
                        best = cand
                except Exception:
                    continue
            if best_count >= 2:
                article_node = best

        paragraphs = []
        if article_node:
            for p in article_node.find_all("p"):
                txt = p.get_text(separator=" ", strip=True)
                if txt and len(txt) > 20:
                    paragraphs.append(txt)
        else:
            for p in soup.find_all("p"):
                txt = p.get_text(separator=" ", strip=True)
                if txt and len(txt) > 20:
                    paragraphs.append(txt)

        if not paragraphs:
            meta_desc = (
                soup.find("meta", attrs={"name": "description"})
                or soup.find("meta", attrs={"property": "og:description"})
            )
            if meta_desc and meta_desc.get("content"):
                paragraphs = [meta_desc.get("content").strip()]

        article_text = "\n\n".join(paragraphs).strip()
        if not article_text:
            return title, None

        if len(article_text) > 12000:
            article_text = article_text[:12000].rsplit("\n", 1)[0]

        article_text = re.sub(r"\s{2,}", " ", article_text).strip()

        return title, article_text

    except Exception:
        return None, None

async def _typing_loop(bot, chat_id, stop_event: asyncio.Event):
    try:
        while not stop_event.is_set():
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
    except Exception:
        pass
        
# handler
async def groq_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id
    chat_id = update.effective_chat.id
    em = _emo()

    prompt = ""
    use_search = False

    if msg.text and msg.text.startswith("/groq"):
        if context.args and context.args[0].lower() == "search":
            use_search = True
            prompt = " ".join(context.args[1:]).strip()
        else:
            prompt = " ".join(context.args).strip()

        GROQ_MEMORY.pop(user_id, None)
        _GROQ_ACTIVE_USERS.pop(user_id, None)

        if not prompt:
            return await msg.reply_text(
                f"{em} Gunakan:\n"
                "/groq <pertanyaan>\n"
                "/groq search <pertanyaan>\n"
                "atau reply jawaban Groq"
            )

    elif msg.reply_to_message:
        if user_id not in _GROQ_ACTIVE_USERS:
            return await msg.reply_text(
                "😒 Lu siapa?\n"
                "Gue belum ngobrol sama lu.\n"
                "Ketik /groq dulu.",
                parse_mode="HTML"
            )

        prompt = msg.text.strip()

    if not prompt:
        return

    if not _can(user_id):
        return await msg.reply_text(f"{em} ⏳ Sabar dulu ya…")

    stop = asyncio.Event()
    typing = asyncio.create_task(
        _typing_loop(context.bot, chat_id, stop)
    )

    try:

        rag_prompt = await build_groq_rag_prompt(prompt, use_search)

        urls = _find_urls(prompt)
        if urls:
            _, article = await _fetch_and_extract_article(urls[0])
            if article:
                rag_prompt = (
                    "Artikel sumber:\n\n"
                    f"{article}\n\n"
                    "Ringkas dengan bullet point + kesimpulan."
                )

        history = GROQ_MEMORY.get(user_id, {"history": []})["history"]

        messages = [
            {
                "role": "system",
                "content": (
                    "Gunakan DATA jika ada (RAG / web / artikel).\n"
                    "Jika dari web, anggap itu informasi TERBARU.\n"
                    "Jangan mengarang fakta.\n"
                    "Jawab singkat, jelas, Bahasa Indonesia santai ala gen z."
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
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 0.9,
                "top_p": 0.95,
                "max_tokens": 2048,
            },
            timeout=aiohttp.ClientTimeout(total=GROQ_TIMEOUT),
        ) as resp:
            data = await resp.json()

            if "choices" not in data or not data["choices"]:
                raise RuntimeError("Groq response invalid")

            raw = data["choices"][0]["message"]["content"]

        history += [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw},
        ]

        GROQ_MEMORY[user_id] = {"history": history}

        stop.set()
        typing.cancel()

        sent = await msg.reply_text(
            split_message(sanitize_ai_output(raw), 4000)[0],
            parse_mode="HTML"
        )

        _GROQ_ACTIVE_USERS[user_id] = sent.message_id

    except Exception as e:
        stop.set()
        typing.cancel()
        GROQ_MEMORY.pop(user_id, None)
        _GROQ_ACTIVE_USERS.pop(user_id, None)
        await msg.reply_text(f"{em} ❌ Error: {html.escape(str(e))}")