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

from utils.config import OWNER_ID, LOG_CHAT_ID

#asupannnnn
log = logging.getLogger(__name__)

#asupan grup
ASUPAN_GROUP_FILE = "data/asupan_groups.json"
ASUPAN_CACHE = []
ASUPAN_PREFETCH_SIZE = 5
ASUPAN_KEYWORD_CACHE = {}
ASUPAN_MESSAGE_KEYWORD = {}
ASUPAN_FETCHING = False
ASUPAN_DELETE_JOBS = {}
ASUPAN_AUTO_DELETE_SEC = 300
ASUPAN_COOLDOWN = {}
ASUPAN_COOLDOWN_SEC = 5
AUTODEL_FILE = "data/autodel_groups.json"
AUTODEL_ENABLED_CHATS = set()


async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
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

    if user.id not in OWNER_ID:
        return

    ASUPAN_ENABLED_CHATS.add(chat.id)
    save_asupan_groups()
    await update.message.reply_text("Asupan diaktifkan di grup ini.")


async def disable_asupan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id not in OWNER_ID:
        return

    ASUPAN_ENABLED_CHATS.discard(chat.id)
    save_asupan_groups()
    await update.message.reply_text("Asupan dimatikan di grup ini.")

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
        
async def asupanlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot = context.bot

    if user.id not in OWNER_ID:
        return

    if not ASUPAN_ENABLED_CHATS:
        return await update.message.reply_text("Belum ada grup yang diizinkan asupan.")

    lines = ["<b>Grup Asupan Aktif</b>\n"]

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
    
async def _expire_asupan_notice(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(
            job.data["chat_id"],
            job.data["message_id"]
        )
    except Exception:
        pass


async def _expire_asupan_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    asupan_msg_id = job.data["asupan_msg_id"]
    reply_to = job.data["reply_to"]

    if ASUPAN_DELETE_JOBS.get(asupan_msg_id) is not job:
        return

    try:
        await context.bot.delete_message(chat_id, asupan_msg_id)

        msg = await context.bot.send_message(
            chat_id,
            "⏳ <b>Asupan Closed</b>\n\n"
            "No activity detected for <b>5 minutes</b>.\n"
            "This asupan session has been automatically closed 🍜\n\n",
            reply_to_message_id=reply_to,
            parse_mode="HTML"
        )

        context.application.job_queue.run_once(
            _expire_asupan_notice,
            15,
            data={
                "chat_id": chat_id,
                "message_id": msg.message_id,
            },
        )

    except Exception:
        pass

    ASUPAN_DELETE_JOBS.pop(asupan_msg_id, None)
    ASUPAN_MESSAGE_KEYWORD.pop(asupan_msg_id, None)

async def asupann_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    bot = context.bot

    if chat.type == "private":
        return

    if not await is_admin_or_owner(update, context):
        return

    if not context.args:
        return await update.message.reply_text(
            "<b>📦 Asupan Command</b>\n\n"
            "• <code>/asupann enable</code>\n"
            "• <code>/asupann disable</code>\n"
            "• <code>/asupann status</code>\n"
            "• <code>/asupann list</code>",
            parse_mode="HTML"
        )

    sub = context.args[0].lower()

    if sub == "enable":
        ASUPAN_ENABLED_CHATS.add(chat.id)
        save_asupan_groups()
        return await update.message.reply_text("Asupan diaktifkan di grup ini.")

    if sub == "disable":
        ASUPAN_ENABLED_CHATS.discard(chat.id)
        save_asupan_groups()
        return await update.message.reply_text("Asupan dimatikan di grup ini.")

    if sub == "status":
        if chat.id in ASUPAN_ENABLED_CHATS:
            return await update.message.reply_text(
                "Asupan <b>AKTIF</b> di grup ini.",
                parse_mode="HTML"
            )
        return await update.message.reply_text(
            "Asupan <b>TIDAK AKTIF</b> di grup ini.",
            parse_mode="HTML"
        )

    if sub == "list":
        if user.id not in OWNER_ID:
            return

        if not ASUPAN_ENABLED_CHATS:
            return await update.message.reply_text("Belum ada grup yang diizinkan asupan.")

        lines = ["<b>Grup Asupan Aktif</b>\n"]
        for cid in ASUPAN_ENABLED_CHATS:
            try:
                c = await bot.get_chat(cid)
                title = c.title or c.username or "Unknown"
                lines.append(f"• {html.escape(title)}")
            except Exception:
                lines.append(f"• <code>{cid}</code>")

        return await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML"
        )
    
async def autodel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if chat.type == "private":
        return

    if not await is_admin_or_owner(update, context):
        return

    if not context.args:
        return await update.message.reply_text(
            "<b>🗑 Auto Delete Asupan</b>\n\n"
            "• <code>/autodel enable</code>\n"
            "• <code>/autodel disable</code>\n"
            "• <code>/autodel status</code>\n"
            "• <code>/autodel list</code>",
            parse_mode="HTML"
        )

    arg = context.args[0].lower()

    if arg == "enable":
        AUTODEL_ENABLED_CHATS.add(chat.id)
        save_autodel_groups()
        return await update.message.reply_text("Auto delete asupan diaktifkan di grup ini.")

    if arg == "disable":
        AUTODEL_ENABLED_CHATS.discard(chat.id)
        save_autodel_groups()
        return await update.message.reply_text("Auto delete asupan dimatikan di grup ini.")

    if arg == "status":
        status = "AKTIF" if is_autodel_enabled(chat.id) else "NONAKTIF"
        return await update.message.reply_text(
            f"📌 Status auto delete asupan: <b>{status}</b>",
            parse_mode="HTML"
        )

    if arg == "list":
        if user.id not in OWNER_ID:
            return

        if not AUTODEL_ENABLED_CHATS:
            return await update.message.reply_text(
                "Tidak ada grup dengan auto delete asupan aktif."
            )

        lines = ["<b>Grup Auto Delete Asupan Aktif</b>\n"]
        for cid in AUTODEL_ENABLED_CHATS:
            try:
                c = await context.bot.get_chat(cid)
                name = c.title or c.username or "Unknown"
                lines.append(f"• {html.escape(name)}")
            except Exception:
                lines.append(f"• <code>{cid}</code>")

        return await update.message.reply_text(
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
        "tante holic",
        "cewe cantik",
        "cewe sma",
        "cewe tanktop",
        "#tanteholic",
        "shsshlla",
        "Seeazeee",
        "hi,its me tatut",
        "billaazz",               
        "innova.kasih.4",
        "tobrut",
        "tanktopstyle",
        "tanktop",
        "geolgeol",
        "zaraxhel",
        "verllyyaling",
        "eunicetjoaa",
        "nasi kfc",
        "fakebody",
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
                chat_id=LOG_CHAT_ID,
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

    if ASUPAN_FETCHING or not LOG_CHAT_ID:
        return

    ASUPAN_FETCHING = True
    try:
        while len(ASUPAN_CACHE) < ASUPAN_PREFETCH_SIZE:
            try:
                url = await fetch_asupan_tikwm(None)

                msg = await bot.send_video(
                    chat_id=LOG_CHAT_ID,
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
            chat_id=LOG_CHAT_ID,
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
        chat_id=LOG_CHAT_ID,
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
                "🚫 Fitur asupan tidak tersedia di grup ini.",
                parse_mode="HTML"
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
                _expire_asupan_job,
                ASUPAN_AUTO_DELETE_SEC,
                data={
                    "chat_id": chat.id,
                    "asupan_msg_id": sent.message_id,
                    "reply_to": update.message.message_id,
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

    if user_id not in OWNER_ID:
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
            old_job = ASUPAN_DELETE_JOBS.get(msg_id)
            if old_job:
                old_job.schedule_removal()
                ASUPAN_DELETE_JOBS.pop(msg_id, None)

        data = await get_asupan_fast(context.bot, keyword)

        await q.message.edit_media(
            media=InputMediaVideo(media=data["file_id"]),
            reply_markup=asupan_keyboard(owner_id)
        )

        if q.message.chat.type != "private" and is_autodel_enabled(q.message.chat_id):
            reply_to = (
                q.message.reply_to_message.message_id
                if q.message.reply_to_message
                else None
            )
            
            job = context.application.job_queue.run_once(
                _expire_asupan_job,
                ASUPAN_AUTO_DELETE_SEC,
                data={
                    "chat_id": q.message.chat_id,
                    "asupan_msg_id": msg_id,
                    "reply_to": reply_to,
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
    if not LOG_CHAT_ID:
        log.warning("[ASUPAN STARTUP] Chat_id is empty")
        return

    try:
        data = await get_asupan_fast(bot)

        msg = await bot.send_video(
            chat_id=LOG_CHAT_ID,
            video=data["file_id"],
            disable_notification=True
        )

        await msg.delete()

        log.info("[ASUPAN STARTUP] Warmup success")

    except Exception as e:
        log.warning(f"[ASUPAN STARTUP] Failed: {e}")

## Credit 
## Special thanks to Pikachu for the inspiration behind the *asupan* feature.  
## Telegram channel: https://t.me/pikachukocak5
