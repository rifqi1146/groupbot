import os
import re
import json
import time
import html
import base64
import random
import asyncio
import logging
from io import BytesIO
from typing import List, Tuple, Optional

import aiohttp
import pytesseract
from PIL import Image
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
    extract_text_from_photo,
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

def ocr_image(path: str) -> str:
    try:
        text = pytesseract.image_to_string(
            Image.open(path),
            lang="ind+eng"
        )
        return text.strip()
    except Exception:
        return ""
        
#helper
async def build_groq_rag_prompt(
    user_prompt: str,
    use_search: bool = False
) -> str:
    # 1. ambil konteks lokal
    contexts = await retrieve_context(
        user_prompt,
        LOCAL_CONTEXTS,
        top_k=3
    )

    # 2. optional google search
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

    # 3. build final RAG prompt
    return build_rag_prompt(user_prompt, contexts)

def _extract_prompt_from_update(update, context) -> str:
    """
    Try common sources:
     - context.args (list) -> join
     - command text after dollar (update.message.text)
     - reply_to_message.text or caption
    Returns empty string if none found.
    """
    try:
        if getattr(context, "args", None):
            joined = " ".join(context.args).strip()
            if joined:
                return joined
    except Exception:
        pass

    try:
        msg = update.message
        if msg and getattr(msg, "text", None):
            txt = msg.text.strip()
           
            if txt.startswith("$"):
                parts = txt[1:].strip().split(maxsplit=1)
                if len(parts) > 1:
                    return parts[1].strip()
    except Exception:
        pass

    try:
        if msg and getattr(msg, "reply_to_message", None):
            rm = msg.reply_to_message
            if getattr(rm, "text", None):
                return rm.text.strip()
            if getattr(rm, "caption", None):
                return rm.caption.strip()
    except Exception:
        pass

    return ""
    
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


# handler
async def groq_query(update, context):
    em = _emo()
    msg = update.message
    if not msg or not msg.from_user:
        return

    chat_id = update.effective_chat.id
    prompt = ""
    use_search = False

    if msg.text and msg.text.startswith("/groq"):
        if context.args and context.args[0].lower() == "search":
            use_search = True
            prompt = " ".join(context.args[1:]).strip()
        else:
            prompt = " ".join(context.args).strip() if context.args else ""

        GROQ_MEMORY.pop(chat_id, None)
        _GROQ_ACTIVE_USERS.pop(chat_id, None)

        if not prompt:
            return await msg.reply_text(
                f"{em} Gunakan:\n"
                "/meta <pertanyaan>\n"
                "/meta search <pertanyaan>\n"
                "atau reply jawaban Meta untuk lanjut"
            )

    elif msg.reply_to_message:
        last_mid = _GROQ_ACTIVE_USERS.get(chat_id)
        if not last_mid:
            return
        if msg.reply_to_message.message_id != last_mid:
            return

        prompt = msg.text.strip() if msg.text else ""

    if not prompt:
        return

    uid = msg.from_user.id
    if not _can(uid):
        return await msg.reply_text(f"{em} ⏳ Sabar dulu ya {COOLDOWN}s…")

    status_msg = await msg.reply_text(f"{em} ✨ Lagi mikir jawaban...")

    if msg.reply_to_message and msg.reply_to_message.photo:
        await status_msg.edit_text(f"{em} 👀 Lagi baca gambar...")
        photo = msg.reply_to_message.photo[-1]
        file = await photo.get_file()
        img_path = await file.download_to_drive()

        ocr_text = ocr_image(img_path)
        try:
            os.remove(img_path)
        except Exception:
            pass

        if not ocr_text:
            return await status_msg.edit_text(f"{em} ❌ Teks gambar ga kebaca.")

        prompt = (
            "Berikut teks hasil OCR dari gambar:\n\n"
            f"{ocr_text}\n\n"
            f"Pertanyaan user:\n{prompt}"
        )

    try:
        rag_prompt = await build_groq_rag_prompt(prompt, use_search)
    except Exception:
        rag_prompt = prompt

    urls = _find_urls(prompt)
    if urls:
        await status_msg.edit_text(f"{em} 🔎 Lagi baca artikel...")
        title, text = await _fetch_and_extract_article(urls[0])
        if text:
            rag_prompt = (
                "Artikel sumber:\n\n"
                f"{text}\n\n"
                "Ringkas dengan bullet point + kesimpulan."
            )

    history = GROQ_MEMORY.get(chat_id, [])
    history.append({"role": "user", "content": rag_prompt})

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
    ] + history

    try:
        session = await get_http_session()
        async with session.post(
            f"{GROQ_BASE}/chat/completions",
            json={
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 0.9,
                "top_p": 0.95,
                "max_tokens": 2048,
            },
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=GROQ_TIMEOUT),
        ) as resp:
            data = await resp.json()
            raw = data["choices"][0]["message"]["content"]

        history.append({"role": "assistant", "content": raw})
        GROQ_MEMORY[chat_id] = history[-10:]

        clean = sanitize_ai_output(raw)
        chunks = split_message(clean, 4000)

        await status_msg.edit_text(f"{em} {chunks[0]}")
        _GROQ_ACTIVE_USERS[chat_id] = status_msg.message_id

        for ch in chunks[1:]:
            await msg.reply_text(ch)

    except Exception as e:
        GROQ_MEMORY.pop(chat_id, None)
        _GROQ_ACTIVE_USERS.pop(chat_id, None)
        await status_msg.edit_text(f"{em} ❌ Error: {e}")
