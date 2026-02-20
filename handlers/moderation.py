import os
import time
import sqlite3
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID

MODERATION_DB = "data/moderation.sqlite3"


def _db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(MODERATION_DB)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS moderation_groups (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _db():
    _db_init()
    return sqlite3.connect(MODERATION_DB)


def moderation_is_enabled(chat_id: int) -> bool:
    con = _db()
    try:
        row = con.execute(
            "SELECT enabled FROM moderation_groups WHERE chat_id=? LIMIT 1",
            (int(chat_id),),
        ).fetchone()
        return bool(row and int(row[0]) == 1)
    finally:
        con.close()


def moderation_set(chat_id: int, enabled: bool):
    con = _db()
    try:
        now = float(time.time())
        con.execute("BEGIN")
        con.execute(
            """
            INSERT INTO moderation_groups (chat_id, enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
              enabled=excluded.enabled,
              updated_at=excluded.updated_at
            """,
            (int(chat_id), 1 if enabled else 0, now),
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


async def _is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return False

    if user.id in OWNER_ID:
        return True

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        m = await context.bot.get_chat_member(chat.id, user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def _resolve_target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    msg = update.message
    if not msg:
        return None

    if msg.reply_to_message and msg.reply_to_message.from_user:
        return int(msg.reply_to_message.from_user.id)

    if not context.args:
        return None

    raw = (context.args[0] or "").strip()
    if not raw:
        return None

    if raw.isdigit():
        return int(raw)

    if raw.startswith("@"):
        raw = raw[1:].strip()

    try:
        c = await context.bot.get_chat(raw)
        if c and getattr(c, "id", None):
            return int(c.id)
    except Exception:
        pass

    return None


async def moderation_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not chat:
        return

    if chat.type not in ("group", "supergroup"):
        return await msg.reply_text("This command can only be used in groups.")

    if not await _is_admin_or_owner(update, context):
        return await msg.reply_text("You are not an admin.")

    arg = (context.args[0].lower().strip() if context.args else "")
    if arg == "enable":
        moderation_set(chat.id, True)
        return await msg.reply_text("Moderation is now <b>ENABLED</b> in this group.", parse_mode="HTML")

    if arg == "disable":
        moderation_set(chat.id, False)
        return await msg.reply_text("Moderation is now <b>DISABLED</b> in this group.", parse_mode="HTML")

    if arg == "status":
        st = "ENABLED" if moderation_is_enabled(chat.id) else "DISABLED"
        return await msg.reply_text(f"Moderation status: <b>{st}</b>", parse_mode="HTML")

    return await msg.reply_text(
        "<b>Moderation</b>\n\n"
        "<code>/moderation enable</code>\n"
        "<code>/moderation disable</code>\n"
        "<code>/moderation status</code>",
        parse_mode="HTML",
    )


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not chat:
        return

    if chat.type not in ("group", "supergroup"):
        return

    if not moderation_is_enabled(chat.id):
        return

    if not await _is_admin_or_owner(update, context):
        return await msg.reply_text("You are not an admin.")

    target_id = await _resolve_target_user_id(update, context)
    if not target_id:
        return await msg.reply_text("Reply to a user or use: <code>/ban @username</code> / <code>/ban user_id</code>", parse_mode="HTML")

    try:
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=target_id)
        return await msg.reply_text("Banned.")
    except Exception as e:
        return await msg.reply_text(f"Failed: <code>{str(e)}</code>", parse_mode="HTML")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not chat:
        return

    if chat.type not in ("group", "supergroup"):
        return

    if not moderation_is_enabled(chat.id):
        return

    if not await _is_admin_or_owner(update, context):
        return await msg.reply_text("You are not an admin.")

    target_id = await _resolve_target_user_id(update, context)
    if not target_id:
        return await msg.reply_text("Reply to a user or use: <code>/unban @username</code> / <code>/unban user_id</code>", parse_mode="HTML")

    try:
        await context.bot.unban_chat_member(chat_id=chat.id, user_id=target_id)
        return await msg.reply_text("Unbanned.")
    except Exception as e:
        return await msg.reply_text(f"Failed: <code>{str(e)}</code>", parse_mode="HTML")


try:
    _db_init()
except Exception:
    pass