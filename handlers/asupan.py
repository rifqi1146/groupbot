import os
import json
import html
import time
import random
import asyncio
import logging
import aiohttp
import sqlite3

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

log = logging.getLogger(__name__)

ASUPAN_DB_PATH = "data/asupan.sqlite3"

ASUPAN_CACHE = []
ASUPAN_PREFETCH_SIZE = 5
ASUPAN_KEYWORD_CACHE = {}
ASUPAN_MESSAGE_KEYWORD = {}
ASUPAN_FETCHING = False
ASUPAN_ENABLED_CHATS = set()
ASUPAN_DELETE_JOBS = {}
ASUPAN_AUTO_DELETE_SEC = 300
ASUPAN_COOLDOWN = {}
ASUPAN_COOLDOWN_SEC = 5

AUTODEL_ENABLED_CHATS = set()


def _asupan_db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(ASUPAN_DB_PATH)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS asupan_groups (
                source_file TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                added_at REAL NOT NULL,
                PRIMARY KEY (source_file, chat_id)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS asupan_autodel (
                source_file TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                enabled INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (source_file, chat_id)
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _db_load_enabled(table: str) -> set[int]:
    con = sqlite3.connect(ASUPAN_DB_PATH)
    try:
        if table == "asupan_autodel":
            cur = con.execute("SELECT chat_id FROM asupan_autodel WHERE enabled=1")
            rows = cur.fetchall()
            if rows:
                return {int(r[0]) for r in rows if r and r[0] is not None}

            cur = con.execute("SELECT chat_id FROM asupan_autodel")
            rows = cur.fetchall()
            return {int(r[0]) for r in rows if r and r[0] is not None}

        cur = con.execute("SELECT chat_id FROM asupan_groups")
        rows = cur.fetchall()
        return {int(r[0]) for r in rows if r and r[0] is not None}

    finally:
        con.close()


def _db_set_enabled(table: str, s: set[int]):
    con = sqlite3.connect(ASUPAN_DB_PATH)
    try:
        con.execute("BEGIN")
        now = time.time()
        src = "runtime"

        if table == "asupan_autodel":
            con.execute("UPDATE asupan_autodel SET enabled=0, updated_at=?", (now,))
            if s:
                con.executemany(
                    """
                    INSERT INTO asupan_autodel (source_file, chat_id, enabled, updated_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(source_file, chat_id) DO UPDATE SET
                      enabled=1,
                      updated_at=excluded.updated_at
                    """,
                    [(src, int(cid), now) for cid in s],
                )

        else:
            if s:
                con.executemany(
                    """
                    INSERT INTO asupan_groups (source_file, chat_id, added_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_file, chat_id) DO UPDATE SET
                      added_at=excluded.added_at
                    """,
                    [(src, int(cid), now) for cid in s],
                )

            con.execute(
                "DELETE FROM asupan_groups WHERE source_file=? AND chat_id NOT IN (%s)"
                % (",".join("?" * len(s)) if s else "-1"),
                (src, *[int(cid) for cid in s]) if s else (src,),
            )

        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()


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
    try:
        _asupan_db_init()
        AUTODEL_ENABLED_CHATS = _db_load_enabled("asupan_autodel")
    except Exception:
        AUTODEL_ENABLED_CHATS = set()


def save_autodel_groups():
    try:
        _asupan_db_init()
        _db_set_enabled("asupan_autodel", AUTODEL_ENABLED_CHATS)
    except Exception:
        pass


def is_autodel_enabled(chat_id: int) -> bool:
    return chat_id in AUTODEL_ENABLED_CHATS


def save_asupan_groups():
    try:
        _asupan_db_init()
        _db_set_enabled("asupan_groups", ASUPAN_ENABLED_CHATS)
    except Exception:
        pass


def is_asupan_enabled(chat_id: int) -> bool:
    return chat_id in ASUPAN_ENABLED_CHATS


def load_asupan_groups():
    global ASUPAN_ENABLED_CHATS
    try:
        _asupan_db_init()
        ASUPAN_ENABLED_CHATS = _db_load_enabled("asupan_groups")
    except Exception:
        ASUPAN_ENABLED_CHATS = set()


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


def asupan_keyboard(owner_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 Ganti Asupan",
            callback_data=f"asupan:next:{owner_id}"
        )]
    ])


async def fetch_asupan_tikwm(keyword: str | None = None):
    default_keywords = [
        "tante holic",
        "araasshr",
        "keiz1a",
        "tataaasiuu20",
        "nasluvt",
        "dimpledtataww",
        "lvme4awaa",
        "liveid63",
        "urvelsyn",
        "cewe cantik",
        "cewe sma",
        "rerereyaaa",
        "cewe smp",
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
        "zaraxhel",
        "verllyyaling",
        "eunicetjoaa",
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


try:
    _asupan_db_init()
except Exception:
    pass

try:
    load_asupan_groups()
except Exception:
    pass

try:
    load_autodel_groups()
except Exception:
    pass

## Credit 
## Special thanks to Pikachu for the inspiration behind the *asupan* feature.  
## Telegram channel: https://t.me/pikachukocak5
