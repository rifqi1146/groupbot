import os
import time
import html
import sqlite3
from datetime import datetime, timedelta, timezone

from telegram import Update, ChatPermissions
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


def _parse_duration(token: str) -> tuple[datetime | None, str | None]:
    t = (token or "").strip().lower()
    if not t:
        return None, None

    num = ""
    unit = ""
    for ch in t:
        if ch.isdigit():
            if unit:
                return None, None
            num += ch
        else:
            unit += ch

    if not num or not unit:
        return None, None

    if unit not in ("s", "m", "h", "d", "w"):
        return None, None

    n = int(num)
    if n <= 0:
        return None, None

    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    seconds = n * mult
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    unit_name = {"s": "sec", "m": "min", "h": "hour", "d": "day", "w": "week"}[unit]
    human = f"{n} {unit_name}{'' if n == 1 else 's'}"

    return until, human


async def _resolve_target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str | None) -> int | None:
    msg = update.message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return int(msg.reply_to_message.from_user.id)

    raw = (token or "").strip()
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


def _extract_duration_target_reason(args: list[str], has_reply_target: bool) -> tuple[datetime | None, str | None, str | None, str]:
    a = [x for x in (args or []) if (x or "").strip()]
    if not a:
        return None, None, None, "-"

    until, dur_human = _parse_duration(a[0])

    if has_reply_target:
        if until is not None:
            reason = " ".join(a[1:]).strip() or "-"
            return until, dur_human, None, reason
        reason = " ".join(a).strip() or "-"
        return None, None, None, reason

    if until is not None:
        target = a[1] if len(a) >= 2 else None
        reason = " ".join(a[2:]).strip() or "-"
        return until, dur_human, target, reason

    target = a[0]
    reason = " ".join(a[1:]).strip() or "-"
    return None, None, target, reason


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
        "<code>/moderation status</code>\n\n"
        "<b>Actions</b>\n"
        "<code>/ban [7d] &lt;reply|user&gt; [reason]</code>\n"
        "<code>/unban &lt;reply|user&gt;</code>\n"
        "<code>/mute [10m] &lt;reply|user&gt; [reason]</code>\n"
        "<code>/unmute &lt;reply|user&gt;</code>",
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

    has_reply = bool(msg.reply_to_message and msg.reply_to_message.from_user)
    until, dur_human, target_token, reason = _extract_duration_target_reason(context.args or [], has_reply)

    target_id = await _resolve_target_user_id(update, context, target_token)
    if not target_id:
        return await msg.reply_text(
            "Reply to a user or use:\n"
            "<code>/ban 7d @username toxic</code>\n"
            "<code>/ban 7d user_id toxic</code>",
            parse_mode="HTML",
        )

    try:
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=target_id, until_date=until)
        dur_txt = f"<b>Duration:</b> {html.escape(dur_human)}\n" if dur_human else "<b>Duration:</b> Permanent\n"
        return await msg.reply_text(
            "<b>Banned</b>\n"
            f"<b>User:</b> <code>{target_id}</code>\n"
            f"{dur_txt}"
            f"<b>Reason:</b> <code>{html.escape(reason)}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        return await msg.reply_text(f"Failed: <code>{html.escape(str(e))}</code>", parse_mode="HTML")


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

    has_reply = bool(msg.reply_to_message and msg.reply_to_message.from_user)
    _, _, target_token, _ = _extract_duration_target_reason(context.args or [], has_reply)

    target_id = await _resolve_target_user_id(update, context, target_token)
    if not target_id:
        return await msg.reply_text(
            "Reply to a user or use: <code>/unban @username</code> / <code>/unban user_id</code>",
            parse_mode="HTML",
        )

    try:
        await context.bot.unban_chat_member(chat_id=chat.id, user_id=target_id)
        return await msg.reply_text(
            "<b>Unbanned</b>\n"
            f"<b>User:</b> <code>{target_id}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        return await msg.reply_text(f"Failed: <code>{html.escape(str(e))}</code>", parse_mode="HTML")


async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    has_reply = bool(msg.reply_to_message and msg.reply_to_message.from_user)
    until, dur_human, target_token, reason = _extract_duration_target_reason(context.args or [], has_reply)

    target_id = await _resolve_target_user_id(update, context, target_token)
    if not target_id:
        return await msg.reply_text(
            "Reply to a user or use:\n"
            "<code>/mute 10m @username rusuh</code>\n"
            "<code>/mute 10m user_id rusuh</code>",
            parse_mode="HTML",
        )

    perms = ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target_id,
            permissions=perms,
            until_date=until,
        )
        dur_txt = f"<b>Duration:</b> {html.escape(dur_human)}\n" if dur_human else "<b>Duration:</b> Permanent\n"
        return await msg.reply_text(
            "<b>Muted</b>\n"
            f"<b>User:</b> <code>{target_id}</code>\n"
            f"{dur_txt}"
            f"<b>Reason:</b> <code>{html.escape(reason)}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        return await msg.reply_text(f"Failed: <code>{html.escape(str(e))}</code>", parse_mode="HTML")


async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    has_reply = bool(msg.reply_to_message and msg.reply_to_message.from_user)
    _, _, target_token, _ = _extract_duration_target_reason(context.args or [], has_reply)

    target_id = await _resolve_target_user_id(update, context, target_token)
    if not target_id:
        return await msg.reply_text(
            "Reply to a user or use: <code>/unmute @username</code> / <code>/unmute user_id</code>",
            parse_mode="HTML",
        )

    perms = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=False,
    )

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target_id,
            permissions=perms,
            until_date=None,
        )
        return await msg.reply_text(
            "<b>Unmuted</b>\n"
            f"<b>User:</b> <code>{target_id}</code>",
            parse_mode="HTML",
        )
    except Exception as e:
        return await msg.reply_text(f"Failed: <code>{html.escape(str(e))}</code>", parse_mode="HTML")


try:
    _db_init()
except Exception:
    pass