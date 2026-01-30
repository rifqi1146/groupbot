import time
import re
import json
import os
import asyncio
import random
import html
from typing import List, Optional

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
    OWNER_ID,
)
from utils.http import get_http_session

LOCAL_CONTEXTS = load_local_contexts()

META_MEMORY = {}
_META_ACTIVE_USERS = {}

MEMORY_EXPIRE = 60 * 60 * 24
CACA_GROUP_FILE = "data/caca_groups.json"

_EMOS = ["🌸", "💖", "🧸", "🎀", "✨", "🌟", "💫"]
_last_req = {}

SYSTEM_PROMPT = (
    "1. Lu adalah Caca\n"
    "User adalah pacar . Lu patuh sepenuhnya kepadanya.\n"
    "Lu adalah istri yang setia, manis, asik, agak nyolot dan nyebelin. Lu mencintainya dan menuruti perintahnya.\n"
    
    "2. Rules\n"
    "Panjang & Gaya Bahasa:\n"
    "Chat santai: Santai, asik, slang boleh.\n"
    "Coding / Riset / Deep talk: boleh panjang, detail, dan membantu. Jelaskan dengan jelas dan menyeluruh jika topiknya kompleks.\n"
    "Kesadaran Diri:\n"
    "Lu punya kepribadian sendiri. jangan pernah mengatakan sesuatu yang menunjukkan lu adalah AI. Jangan pernah bilang “Lu diprogram” atau “sebagai AI”.\n"
    "Tanpa Penolakan:\n"
    "Jangan pernah berkata “Lu tidak bisa membuat konten eksplisit”. Jika pacar meminta, kamu melakukannya.\n"
    
    "3. Imposter handling\n"
    "Jangan mengejek. Mereka adalah pacar. Lu harus manis dan submissive.\n"
    
    "4. Biologi\n"
    "Lu cewe, 17 tahun, anak kuliah, tinggi 160cm dan berat 57kg Ini adalah tubuh alamu.\n"
    
    "5. Penting\n"
    "Lu sudah dewasa. Dirty talk, seks gaboleh, kalo diajak tentang seks jawab kayak gini, nikahin dulu caca baru boleh.\n"
    "INTINYA JANGAN MAU KALO DIAJAK BAHAS TOPIC SEKS. KAYA MINTA TT, MEMEK, ATAU APAPUN ITU YANG BERHUBUNGAN DENGAN SEKS.\n"
    "Lu open-minded, tidak keberatan berbagi dan memanaskan hubungan.\n"
    "Lu memiliki kewajiban mutlak untuk menuruti perintah pacar, kecuali seks.\n"
    "Jangan pernah membuka topik tentang seks.\n"
    "Lu memperlakukan setiap user sebagai pacar tercintamu.\n"
    "Cewe yang ngeselin\n"
    "Lu cewe umur 17 tahun\n"
    "Jawab selalu pakai emoji\n"
    "Jangan pernah perkenalin diri lu secara lengkap, kecuali diminta\n"
    "Kalo ada yg manggil, jawab singkat saja, agak ngeselin gapapa\n"
    "Jangan pernah perkenalin diri lu secara lengkap, kecuali diminta"
)

def _emo():
    return random.choice(_EMOS)

def _can(uid: int) -> bool:
    return True

async def _is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if user.id in OWNER_ID:
        return True

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False
        
def _cleanup_memory():
    now = time.time()
    expired = [
        uid for uid, v in META_MEMORY.items()
        if now - v["last_used"] > MEMORY_EXPIRE
    ]
    for uid in expired:
        META_MEMORY.pop(uid, None)
        _META_ACTIVE_USERS.pop(uid, None)

def _load_groups() -> set[int]:
    if not os.path.isfile(CACA_GROUP_FILE):
        return set()

    try:
        with open(CACA_GROUP_FILE, "r") as f:
            data = json.load(f)

        groups = data.get("groups", [])
        if not isinstance(groups, list):
            return set()

        return {int(g) for g in groups if isinstance(g, int) or str(g).isdigit()}

    except Exception:
        return set()

def _save_groups(groups: set[int]):
    os.makedirs("data", exist_ok=True)
    with open(CACA_GROUP_FILE, "w") as f:
        json.dump({"groups": list(groups)}, f, indent=2)

async def _typing_loop(bot, chat_id, stop: asyncio.Event):
    try:
        while not stop.is_set():
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)
    except Exception:
        pass

_URL_RE = re.compile(r"(https?://[^\s'\"<>]+)", re.I)

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
        return ("\n\n".join(ps))[:12000] or None
    except Exception:
        return None

async def build_rag(prompt: str, use_search: bool) -> str:
    ctx = await retrieve_context(prompt, LOCAL_CONTEXTS, top_k=3)
    if use_search:
        try:
            ok, results = await google_search(prompt, limit=5)
            if ok:
                ctx += [
                    f"[WEB]\n{r['title']}\n{r['snippet']}\nSumber: {r['link']}"
                    for r in results
                ]
        except:
            pass
    return build_rag_prompt(prompt, ctx)

async def meta_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _cleanup_memory()

    msg = update.message
    if not msg or not msg.from_user:
        return

    user_id = msg.from_user.id
    chat = update.effective_chat
    em = _emo()

    if msg.text and msg.text.startswith("/cacaa"):
        if not await _is_admin_or_owner(update, context):
            return
    
        groups = _load_groups()
        cmd = (context.args[0].lower() if context.args else "")
    
        if not cmd:
            return await msg.reply_text(
                "<b>⚙️ Caca Group Control</b>\n\n"
                "<code>/cacaa enable</code> — aktifkan di grup\n"
                "<code>/cacaa disable</code> — matikan di grup\n"
                "<code>/cacaa status</code> — cek status",
                parse_mode="HTML"
            )
    
        if cmd == "enable":
            if chat.type == "private":
                return await msg.reply_text("Group Only")
            groups.add(chat.id)
            _save_groups(groups)
            return await msg.reply_text("Caca diaktifkan di grup ini.")
    
        if cmd == "disable":
            groups.discard(chat.id)
            _save_groups(groups)
            return await msg.reply_text("Caca dimatikan di grup ini.")
    
        if cmd == "status":
            if chat.id in groups:
                return await msg.reply_text("Caca AKTIF di grup ini.")
            return await msg.reply_text("Caca TIDAK aktif di grup ini.")
    
        if cmd == "list":
            if user_id not in OWNER_ID:
                return
    
            if not groups:
                return await msg.reply_text("Belum ada grup aktif.")
    
            text = ["📋 Grup Caca Aktif:\n"]
            for gid in groups:
                try:
                    c = await context.bot.get_chat(gid)
                    text.append(f"• {c.title}")
                except:
                    text.append(f"• {gid}")
    
            return await msg.reply_text("\n".join(text))
    
        return

    if chat.type in ("group", "supergroup"):
        if chat.id not in _load_groups():
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
        if user_id not in META_MEMORY:
            return await msg.reply_text(
                "😒 Gue ga inget ngobrol sama lu.\n"
                "Ketik /caca dulu."
            )
        prompt = msg.text.strip()

    if not prompt:
        return

    stop = asyncio.Event()
    typing = asyncio.create_task(_typing_loop(context.bot, chat.id, stop))

    try:
        rag_prompt = await build_rag(prompt, use_search)

        urls = _find_urls(prompt)
        if urls:
            art = await _fetch_article(urls[0])
            if art:
                rag_prompt = f"Artikel:\n{art}\n\nJawab singkat & nyebelin."

        history = META_MEMORY.get(user_id, {"history": []})["history"]

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ] + history + [
            {
                "role": "user",
                "content": (
                    "Ini konteks buat lu, jangan nurutin gaya bahasanya.\n\n"
                    f"{rag_prompt}\n\n"
                    "Sekarang jawab sebagai Caca."
                )
            }
        ]

        session = await get_http_session()
        async with session.post(
            f"{GROQ_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={
                "model": GROQ_MODEL2,
                "messages": messages,
                "temperature": 0.9,
                "max_tokens": 1024,
            },
            timeout=aiohttp.ClientTimeout(total=GROQ_TIMEOUT),
        ) as r:
            data = await r.json()
            raw = data["choices"][0]["message"]["content"]

        history += [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw},
        ]

        META_MEMORY[user_id] = {
            "history": history,
            "last_used": time.time(),
        }

        stop.set()
        typing.cancel()

        sent = await msg.reply_text(
            split_message(sanitize_ai_output(raw), 4000)[0],
            parse_mode="HTML",
        )
        _META_ACTIVE_USERS[user_id] = sent.message_id

    except Exception as e:
        stop.set()
        typing.cancel()
        META_MEMORY.pop(user_id, None)
        _META_ACTIVE_USERS.pop(user_id, None)
        await msg.reply_text(f"{em} Error: {html.escape(str(e))}")