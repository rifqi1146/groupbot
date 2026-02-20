import os, io, time, html, urllib.parse, sqlite3
import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session
from utils.config import OWNER_ID
from utils.text import bold, code

from handlers.groq import _emo, _can
from utils.nsfw import _extract_prompt_from_update


NSFW_DB = "data/nsfw.sqlite3"


def nsfw_db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(NSFW_DB)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS nsfw_groups (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def db():
    return sqlite3.connect(NSFW_DB)


def is_nsfw_allowed(chat_id: int, chat_type: str) -> bool:
    if chat_type == "private":
        return True

    con = db()
    try:
        cur = con.execute(
            "SELECT 1 FROM nsfw_groups WHERE chat_id=? AND enabled=1",
            (int(chat_id),),
        )
        return cur.fetchone() is not None
    finally:
        con.close()


def set_nsfw(chat_id: int, enabled: bool):
    con = db()
    try:
        now = time.time()
        if enabled:
            con.execute(
                """
                INSERT INTO nsfw_groups (chat_id, enabled, updated_at)
                VALUES (?,1,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  enabled=1,
                  updated_at=excluded.updated_at
                """,
                (int(chat_id), now),
            )
        else:
            con.execute(
                """
                INSERT INTO nsfw_groups (chat_id, enabled, updated_at)
                VALUES (?,0,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  enabled=0,
                  updated_at=excluded.updated_at
                """,
                (int(chat_id), now),
            )
        con.commit()
    finally:
        con.close()


def get_all_enabled():
    con = db()
    try:
        cur = con.execute(
            "SELECT chat_id FROM nsfw_groups WHERE enabled=1"
        )
        return [int(r[0]) for r in cur.fetchall()]
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
        m = await context.bot.get_chat_member(chat.id, user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def nsfw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        return

    arg = context.args[0].lower() if context.args else ""

    if arg == "list":
        if user.id not in OWNER_ID:
            return

        groups = get_all_enabled()

        if not groups:
            return await update.message.reply_text(
                "No NSFW-enabled groups.",
                parse_mode="HTML"
            )

        lines = ["<b>NSFW Enabled Groups</b>\n"]

        for gid in groups:
            try:
                c = await context.bot.get_chat(gid)
                title = html.escape(c.title or str(gid))
                lines.append(f"• {title}")
            except:
                lines.append(f"• <code>{gid}</code>")

        return await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML"
        )

    if not await is_admin_or_owner(update, context):
        return

    if arg == "enable":
        set_nsfw(chat.id, True)
        return await update.message.reply_text(
            "NSFW <b>ENABLED</b> in this group.",
            parse_mode="HTML"
        )

    if arg == "disable":
        set_nsfw(chat.id, False)
        return await update.message.reply_text(
            "NSFW <b>DISABLED</b> in this group.",
            parse_mode="HTML"
        )

    if arg == "status":
        status = "ENABLED" if is_nsfw_allowed(chat.id, chat.type) else "DISABLED"
        return await update.message.reply_text(
            f"NSFW status in this group: <b>{status}</b>",
            parse_mode="HTML"
        )

    return await update.message.reply_text(
        "<b>NSFW Settings</b>\n\n"
        "<code>/nsfw enable</code>\n"
        "<code>/nsfw disable</code>\n"
        "<code>/nsfw status</code>\n"
        "<code>/nsfw list</code>",
        parse_mode="HTML"
    )