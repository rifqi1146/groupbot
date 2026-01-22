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
from bs4 import BeautifulSoup

from telegram import Update
from telegram.ext import ContextTypes

from utils.ai_utils import (
    split_message,
    sanitize_ai_output,
)

from utils.config import (
    GEMINI_API_KEY,
)
  
from utils.http import get_http_session
from utils.storage import load_json_file, save_json_file

from rag.retriever import retrieve_context
from rag.prompt import build_rag_prompt
from rag.loader import load_local_contexts

LOCAL_CONTEXTS = load_local_contexts()
AI_MEMORY = {}
_AI_ACTIVE_USERS = {}

#gemini
async def _typing_loop(bot, chat_id, stop_event: asyncio.Event):
    try:
        while not stop_event.is_set():
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
    except Exception:
        pass
        
async def build_ai_prompt(chat_id: str, user_prompt: str) -> str:
    history = AI_MEMORY.get(chat_id, [])

    lines = []
    for h in history:
        lines.append(f"User: {h['user']}")
        lines.append(f"AI: {h['ai']}")

    # RAG lokal
    try:
        contexts = await retrieve_context(
            user_prompt,
            LOCAL_CONTEXTS,
            top_k=3
        )
    except Exception:
        contexts = []

    if contexts:
        rag_block = "\n\n".join(contexts)
        lines.append("=== KONTEKS LOKAL ===")
        lines.append(rag_block)
        lines.append("=== END KONTEKS ===")

    lines.append(f"User: {user_prompt}")
    return "\n".join(lines)
    
async def ask_ai_gemini(prompt: str, model: str = "gemini-2.5-flash") -> (bool, str):
    if not GEMINI_API_KEY:
        return False, "API key Gemini belum diset."

    if not prompt:
        return False, "Tidak ada prompt."

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={GEMINI_API_KEY}"
    )

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "Gunakan DATA jika ada (RAG / Google search / artikel).\n"
                        "Jika dari Googke search, anggap itu informasi TERBARU.\n"
                        "Jangan mengarang fakta.\n"
                        "Jawab singkat, jelas, Bahasa Indonesia santai ala gen z."
                    )
                }
            ]
        },
        "tools": [
            {
                "google_search": {}
            }
        ],
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        session = await get_http_session()
        async with session.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60)
        ) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}: {await resp.text()}"

            data = await resp.json()

        candidates = data.get("candidates") or []
        if not candidates:
            return True, "Model merespon hasil."

        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return True, parts[0].get("text", "").strip()

        return True, json.dumps(candidates[0], ensure_ascii=False)

    except asyncio.TimeoutError:
        return False, "Timeout memanggil Gemini"
    except Exception as e:
        return False, f"Gagal memanggil Gemini: {e}"

#cmd
async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = update.message
    prompt = ""

    if msg.text and msg.text.startswith("/ai"):
        if context.args:
            prompt = " ".join(context.args)
        else:
            prompt = ""

        AI_MEMORY.pop(chat_id, None)
        _AI_ACTIVE_USERS.pop(chat_id, None)

        if not prompt:
            return await msg.reply_text(
                "Contoh:\n"
                "/ai apa itu relativitas?\n"
                "atau reply jawaban AI untuk lanjut"
            )

    elif msg.reply_to_message:
        last_mid = _AI_ACTIVE_USERS.get(chat_id)
        if not last_mid or msg.reply_to_message.message_id != last_mid:
            return
        prompt = msg.text or ""

    if not prompt:
        return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _typing_loop(context.bot, chat_id, stop_typing)
    )

    try:
        final_prompt = await build_ai_prompt(chat_id, prompt)

        ok, answer = await ask_ai_gemini(
            final_prompt,
            model="gemini-2.5-flash"
        )

        if not ok:
            raise RuntimeError(answer)

        clean = sanitize_ai_output(answer)
        chunks = split_message(clean, 4000)

        stop_typing.set()
        typing_task.cancel()

        await msg.reply_text(chunks[0], parse_mode="HTML")
        _AI_ACTIVE_USERS[chat_id] = msg.message_id + 1

        for part in chunks[1:]:
            await msg.reply_text(part, parse_mode="HTML")

        history = AI_MEMORY.get(chat_id, [])
        history.append({"user": prompt, "ai": clean})
        AI_MEMORY[chat_id] = history

    except Exception as e:
        stop_typing.set()
        typing_task.cancel()
        AI_MEMORY.pop(chat_id, None)
        _AI_ACTIVE_USERS.pop(chat_id, None)
        await msg.reply_text(f"❌ Error: {e}")