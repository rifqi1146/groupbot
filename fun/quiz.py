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
QUIZ_TOTAL = 10

_ACTIVE_QUIZ = {}

_EMOS = ["🧠", "🎯", "🔥", "✨", "📚"]
def _emo():
    return random.choice(_EMOS)

_QUESTION_STYLES = [
    "definisi konsep",
    "sebab dan akibat",
    "logika sederhana",
    "kasus singkat",
    "fakta unik",
    "perbandingan",
    "tebakan ilmiah ringan",
]


async def _generate_question_bank() -> list:
    seed = random.randint(100000, 999999)
    style = random.choice(_QUESTION_STYLES)

    prompt = (
        f"[SEED:{seed}]\n"
        f"Gaya soal: {style}\n\n"
        "Buatkan 10 soal pilihan ganda tingkat umum.\n"
        "Topik ACAK dari:\n"
        "- Pengetahuan umum\n"
        "- Ilmu pengetahuan sosial\n"
        "- Teknologi / coding\n"
        "- Ilmu pengetahuan alam\n"
        "- Sejarah\n"
        "- Politik\n\n"
        "Gunakan Bahasa Indonesia.\n\n"
        "Format WAJIB JSON:\n"
        "[\n"
        "  {\n"
        '    "question": "...",\n'
        '    "options": {\n'
        '      "A": "...",\n'
        '      "B": "...",\n'
        '      "C": "...",\n'
        '      "D": "..."\n'
        "    },\n"
        '    "answer": "A"\n'
        "  }\n"
        "]\n\n"
        "Jawaban random A/B/C/D.\n"
        "Jangan beri teks lain selain JSON."
    )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "Kamu adalah pembuat soal quiz profesional."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.95,
        "max_tokens": 1024,
    }

    session = await get_http_session()
    async with session.post(
        f"{GROQ_BASE}/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type": "application/json",
        },
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        if resp.status != 200:
            raise RuntimeError("Gagal generate soal")

        data = await resp.json()

    raw = data["choices"][0]["message"]["content"].strip()
    bank = json.loads(raw)

    if not isinstance(bank, list) or len(bank) < QUIZ_TOTAL:
        raise RuntimeError("Bank soal tidak valid")

    return bank[:QUIZ_TOTAL]


async def _send_question(msg, quiz):
    q = quiz["bank"][quiz["current"]]
    no = quiz["current"] + 1

    text = (
        f"{_emo()} <b>QUIZ {no}/{QUIZ_TOTAL}</b>\n\n"
        f"<b>{html.escape(q['question'])}</b>\n\n"
        f"A. {html.escape(q['options']['A'])}\n"
        f"B. {html.escape(q['options']['B'])}\n"
        f"C. {html.escape(q['options']['C'])}\n"
        f"D. {html.escape(q['options']['D'])}\n\n"
        f"<i>Reply A / B / C / D (30 detik)</i>"
    )

    sent = await msg.reply_text(text, parse_mode="HTML")
    quiz["message_id"] = sent.message_id
    quiz["start"] = time.time()
    quiz["answered"] = set()


async def _end_quiz(msg, quiz):
    scores = quiz["scores"]
    if not scores:
        return await msg.reply_text("😴 Quiz selesai. Tidak ada yang menjawab.")

    ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    text = "🏆 <b>HASIL QUIZ</b>\n\n"
    for i, (uid, score) in enumerate(ranking, 1):
        try:
            member = await msg.chat.get_member(uid)
            name = html.escape(member.user.full_name)
        except Exception:
            name = "User"

        text += (
            f"{i}. <a href='tg://user?id={uid}'>{name}</a>"
            f" — <b>{score}</b> poin\n"
        )

    await msg.reply_text(text, parse_mode="HTML")

async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    chat_id = update.effective_chat.id
    if chat_id in _ACTIVE_QUIZ:
        return await msg.reply_text("⚠️ Quiz masih berjalan!")

    try:
        bank = await _generate_question_bank()
    except Exception:
        return await msg.reply_text("❌ Gagal membuat soal quiz (Groq error).")

    quiz = {
        "current": 0,
        "scores": {},
        "bank": bank,
        "message_id": None,
        "start": time.time(),
        "answered": set(),
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

    if msg.reply_to_message.message_id != quiz["message_id"]:
        return

    q = quiz["bank"][quiz["current"]]

    if time.time() - quiz["start"] > QUIZ_TIMEOUT:
        await msg.reply_text("⏰ Waktu habis!")
    else:
        ans = msg.text.strip().upper()
        if ans not in ("A", "B", "C", "D"):
            return

        uid = msg.from_user.id
        if uid in quiz["answered"]:
            return

        quiz["answered"].add(uid)

        if ans == q["answer"]:
            quiz["scores"][uid] = quiz["scores"].get(uid, 0) + 1
            await msg.reply_text("✅ <b>Benar!</b>", parse_mode="HTML")
        else:
            await msg.reply_text(
                f"❌ <b>Salah.</b> Jawaban benar: <b>{q['answer']}</b>",
                parse_mode="HTML"
            )

    if quiz["current"] >= QUIZ_TOTAL - 1:
        _ACTIVE_QUIZ.pop(chat_id, None)
        return await _end_quiz(msg, quiz)

    quiz["current"] += 1
    await _send_question(msg, quiz)