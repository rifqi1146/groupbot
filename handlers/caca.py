import time
import re
import json
import os
import asyncio
import random
import html
from typing import List, Optional
import sqlite3

import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes

from rag.adalah_pokoknya.retriever import retrieve_context
from rag.adalah_pokoknya.prompt import build_rag_prompt
from rag.adalah_pokoknya.loader import load_local_contexts
from handlers.gsearch import google_search

from utils.ai_utils import split_message, sanitize_ai_output, PERSONAS, SYSTEM_PROMPT, SYSTEM_PROMPT2
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

META_DB_PATH = "data/meta_memory.sqlite3"
META_MAX_TURNS = 50

CACA_APPROVED_FILE = "data/caca_approved.json"
_CACA_APPROVED = set()
CACA_MODE_FILE = "data/caca_mode.json"

def _meta_db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(META_DB_PATH)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS meta_memory (
                user_id INTEGER PRIMARY KEY,
                history_json TEXT NOT NULL,
                last_used REAL NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()

def _meta_db_get(user_id: int) -> tuple[list, float] | None:
    con = sqlite3.connect(META_DB_PATH)
    try:
        cur = con.execute(
            "SELECT history_json, last_used FROM meta_memory WHERE user_id=?",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        history = json.loads(row[0]) if row[0] else []
        last_used = float(row[1])
        if not isinstance(history, list):
            history = []
        return history, last_used
    finally:
        con.close()

def _meta_db_set(user_id: int, history: list):
    if META_MAX_TURNS and META_MAX_TURNS > 0:
        max_msgs = META_MAX_TURNS * 2
        if len(history) > max_msgs:
            history = history[-max_msgs:]

    con = sqlite3.connect(META_DB_PATH)
    try:
        con.execute(
            """
            INSERT INTO meta_memory (user_id, history_json, last_used)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              history_json=excluded.history_json,
              last_used=excluded.last_used
            """,
            (user_id, json.dumps(history, ensure_ascii=False), time.time()),
        )
        con.commit()
    finally:
        con.close()

def _meta_db_touch(user_id: int):
    con = sqlite3.connect(META_DB_PATH)
    try:
        con.execute(
            "UPDATE meta_memory SET last_used=? WHERE user_id=?",
            (time.time(), user_id),
        )
        con.commit()
    finally:
        con.close()

def _meta_db_clear(user_id: int):
    con = sqlite3.connect(META_DB_PATH)
    try:
        con.execute("DELETE FROM meta_memory WHERE user_id=?", (user_id,))
        con.commit()
    finally:
        con.close()

def _meta_db_cleanup(expire_seconds: int):
    cutoff = time.time() - expire_seconds
    con = sqlite3.connect(META_DB_PATH)
    try:
        con.execute("DELETE FROM meta_memory WHERE last_used < ?", (cutoff,))
        con.commit()
    finally:
        con.close()

async def meta_db_init():
    await asyncio.to_thread(_meta_db_init)

async def meta_db_get(user_id: int) -> list:
    res = await asyncio.to_thread(_meta_db_get, user_id)
    if not res:
        return []
    history, last_used = res
    return history

async def meta_db_set(user_id: int, history: list):
    await asyncio.to_thread(_meta_db_set, user_id, history)

async def meta_db_clear(user_id: int):
    await asyncio.to_thread(_meta_db_clear, user_id)

async def meta_db_cleanup():
    await asyncio.to_thread(_meta_db_cleanup, MEMORY_EXPIRE)

asyncio.get_event_loop().create_task(meta_db_init())
    
def _load_modes():
    if not os.path.isfile(CACA_MODE_FILE):
        return {}
    try:
        with open(CACA_MODE_FILE, "r") as f:
            data = json.load(f)
        return {int(k): v for k, v in data.get("modes", {}).items()}
    except Exception:
        return {}

def _save_modes(modes: dict[int, str]):
    os.makedirs("data", exist_ok=True)
    with open(CACA_MODE_FILE, "w") as f:
        json.dump({"modes": modes}, f, indent=2)
        
_CACA_MODE = _load_modes()

def _load_approved():
    if not os.path.isfile(CACA_APPROVED_FILE):
        return set()
    try:
        with open(CACA_APPROVED_FILE, "r") as f:
            data = json.load(f)
        return {int(x) for x in data.get("approved", [])}
    except Exception:
        return set()

def _save_approved(s: set[int]):
    os.makedirs("data", exist_ok=True)
    with open(CACA_APPROVED_FILE, "w") as f:
        json.dump({"approved": list(s)}, f, indent=2)

def _is_approved(user_id: int) -> bool:
    return user_id in _CACA_APPROVED
    
_CACA_APPROVED = _load_approved()

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
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(meta_db_cleanup())
    except Exception:
        pass

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

    if msg.text and msg.text.startswith("/cacamode"):
        if user_id not in OWNER_ID:
            return await msg.reply_text("❌ Owner only.")

        if not context.args:
            return await msg.reply_text(
                "<b>⚙️ Caca Persona Control</b>\n\n"
                "<code>/cacamode add &lt;user_id&gt;</code>\n"
                "<code>/cacamode del &lt;user_id&gt;</code>\n"
                "<code>/cacamode list</code>",
                parse_mode="HTML"
            )

        cmd = context.args[0].lower()

        if cmd == "add" and len(context.args) > 1:
            uid = int(context.args[1])
            _CACA_APPROVED.add(uid)
            _save_approved(_CACA_APPROVED)
            return await msg.reply_text(
                f"✅ User <code>{uid}</code> di-approve.",
                parse_mode="HTML"
            )

        if cmd == "del" and len(context.args) > 1:
            uid = int(context.args[1])
            _CACA_APPROVED.discard(uid)
            _CACA_MODE.pop(uid, None)
            _save_modes(_CACA_MODE)
            await meta_db_clear(uid)
            _save_approved(_CACA_APPROVED)
            return await msg.reply_text(
                f"❎ User <code>{uid}</code> dihapus.",
                parse_mode="HTML"
            )

        if cmd == "list":
            if not _CACA_APPROVED:
                return await msg.reply_text("Belum ada user approved.")
        
            lines = []
            for uid in _CACA_APPROVED:
                try:
                    u = await context.bot.get_chat(uid)
                    name = html.escape(u.full_name)
                except:
                    name = "Unknown User"
        
                lines.append(f"• <a href=\"tg://user?id={uid}\">{name}</a>")
        
            return await msg.reply_text(
                "👑 <b>User Approved:</b>\n" + "\n".join(lines),
                parse_mode="HTML",
                disable_web_page_preview=True
            )

        return

    if msg.text and msg.text.startswith("/mode"):
        if user_id not in _CACA_APPROVED:
            return await msg.reply_text(
                "❌ Mode persona hanya untuk user donatur.\n"
                "Selain donatur dilarang ngatur 😤"
            )

        if not context.args:
            cur = _CACA_MODE.get(user_id, "default")
            return await msg.reply_text(
                f"🎭 Mode sekarang: <b>{cur}</b>\n\n"
                "Mode tersedia:\n"
                "• default\n"
                "• bokep",
                parse_mode="HTML"
            )

        mode = context.args[0].lower()
        if mode not in PERSONAS:
            return await msg.reply_text("❌ Mode tidak dikenal.")

        _CACA_MODE[user_id] = mode
        _save_modes(_CACA_MODE)
        await meta_db_clear(user_id)

        return await msg.reply_text(
            f"🎭 Persona diubah ke <b>{mode}</b> ✨",
            parse_mode="HTML"
        )

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
            await meta_db_clear(user_id)
            _META_ACTIVE_USERS.pop(user_id, None)

        if not prompt.strip():
            return await msg.reply_text(
                f"{em} Pake gini:\n"
                "/caca <teks>\n"
                "/caca search <teks>\n"
                "atau reply jawaban gue 😒"
            )

    elif msg.reply_to_message:
        history = await meta_db_get(user_id)
        if not history:
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
        search_context = ""

        if use_search:
            try:
                ok, results = await google_search(prompt, limit=3)
                if ok and results:
                    lines = []
                    for r in results:
                        lines.append(
                            f"- {r['title']}\n"
                            f"  {r['snippet']}\n"
                            f"  Sumber: {r['link']}"
                        )
                    search_context = (
                        "Ini hasil search, pake buat nambah konteks. "
                        "Jawab tetap sebagai Caca.\n\n"
                        + "\n\n".join(lines)
                    )
            except:
                pass

        history = await meta_db_get(user_id)

        mode = _CACA_MODE.get(user_id, "default")
        system_prompt = PERSONAS.get(mode, PERSONAS["default"])

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            }
        ] + history + [
            {
                "role": "user",
                "content": (
                    f"{search_context}\n\n{prompt}"
                    if search_context else prompt
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
                "max_tokens": 2048,
            },
            timeout=aiohttp.ClientTimeout(total=GROQ_TIMEOUT),
        ) as r:
            data = await r.json()
            raw = data["choices"][0]["message"]["content"]

        history += [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw},
        ]

        await meta_db_set(user_id, history)

        stop.set()
        typing.cancel()

        chunks = split_message(sanitize_ai_output(raw), 4000)

        sent = None
        for i, chunk in enumerate(chunks):
            if i == 0:
                sent = await msg.reply_text(chunk, parse_mode="HTML")
            else:
                await msg.reply_text(chunk, parse_mode="HTML")

        if sent:
            _META_ACTIVE_USERS[user_id] = sent.message_id

    except Exception as e:
        stop.set()
        typing.cancel()
        await meta_db_clear(user_id)
        _META_ACTIVE_USERS.pop(user_id, None)
        await msg.reply_text(f"{em} Error: {html.escape(str(e))}")