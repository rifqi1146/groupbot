import re
import os
import asyncio
import random
import html
import logging
from dotenv import load_dotenv
from typing import Optional
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes
from handlers.join import require_join_or_block
from handlers.gsearch import google_search
from utils.text import split_message, sanitize_ai_output
from .caca_prompt import PERSONAS
from utils.http import get_http_session
from database import caca_db
from utils import caca_memory
from utils.config import CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AUTH_TOKEN, CLOUDFLARE_MODEL

load_dotenv()
logger = logging.getLogger(__name__)
CLOUDFLARE_TIMEOUT = int(os.getenv("CLOUDFLARE_TIMEOUT", "60"))
_EMOS = ["🌸", "💖", "🧸", "🎀", "🌟", "💫"]
_URL_RE = re.compile(r"(https?://[^\s'\"<>]+)", re.I)

def _emo():
    return random.choice(_EMOS)

def _parse_html(html_text: str) -> Optional[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "iframe", "noscript"]):
        t.decompose()
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.text) > 30]
    return ("\n\n".join(ps))[:12000] or None

def _cleanup_memory():
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(caca_memory.cleanup())
    except Exception:
        pass

async def _typing_loop(bot, chat_id, stop: asyncio.Event):
    try:
        while not stop.is_set():
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)
    except Exception:
        pass

def _normalize_caca_output(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue
        if i + 1 < len(lines) and lines[i + 1]:
            current = line
            nxt = lines[i + 1]
            if len(current) <= 35:
                merged.append(f"{current} {nxt}".strip())
                i += 2
                continue
        merged.append(line)
        i += 1
    text = "\n".join(merged)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

def _cf_credentials():
    pairs = []
    seen = set()
    raw = [(CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AUTH_TOKEN)]
    for i in range(2, 11):
        raw.append((os.getenv(f"CLOUDFLARE_ACCOUNT_ID_{i}", ""), os.getenv(f"CLOUDFLARE_AUTH_TOKEN_{i}", "")))
    for account_id, token in raw:
        account_id = (account_id or "").strip()
        token = (token or "").strip()
        if not account_id or not token:
            continue
        key = (account_id, token)
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"account_id": account_id, "token": token})
    return pairs

def _cf_extract_error(data, status: int) -> str:
    if isinstance(data, dict):
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0] or {}
            msg = first.get("message")
            if msg:
                return str(msg)
        if data.get("error"):
            return str(data.get("error"))
    return f"Cloudflare HTTP {status}"

def _is_cf_quota_error(message: str) -> bool:
    text = (message or "").lower()
    return (
        "daily free allocation" in text
        or "used up your daily free allocation" in text
        or "please upgrade to cloudflare's workers paid plan" in text
        or "neurons" in text
        or "quota" in text
        or "rate limit" in text
    )

async def _cloudflare_chat(messages: list[dict]):
    creds = _cf_credentials()
    if not creds:
        raise RuntimeError("CLOUDFLARE credentials belum diset")
    session = await get_http_session()
    errors = []
    last_quota_error = None
    for idx, cred in enumerate(creds, start=1):
        account_id = cred["account_id"]
        token = cred["token"]
        try:
            async with session.post(
                f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{CLOUDFLARE_MODEL}",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messages": messages,
                    "temperature": 0.9,
                    "max_completion_tokens": 1024,
                    "chat_template_kwargs": {"enable_thinking": False, "clear_thinking": True},
                },
                timeout=aiohttp.ClientTimeout(total=CLOUDFLARE_TIMEOUT),
            ) as r:
                data = await r.json(content_type=None)
                if r.status >= 400:
                    err = _cf_extract_error(data, r.status)
                    raise RuntimeError(err)
                if isinstance(data, dict) and data.get("success") is False:
                    err = _cf_extract_error(data, r.status)
                    raise RuntimeError(err)
                result = data.get("result") or {}
                raw = (
                    result.get("response")
                    or result.get("output_text")
                    or result.get("text")
                    or (
                        result.get("choices", [{}])[0].get("message", {}).get("content")
                        if isinstance(result.get("choices"), list) and result.get("choices")
                        else None
                    )
                )
                if not raw:
                    raise RuntimeError(f"Unexpected Cloudflare response: {data}")
                logger.info("Cloudflare success | key_index=%s account_id=%s", idx, account_id)
                return raw
        except Exception as e:
            err = str(e)
            errors.append(f"key#{idx}: {err}")
            if _is_cf_quota_error(err):
                last_quota_error = err
                logger.warning("Cloudflare quota hit | key_index=%s account_id=%s err=%s", idx, account_id, err)
                continue
            logger.warning("Cloudflare request failed | key_index=%s account_id=%s err=%s", idx, account_id, err)
            continue
    if last_quota_error and all(_is_cf_quota_error(x.split(": ", 1)[-1]) for x in errors):
        raise RuntimeError("Semua API key Cloudflare kena limit harian.")
    raise RuntimeError("Cloudflare failed: " + " | ".join(errors[-3:]))

async def meta_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    _cleanup_memory()
    msg = update.message
    if not msg or not msg.from_user:
        return
    user_id = msg.from_user.id
    chat = update.effective_chat
    em = _emo()
    if chat and chat.type in ("group", "supergroup"):
        groups = await caca_db.load_groups()
        if chat.id not in groups:
            return await msg.reply_text("<b>Caca tidak tersedia di grup ini</b>", parse_mode="HTML")
    prompt = ""
    use_search = False
    if msg.text and msg.text.startswith("/caca"):
        if context.args and context.args[0].lower() == "search":
            use_search = True
            prompt = " ".join(context.args[1:])
        else:
            prompt = " ".join(context.args)
            await caca_memory.clear(user_id)
            await caca_memory.clear_last_message_id(user_id)
        if not prompt.strip():
            return await msg.reply_text(
                f"{em} Pake gini:\n/caca <teks>\n/caca search <teks>\natau reply jawaban gue 😒"
            )
    elif msg.reply_to_message:
        history = await caca_memory.get_history(user_id)
        if not history:
            return await msg.reply_text("😒 Gue ga inget ngobrol sama lu.\nKetik /caca dulu.")
        prompt = (msg.text or "").strip()
    if not prompt:
        return
    stop = asyncio.Event()
    typing = asyncio.create_task(_typing_loop(context.bot, chat.id, stop))
    try:
        search_context = ""
        if use_search:
            try:
                ok, results = await google_search(prompt, limit=5)
                if ok and results:
                    lines = []
                    for r in results:
                        lines.append(f"- {r['title']}\n  {r['snippet']}\n  Sumber: {r['link']}")
                    search_context = (
                        "Ini hasil search, pake buat nambah konteks, anggap ini adalah sumber terbaru."
                        "Jawab tetap sebagai Caca.\n\n" + "\n\n".join(lines)
                    )
                elif not ok:
                    logger.warning("Google Search failed | query=%r err=%r", prompt, results)
            except Exception as e:
                logger.error("Google Search unexpected error | query=%r err=%r", prompt, e, exc_info=True)
        history = await caca_memory.get_history(user_id)
        mode = caca_db.get_mode(user_id)
        system_prompt = PERSONAS.get(mode, PERSONAS["default"])
        messages = [{"role": "system", "content": system_prompt}] + history + [{
            "role": "user",
            "content": f"{search_context}\n\n{prompt}" if search_context else prompt,
        }]
        raw = await _cloudflare_chat(messages)
        history += [{"role": "user", "content": prompt}, {"role": "assistant", "content": raw}]
        await caca_memory.set_history(user_id, history)
        stop.set()
        typing.cancel()
        cleaned = _normalize_caca_output(sanitize_ai_output(raw))
        chunks = split_message(cleaned, 4000)
        sent = None
        for i, chunk in enumerate(chunks):
            if i == 0:
                sent = await msg.reply_text(chunk, parse_mode="HTML")
            else:
                await msg.reply_text(chunk, parse_mode="HTML")
        if sent:
            await caca_memory.set_last_message_id(user_id, sent.message_id)
    except Exception as e:
        stop.set()
        typing.cancel()
        await caca_memory.clear(user_id)
        await caca_memory.clear_last_message_id(user_id)
        await msg.reply_text(f"{em} Error: {html.escape(str(e))}")

def init_background():
    loop = asyncio.get_event_loop()
    loop.create_task(caca_memory.init())
    loop.create_task(caca_db.init())