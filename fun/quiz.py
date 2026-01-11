import json
import time
import asyncio
import html
import random
import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session
from utils.config import (
    GROQ_MODEL,
    GROQ_BASE,
    GROQ_KEY,
)

QUIZ_TIMEOUT = 30

_ACTIVE_QUIZ = {}

_EMOS = ["🧠", "🎯", "🔥", "✨", "📚"]
def _emo(): 
    return random.choice(_EMOS)


async def _generate_question() -> dict:
    prompt = (
        "Buatkan 1 soal pilihan ganda pengetahuan umum "
        "Bahasa Indonesia.\n\n"
        "Format WAJIB JSON:\n"
        "{\n"
        '  "question": "...",\n'
        '  "options": {\n'
        '    "A": "...",\n'
        '    "B": "...",\n'
        '    "C": "...",\n'
        '    "D": "..."\n'
        "  },\n"
        '  "answer": "A"\n'
        "}\n\n"
        "Jangan beri teks lain selain JSON."
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Kamu adalah pembuat soal quiz Bahasa Indonesia."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.8,
        "max_tokens": 512
    }

    session = await get_http_session()
    async with session.post(
        f"{GROQ_BASE}/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type": "application/json",
        },
        timeout=aiohttp.ClientTimeout(total=20),
    ) as resp:
        if resp.status != 200:
            raise RuntimeError("Gagal generate soal")

        data = await resp.json()

    raw = data["choices"][0]["message"]["content"]
    return json.loads(raw)


async def _send_question(msg, quiz):
    q = quiz["data"]
    text = (
        f"{_emo()} <b>QUIZ</b>\n\n"
        f"<b>{html.escape(q['question'])}</b>\n\n"
        f"A. {html.escape(q['options']['A'])}\n"
        f"B. {html.escape(q['options']['B'])}\n"
        f"C. {html.escape(q['options']['C'])}\n"
        f"D. {html.escape(q['options']['D'])}\n\n"
        f"<i>Reply A / B / C / D</i>"
    )

    sent = await msg.reply_text(text, parse_mode="HTML")
    quiz["message_id"] = sent.message_id
    quiz["start"] = time.time()


async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    chat_id = update.effective_chat.id

    quiz = {
        "data": await _generate_question(),
        "start": time.time(),
        "message_id": None
    }

    _ACTIVE_QUIZ[chat_id] = quiz
    await _send_question(msg, quiz)


async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or not msg.reply_to_message:
        return

    chat_id = update.effective_chat.id
    quiz = _ACTIVE_QUIZ.get(chat_id)
    if not quiz:
        return

    if msg.reply_to_message.message_id != quiz.get("message_id"):
        return

    if time.time() - quiz["start"] > QUIZ_TIMEOUT:
        _ACTIVE_QUIZ.pop(chat_id, None)
        return await msg.reply_text("⏰ Waktu habis! Soal dilewati.")

    ans = msg.text.strip().upper()
    if ans not in ("A", "B", "C", "D"):
        return

    correct = quiz["data"]["answer"]

    if ans == correct:
        await msg.reply_text("✅ <b>Benar!</b>", parse_mode="HTML")
    else:
        await msg.reply_text(
            f"❌ Salah. Jawaban benar: <b>{correct}</b>",
            parse_mode="HTML"
        )

    try:
        quiz["data"] = await _generate_question()
        quiz["start"] = time.time()
        await _send_question(msg, quiz)
    except Exception:
        _ACTIVE_QUIZ.pop(chat_id, None)
        await msg.reply_text("❌ Gagal lanjut soal.")
        