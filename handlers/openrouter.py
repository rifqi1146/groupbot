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
from rag.retriever import retrieve_context
from rag.prompt import build_rag_prompt
from handlers.gsearch import google_search
from rag.loader import load_local_contexts

import aiohttp
import pytesseract
from PIL import Image
from bs4 import BeautifulSoup

from telegram import Update
from telegram.ext import ContextTypes

from utils.ai_utils import (
    split_message,
    sanitize_ai_output,
    extract_text_from_photo,
)

from utils.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    MODEL_THINK,
    OPENROUTER_IMAGE_MODEL,
)
  
from utils.http import get_http_session

#core function
async def openrouter_generate_image(prompt: str) -> list[str]:
    session = await get_http_session()

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com",
        "X-Title": "KiyoshiBot",
    }

    payload = {
        "model": OPENROUTER_IMAGE_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "extra_body": {
            "modalities": ["image", "text"]
        }
    }

    async with session.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(await resp.text())

        data = await resp.json()

    images: list[str] = []
    msg = data.get("choices", [{}])[0].get("message", {})

    for img in msg.get("images", []):
        url = img.get("image_url", {}).get("url")
        if isinstance(url, str):
            images.append(url)

    return images
    
def data_url_to_bytesio(data_url: str) -> BytesIO:
    header, encoded = data_url.split(",", 1)
    data = base64.b64decode(encoded)
    bio = BytesIO(data)
    bio.seek(0)
    return bio
    
async def openrouter_ask_think(user_prompt: str) -> str:
    # 1. ambil konteks dari dokumen lokal
    contexts = await retrieve_context(
        user_prompt,
        LOCAL_CONTEXTS
    )

    # 2. fallback ke google search kalau lokal kosong
    if not contexts:
        try:
            ok, results = await google_search(user_prompt, limit=5)
            if ok and results:
                contexts = [
                    f"[WEB]\n{r['title']}\n{r['snippet']}\nSumber: {r['link']}"
                    for r in results
                ]
        except Exception:
            pass

    # 3. build RAG prompt
    rag_prompt = build_rag_prompt(user_prompt, contexts)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com",
        "X-Title": "KiyoshiBot",
    }

    payload = {
        "model": MODEL_THINK,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Kamu adalah KiyoshiBot.\n"
                    "- Jika DATA berisi aturan bot atau dokumentasi, WAJIB gunakan itu.\n"
                    "- Jangan mengarang aturan sendiri.\n"
                    "- Jika DATA kosong, boleh pakai pengetahuan umum atau web dan jelaskan sumbernya.\n"
                    "- Jawab pakai Bahasa Indonesia santai ala gen z."
                ),
            },
            {
                "role": "user",
                "content": rag_prompt,
            },
        ],
    }

    session = await get_http_session()
    async with session.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(await resp.text())

        data = await resp.json()

    return data["choices"][0]["message"]["content"].strip()

#askcmd
async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if context.args and context.args[0].lower() == "img":
        prompt = " ".join(context.args[1:]).strip()

        if not prompt:
            return await msg.reply_text(
                "🎨 <b>Generate Image</b>\n\n"
                "Contoh:\n"
                "<code>/ask img anime girl cyberpunk</code>",
                parse_mode="HTML"
            )

        status = await msg.reply_text(
            "🎨 <i>Lagi bikin gambar...</i>",
            parse_mode="HTML"
        )

        try:
            images = await openrouter_generate_image(prompt)

            if not images:
                await status.delete()
                return await msg.reply_text("❌ Gagal generate gambar.")

            await status.delete()

            for url in images:
                try:

                    if isinstance(url, str) and url.startswith("data:image"):
                        bio = data_url_to_bytesio(url)
                        await msg.reply_photo(photo=bio)
                    else:
                        await msg.reply_photo(photo=url)
                except Exception:
                    continue

        except Exception as e:
            try:
                await status.delete()
            except:
                pass

            await msg.reply_text(
                f"<b>❌ Gagal generate image</b>\n"
                f"<code>{html.escape(str(e))}</code>",
                parse_mode="HTML"
            )

        return

    user_prompt = ""
    if context.args:
        user_prompt = " ".join(context.args).strip()
    elif msg.reply_to_message:
        if msg.reply_to_message.text:
            user_prompt = msg.reply_to_message.text.strip()
        elif msg.reply_to_message.caption:
            user_prompt = msg.reply_to_message.caption.strip()

    ocr_text = ""

    status_msg = await msg.reply_text(
        "🧠 <i>Memproses...</i>",
        parse_mode="HTML"
    )

    if msg.reply_to_message and msg.reply_to_message.photo:
        await status_msg.edit_text(
            "👁️ <i>Lagi baca gambar...</i>",
            parse_mode="HTML"
        )

        photo = msg.reply_to_message.photo[-1]
        ocr_text = await extract_text_from_photo(
            context.bot,
            photo.file_id
        )

        if not ocr_text:
            return await status_msg.edit_text(
                "❌ <b>Teks di gambar tidak terbaca.</b>",
                parse_mode="HTML"
            )

        await status_msg.edit_text(
            "🧠 <i>Lagi mikir jawabannya...</i>",
            parse_mode="HTML"
        )

    if not user_prompt and not ocr_text:
        return await status_msg.edit_text(
            "<b>❓ Ask AI</b>\n\n"
            "<b>Contoh:</b>\n"
            "<code>/ask jelaskan relativitas</code>\n"
            "<code>/ask img anime cyberpunk</code>\n"
            "<i>atau reply pesan / foto lalu ketik /ask</i>",
            parse_mode="HTML"
        )

    if ocr_text and user_prompt:
        final_prompt = (
            "Berikut teks hasil OCR dari sebuah gambar:\n\n"
            f"{ocr_text}\n\n"
            "Pertanyaan user terkait gambar tersebut:\n"
            f"{user_prompt}"
        )
    elif ocr_text:
        final_prompt = (
            "Berikut teks hasil OCR dari sebuah gambar. "
            "Tolong jelaskan atau ringkas isinya dengan jelas:\n\n"
            f"{ocr_text}"
        )
    else:
        final_prompt = user_prompt

    try:
        raw = await openrouter_ask_think(final_prompt)
        clean = sanitize_ai_output(raw)
        chunks = split_message(clean, max_length=3800)

        await status_msg.edit_text(
            chunks[0],
            parse_mode="HTML"
        )

        for ch in chunks[1:]:
            await asyncio.sleep(0.25)
            await msg.reply_text(ch, parse_mode="HTML")

    except Exception as e:
        await status_msg.edit_text(
            f"<b>❌ Gagal</b>\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
    