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

from utils.ai_utils import (
    split_message,
    sanitize_ai_output,
    extract_text_from_photo,
)

from utils.config import (
    GEMINI_MODELS,
    GEMINI_API_KEY,
)
  
from utils.http import get_http_session
from utils.storage import load_json_file, save_json_file

AI_MODE_FILE = "data/ai_mode.json"

# ---- ai mode 
def load_ai_mode():
    return load_json_file(AI_MODE_FILE, {})
def save_ai_mode(data):
    save_json_file(AI_MODE_FILE, data)
_ai_mode = load_ai_mode()
    
#gemini
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
                        "Selalu Gunakan Google Search untuk mencari semua informasi. "
                        "Jika data tidak ditemukan, katakan secara jujur. "
                        "Jangan mengarang jawaban."
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
    chat_id = str(update.effective_chat.id)
    model_key = _ai_mode.get(chat_id, "flash")
    prompt = ""

    if context.args:
        first = context.args[0].lower()
        if first in GEMINI_MODELS:
            model_key = first
            prompt = " ".join(context.args[1:])
        else:
            prompt = " ".join(context.args)
    elif update.message.reply_to_message:
        prompt = update.message.reply_to_message.text or ""

    if not prompt:
        return await update.message.reply_text(
            f"Model default chat: {model_key.upper()}\n"
            "Contoh:\n"
            "/ai apa itu relativitas?\n"
            "/ai pro jelaskan apa itu jawa"
        )

    model_name = GEMINI_MODELS.get(model_key, GEMINI_MODELS["flash"])
    loading = await update.message.reply_text("⏳ Memproses...")

    ok, answer = await ask_ai_gemini(prompt, model=model_name)

    if not ok:
        try:
            await loading.edit_text(f"❗ Error: {answer}")
        except Exception:
            await update.message.reply_text(f"❗ Error: {answer}")
        return

    clean = sanitize_ai_output(answer)
    header = f"💡 Jawaban ({model_key.upper()})"
    full_text = f"{header}\n\n{clean}"

    chunks = split_message(clean, 4000)

    try:
        await loading.edit_text(chunks[0], parse_mode="HTML")
    except Exception:
        await update.message.reply_text(chunks[0], parse_mode="HTML")

    for part in chunks[1:]:
        await asyncio.sleep(0.25)
        await update.message.reply_text(part, parse_mode="HTML")
        
#default ai
async def setmodeai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Pilih mode AI:\n/setmodeai flash\n/setmodeai pro\n/setmodeai lite"
        )
    mode = context.args[0].lower()
    if mode not in GEMINI_MODELS:
        return await update.message.reply_text("Pilihan hanya: flash / pro / lite")
    chat_id = str(update.effective_chat.id)
    _ai_mode[chat_id] = mode
    save_ai_mode(_ai_mode)
    await update.message.reply_text(f"Default model AI untuk chat ini diset ke {mode.upper()} ✔️")

