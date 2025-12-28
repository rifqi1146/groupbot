import os
import json
import html
import time
import random
import asyncio
import logging
import aiohttp

from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaVideo,
)
from telegram.ext import (
    ContextTypes,
)

from telegram import Update

from utils.http import get_http_session
from utils.config import OWNER_ID

from utils.config import OWNER_ID, ASUPAN_STARTUP_CHAT_ID

#asupannnnn
log = logging.getLogger(__name__)

#asupan grup
ASUPAN_GROUP_FILE = "data/asupan_groups.json"
ASUPAN_ENABLED_CHATS = set()
ASUPAN_CACHE = []
ASUPAN_PREFETCH_SIZE = 5
ASUPAN_KEYWORD_CACHE = {}
ASUPAN_USER_KEYWORD = {}
ASUPAN_MESSAGE_KEYWORD = {}
ASUPAN_FETCHING = False
ASUPAN_DELETE_JOBS = {}
ASUPAN_AUTO_DELETE_SEC = 300
ASUPAN_COOLDOWN = {}
ASUPAN_COOLDOWN_SEC = 5
AUTODEL_FILE = "data/autodel_groups.json"
AUTODEL_ENABLED_CHATS = set()


def load_autodel_groups():
    global AUTODEL_ENABLED_CHATS
    if not os.path.exists(AUTODEL_FILE):
        AUTODEL_ENABLED_CHATS = set()
        return
    try:
        with open(AUTODEL_FILE, "r") as f:
            data = json.load(f)
            AUTODEL_ENABLED_CHATS = set(data.get("enabled_chats", []))
    except Exception:
        AUTODEL_ENABLED_CHATS = set()


def save_autodel_groups():
    with open(AUTODEL_FILE, "w") as f:
        json.dump(
            {"enabled_chats": list(AUTODEL_ENABLED_CHATS)},
            f,
            indent=2
        )


def is_autodel_enabled(chat_id: int) -> bool:
    return chat_id in AUTODEL_ENABLED_CHATS


def save_asupan_groups():
    with open(ASUPAN_GROUP_FILE, "w") as f:
        json.dump(
            {"enabled_chats": list(ASUPAN_ENABLED_CHATS)},
            f,
            indent=2
        )


def is_asupan_enabled(chat_id: int) -> bool:
    return chat_id in ASUPAN_ENABLED_CHATS


async def enable_asupan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    ASUPAN_ENABLED_CHATS.add(chat.id)
    save_asupan_groups()
    await update.message.reply_text("✅ Asupan diaktifkan di grup ini.")


async def disable_asupan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    ASUPAN_ENABLED_CHATS.discard(chat.id)
    save_asupan_groups()
    await update.message.reply_text("🚫 Asupan dimatikan di grup ini.")

def load_asupan_groups():
    global ASUPAN_ENABLED_CHATS
    if not os.path.exists(ASUPAN_GROUP_FILE):
        ASUPAN_ENABLED_CHATS = set()
        return

    try:
        with open(ASUPAN_GROUP_FILE, "r") as f:
            data = json.load(f)
            ASUPAN_ENABLED_CHATS = set(data.get("enabled_chats", []))
    except Exception:
        ASUPAN_ENABLED_CHATS = set()
        
async def _delete_asupan_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    message_id = job.data["message_id"]

    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception:
        pass

    ASUPAN_DELETE_JOBS.pop(message_id, None)


async def autodel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    if chat.type == "private":
        return await update.message.reply_text("ℹ️ Auto delete tidak berlaku di private chat.")

    if not context.args:
        return await update.message.reply_text(
            "Gunakan:\n"
            "/autodel on\n"
            "/autodel off\n"
            "/autodel status\n"
            "/autodel list"
        )

    arg = context.args[0].lower()

    if arg == "on":
        AUTODEL_ENABLED_CHATS.add(chat.id)
        save_autodel_groups()
        return await update.message.reply_text("✅ Auto delete diaktifkan di grup ini.")

    if arg == "off":
        AUTODEL_ENABLED_CHATS.discard(chat.id)
        save_autodel_groups()
        return await update.message.reply_text("🚫 Auto delete dimatikan di grup ini.")

    if arg == "status":
        status = "AKTIF ✅" if is_autodel_enabled(chat.id) else "NONAKTIF ❌"
        return await update.message.reply_text(
            f"📌 Status auto delete di grup ini: <b>{status}</b>",
            parse_mode="HTML"
        )

    if arg == "list":
        if not AUTODEL_ENABLED_CHATS:
            return await update.message.reply_text("📭 Tidak ada grup dengan auto delete aktif.")

        lines = ["<b>📋 Grup Auto Delete Aktif</b>\n"]
        for cid in AUTODEL_ENABLED_CHATS:
            try:
                c = await context.bot.get_chat(cid)
                name = c.title or c.username or "Unknown"
                lines.append(f"• {html.escape(name)}")
            except Exception:
                pass

        return await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    await update.message.reply_text("❌ Argumen tidak dikenali.")
    
async def asupanlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot = context.bot

    if user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    if not ASUPAN_ENABLED_CHATS:
        return await update.message.reply_text("📭 Belum ada grup yang diizinkan asupan.")

    lines = ["<b>📋 Grup Asupan Aktif</b>\n"]

    for cid in ASUPAN_ENABLED_CHATS:
        try:
            chat = await bot.get_chat(cid)
            title = chat.title or chat.username or "Unknown"
            lines.append(f"• {html.escape(title)}")
        except Exception:
            lines.append(f"• <code>{cid}</code>")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML"
    )
    

#inline keyboard
def asupan_keyboard(owner_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 Ganti Asupan",
            callback_data=f"asupan:next:{owner_id}"
        )]
    ])

#fetch
async def fetch_asupan_tikwm(keyword: str | None = None):
    default_keywords = [
        "tobrut",
        "pemersatubangsa",
        "tanktopstyle",
        "tanktop",
        "bahancrt",
        "cucimata",
        "bhncrt",
        "geolgeol",
        "zaraxhel",
        "verllyyaling",
        "cewek lucu indo",
        "asupan cewek",
        "asupan indo",
        "tante holic",
        "trend susu beracun",
        "krisna minta susu",
        "trendsusuberacun",
        "eunicetjoaa",
        "cewek viral",
        "nasikfc",
        "cewek fyp",
        "cewek cantik",
        "cewek indo",
        "cewek tiktok indo",
        "cewek joget indo",
        "cewek cantik indo",
        "cewek hijab",
        "fakebody",
        "tobrut style",
        "cewek jawa",
        "cewek sunda",
        "asupan malam",
        "asupan pagi",
        "asupan harian"
    ]

    query = keyword.strip() if keyword else random.choice(default_keywords)

    api_url = "https://www.tikwm.com/api/feed/search"
    payload = {
        "keywords": query,
        "count": 20,
        "cursor": 0,
        "region": "ID"
    }

    session = await get_http_session()
    async with session.post(
        api_url,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=15)
    ) as r:
        data = await r.json()

    if data.get("code") != 0:
        raise RuntimeError(f"TikWM API error: {data.get('msg')}")

    videos = data.get("data", {}).get("videos") or []
    if not videos:
        raise RuntimeError("Asupan kosong")

    return random.choice(videos)["play"]

async def warm_keyword_asupan_cache(bot, keyword: str):
    kw = keyword.lower().strip()
    cache = ASUPAN_KEYWORD_CACHE.setdefault(kw, [])

    if len(cache) >= ASUPAN_PREFETCH_SIZE:
        return

    try:
        while len(cache) < ASUPAN_PREFETCH_SIZE:
            url = await fetch_asupan_tikwm(kw)

            msg = await bot.send_video(
                chat_id=ASUPAN_STARTUP_CHAT_ID,
                video=url,
                disable_notification=True
            )

            cache.append({"file_id": msg.video.file_id})
            await msg.delete()

            await asyncio.sleep(1.1)

    except Exception as e:
        log.warning(f"[ASUPAN KEYWORD PREFETCH] {kw}: {e}")
        
async def warm_asupan_cache(bot):
    global ASUPAN_FETCHING

    if ASUPAN_FETCHING or not ASUPAN_STARTUP_CHAT_ID:
        return

    ASUPAN_FETCHING = True
    try:
        while len(ASUPAN_CACHE) < ASUPAN_PREFETCH_SIZE:
            try:
                url = await fetch_asupan_tikwm(None)

                msg = await bot.send_video(
                    chat_id=ASUPAN_STARTUP_CHAT_ID,
                    video=url,
                    disable_notification=True
                )
                ASUPAN_CACHE.append({"file_id": msg.video.file_id})
                await msg.delete()

                await asyncio.sleep(1.1)

            except Exception as e:
                log.warning(f"[ASUPAN PREFETCH] {e}")
                break
    finally:
        ASUPAN_FETCHING = False

#get asupan
async def get_asupan_fast(bot, keyword: str | None = None):
    if keyword is None:
        if ASUPAN_CACHE:
            return ASUPAN_CACHE.pop(0)

        url = await fetch_asupan_tikwm(None)
        msg = await bot.send_video(
            chat_id=ASUPAN_STARTUP_CHAT_ID,
            video=url,
            disable_notification=True
        )
        file_id = msg.video.file_id
        await msg.delete()
        return {"file_id": file_id}
        
    kw = keyword.lower().strip()
    cache = ASUPAN_KEYWORD_CACHE.get(kw)

    if cache:
        return cache.pop(0)

    url = await fetch_asupan_tikwm(kw)
    msg = await bot.send_video(
        chat_id=ASUPAN_STARTUP_CHAT_ID,
        video=url,
        disable_notification=True
    )
    file_id = msg.video.file_id
    await msg.delete()
    return {"file_id": file_id}

#cmd asupan
async def asupan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "private":
        if not is_asupan_enabled(chat.id):
            return await update.message.reply_text(
                "🚫 Fitur asupan tidak tersedia di grup ini."
            )

    keyword = " ".join(context.args).strip() if context.args else None
    msg = await update.message.reply_text("😋 Nyari asupan...")

    try:
        data = await get_asupan_fast(context.bot, keyword)

        sent = await chat.send_video(
            video=data["file_id"],
            reply_to_message_id=update.message.message_id,
            reply_markup=asupan_keyboard(user.id)
        )

        ASUPAN_MESSAGE_KEYWORD[sent.message_id] = keyword

        if chat.type != "private" and is_autodel_enabled(chat.id):
            old_job = ASUPAN_DELETE_JOBS.pop(sent.message_id, None)
            if old_job:
                old_job.schedule_removal()

            job = context.application.job_queue.run_once(
                _delete_asupan_job,
                ASUPAN_AUTO_DELETE_SEC,
                data={
                    "chat_id": chat.id,
                    "message_id": sent.message_id,
                },
            )
            ASUPAN_DELETE_JOBS[sent.message_id] = job

        await msg.delete()

        context.application.create_task(warm_asupan_cache(context.bot))
        if keyword:
            context.application.create_task(
                warm_keyword_asupan_cache(context.bot, keyword)
            )

    except Exception as e:
        await msg.edit_text(f"❌ Gagal: {e}")

#asupan callback
async def asupan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id

    try:
        _, action, owner_id = q.data.split(":")
        owner_id = int(owner_id)
    except Exception:
        await q.answer("❌ Invalid callback", show_alert=True)
        return

    if user_id != owner_id:
        await q.answer("❌ Bukan asupan lu dongo!", show_alert=True)
        return

    now = time.time()
    last = ASUPAN_COOLDOWN.get(user_id, 0)
    if now - last < ASUPAN_COOLDOWN_SEC:
        await q.answer(
            f"Tunggu {ASUPAN_COOLDOWN_SEC} detik sebelum ganti asupan lagi.",
            show_alert=True
        )
        return

    ASUPAN_COOLDOWN[user_id] = now
    await q.answer()

    try:
        msg_id = q.message.message_id
        keyword = ASUPAN_MESSAGE_KEYWORD.get(msg_id)

        if q.message.chat.type != "private" and is_autodel_enabled(q.message.chat_id):
            old_job = ASUPAN_DELETE_JOBS.pop(msg_id, None)
            if old_job:
                old_job.schedule_removal()

        data = await get_asupan_fast(context.bot, keyword)

        await q.message.edit_media(
            media=InputMediaVideo(media=data["file_id"]),
            reply_markup=asupan_keyboard(owner_id)
        )

        if q.message.chat.type != "private" and is_autodel_enabled(q.message.chat_id):
            job = context.application.job_queue.run_once(
                _delete_asupan_job,
                ASUPAN_AUTO_DELETE_SEC,
                data={
                    "chat_id": q.message.chat_id,
                    "message_id": msg_id,
                },
            )
            ASUPAN_DELETE_JOBS[msg_id] = job

        ASUPAN_MESSAGE_KEYWORD[msg_id] = keyword

        if keyword:
            context.application.create_task(
                warm_keyword_asupan_cache(context.bot, keyword)
            )
        else:
            context.application.create_task(
                warm_asupan_cache(context.bot)
            )

    except Exception:
        await q.answer("❌ Gagal ambil asupan", show_alert=True)

async def send_asupan_once(bot):
    if not ASUPAN_STARTUP_CHAT_ID:
        log.warning("[ASUPAN STARTUP] Chat_id is empty")
        return

    try:
        data = await get_asupan_fast(bot)

        msg = await bot.send_video(
            chat_id=ASUPAN_STARTUP_CHAT_ID,
            video=data["file_id"],
            disable_notification=True
        )

        await msg.delete()

        log.info("[ASUPAN STARTUP] Warmup success")

    except Exception as e:
        log.warning(f"[ASUPAN STARTUP] Failed: {e}")

async def startup_tasks(app):
    await asyncio.sleep(3)
    if not ASUPAN_STARTUP_CHAT_ID:
        log.warning("[ASUPAN STARTUP] Chat_id is empty")
        return

    try:
        await send_asupan_once(app.bot)
    except Exception as e:
        log.warning(f"[ASUPAN STARTUP] {e}")

