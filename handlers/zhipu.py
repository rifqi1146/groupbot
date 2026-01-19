import os
import re
import html
import asyncio
from io import BytesIO
from typing import List, Dict

import aiohttp
import pytesseract
from PIL import Image
from telegram import Update
from telegram.ext import ContextTypes

from rag.retriever import retrieve_context
from rag.prompt import build_rag_prompt
from rag.loader import load_local_contexts
from handlers.gsearch import google_search

from utils.ai_utils import (
    split_message,
    sanitize_ai_output,
    extract_text_from_photo,
)

from utils.http import get_http_session
from utils.config import (
    ZHIPU_MODEL,
    ZHIPU_URL,
    ZHIPU_API_KEY,
    ZHIPU_IMAGE_SIZE,
    ZHIPU_IMAGE_MODEL,
    ZHIPU_IMAGE_URL,
)

LOCAL_CONTEXTS = load_local_contexts()
_ZHIPU_ACTIVE_USERS = {}
ZHIPU_MAX_TOKENS = 2048
ZHIPU_TEMPERATURE = 0.95
ZHIPU_TOP_P = 0.7
ZHIPU_MEMORY_LIMIT = 10

SYSTEM_PROMPT = (
    "- Jika konteks berasal dari pencarian web, anggap itu informasi TERBARU."
    "- Jika DATA berisi aturan bot atau dokumentasi, WAJIB gunakan itu."
    "- Jangan mengarang aturan sendiri."
    "- Jika DATA kosong, boleh pakai pengetahuan umum atau web dan jelaskan sumbernya."
    "- Jawab pakai Bahasa Indonesia santai ala gen z."
)

_USER_MEMORY: Dict[int, List[dict]] = {}

async def build_zhipu_rag_prompt(
    user_prompt: str,
    use_search: bool = False
) -> str:
    # ambil konteks lokal
    contexts = await retrieve_context(
        user_prompt,
        LOCAL_CONTEXTS,
        top_k=3
    )

    # google search
    if use_search:
        try:
            ok, results = await google_search(user_prompt, limit=5)
            if ok and results:
                web_ctx = [
                    f"[WEB]\n{r['title']}\n{r['snippet']}\nSumber: {r['link']}"
                    for r in results
                ]
                contexts = contexts + web_ctx
        except Exception:
            pass

    # build prompt RAG
    return build_rag_prompt(user_prompt, contexts)
    
async def zhipu_chat(user_id: int, prompt: str) -> str:
    if not ZHIPU_API_KEY:
        raise RuntimeError("ZHIPU_API_KEY belum diset")

    history = _USER_MEMORY.get(user_id, [])
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": ZHIPU_MODEL,
        "messages": messages,
        "max_tokens": ZHIPU_MAX_TOKENS,
        "temperature": ZHIPU_TEMPERATURE,
        "top_p": ZHIPU_TOP_P,
    }

    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json",
    }

    session = await get_http_session()
    async with session.post(
        ZHIPU_URL,
        headers=headers,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(await resp.text())
        data = await resp.json()

    answer = data["choices"][0]["message"]["content"].strip()

    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": answer})
    _USER_MEMORY[user_id] = history[-ZHIPU_MEMORY_LIMIT:]

    return answer

async def zhipu_generate_image(prompt: str) -> BytesIO:
    if not ZHIPU_API_KEY:
        raise RuntimeError("ZHIPU_API_KEY belum diset")

    payload = {
        "model": ZHIPU_IMAGE_MODEL,
        "prompt": prompt,
        "size": ZHIPU_IMAGE_SIZE,
    }

    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json",
    }

    session = await get_http_session()
    async with session.post(
        ZHIPU_IMAGE_URL,
        headers=headers,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(await resp.text())
        data = await resp.json()

    image_url = data["data"][0]["url"]

    async with session.get(image_url) as img_resp:
        if img_resp.status != 200:
            raise RuntimeError("Gagal download gambar")
        content = await img_resp.read()

    bio = BytesIO(content)
    bio.name = "zhipu.png"
    bio.seek(0)
    return bio
    
async def zhipu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id

    use_search = False
    prompt = ""

    if context.args:
        if context.args[0].lower() == "search":
            use_search = True
            prompt = " ".join(context.args[1:]).strip()
        else:
            prompt = " ".join(context.args).strip()

        _USER_MEMORY.pop(user_id, None)
        _ZHIPU_ACTIVE_USERS.pop(user_id, None)

    elif msg.reply_to_message:
        last_mid = _ZHIPU_ACTIVE_USERS.get(user_id)
        if not last_mid:
            return
        if msg.reply_to_message.message_id != last_mid:
            return

        if msg.text:
            prompt = msg.text.strip()
        elif msg.caption:
            prompt = msg.caption.strip()

    if not prompt:
        return await msg.reply_text(
            "<b>🤖 GLM AI</b>\n\n"
            "<code>/glm jelaskan relativitas</code>\n"
            "<code>/glm search hasil pertandingan Indonesia vs Malaysia</code>\n"
            "<i>atau reply jawaban GLM untuk lanjut</i>",
            parse_mode="HTML"
        )

    status = await msg.reply_text("🧠 <i>Lagi mikir...</i>", parse_mode="HTML")

    ocr_text = ""
    if msg.reply_to_message and msg.reply_to_message.photo:
        await status.edit_text("👁️ <i>Lagi baca gambar...</i>", parse_mode="HTML")
        photo = msg.reply_to_message.photo[-1]
        ocr_text = await extract_text_from_photo(context.bot, photo.file_id)

        if not ocr_text:
            _ZHIPU_ACTIVE_USERS.pop(user_id, None)
            return await status.edit_text(
                "❌ <b>Teks di gambar tidak terbaca</b>",
                parse_mode="HTML"
            )

    if ocr_text:
        prompt = (
            "Berikut teks hasil OCR dari gambar:\n\n"
            f"{ocr_text}\n\n"
            "Pertanyaan user:\n"
            f"{prompt}"
        )

    # Build RAG
    try:
        final_prompt = await build_zhipu_rag_prompt(
            prompt,
            use_search=use_search
        )
    except Exception:
        final_prompt = prompt

    try:
        raw = await zhipu_chat(user_id, final_prompt)
        clean = sanitize_ai_output(raw)
        chunks = split_message(clean)

        _ZHIPU_ACTIVE_USERS[user_id] = status.message_id

        await status.edit_text(chunks[0], parse_mode="HTML")
        for ch in chunks[1:]:
            await asyncio.sleep(0.25)
            await msg.reply_text(ch, parse_mode="HTML")

    except Exception as e:
        _USER_MEMORY.pop(user_id, None)
        _ZHIPU_ACTIVE_USERS.pop(user_id, None)
        await status.edit_text(
            f"<b>❌ Error</b>\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
        
async def zhipuimg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "<b>🎨 Zhipu Image</b>\n\n"
            "Contoh:\n"
            "<code>/img kucing lucu di jendela</code>",
            parse_mode="HTML"
        )

    prompt = " ".join(context.args).strip()

    status = await msg.reply_text(
        "🎨 <i>Lagi bikin gambar...</i>",
        parse_mode="HTML"
    )

    try:
        img = await zhipu_generate_image(prompt)
        await status.delete()
        await msg.reply_photo(photo=img)

    except Exception as e:
        await status.edit_text(
            f"<b>❌ Gagal generate image</b>\n"
            f"<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )