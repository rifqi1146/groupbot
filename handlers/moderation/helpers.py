import html
import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes

from database.moderation_db import lookup_user_id

log = logging.getLogger(__name__)

DURATION_RE = re.compile(r"^(\d+)([smhdw])$", re.I)


def get_message_thread_id(msg) -> int | None:
    if not msg:
        return None

    thread_id = getattr(msg, "message_thread_id", None)
    if thread_id is None:
        return None

    try:
        return int(thread_id)
    except Exception:
        return None


def get_topic_reply_kwargs(msg) -> dict:
    thread_id = get_message_thread_id(msg)
    if thread_id is None:
        return {}
    return {"message_thread_id": thread_id}


async def reply_in_topic(msg, text: str, **kwargs):
    if not msg:
        return None
    kwargs = {**get_topic_reply_kwargs(msg), **kwargs}
    return await msg.reply_text(text, **kwargs)


def parse_duration(raw: str) -> tuple[datetime | None, str | None]:
    m = DURATION_RE.match((raw or "").strip())
    if not m:
        return None, None

    n = int(m.group(1))
    unit = m.group(2).lower()

    if n <= 0:
        return None, None

    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    seconds = n * mult
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    unit_name = {"s": "sec", "m": "min", "h": "hour", "d": "day", "w": "week"}[unit]
    human = f"{n} {unit_name}{'' if n == 1 else 's'}"

    return until, human


def mention_html(user_id: int, name: str) -> str:
    safe = html.escape(name or "User")
    return f'<a href="tg://user?id={int(user_id)}">{safe}</a>'


def display_name(obj) -> str:
    if not obj:
        return ""
    first = getattr(obj, "first_name", "") or ""
    last = getattr(obj, "last_name", "") or ""
    username = getattr(obj, "username", "") or ""
    name = (first + (" " + last if last else "")).strip()
    if name:
        return name
    if username:
        return f"@{username}"
    return ""


def text_mention_user_from_message(msg, token: str | None):
    if not msg or not getattr(msg, "entities", None):
        return None

    if not token:
        for ent in msg.entities:
            if ent.type == "text_mention" and ent.user:
                return ent.user
        return None

    t = (token or "").strip()
    if not t:
        return None

    text = msg.text or ""
    for ent in msg.entities:
        if ent.type == "text_mention" and ent.user:
            try:
                part = text[ent.offset : ent.offset + ent.length]
            except Exception:
                continue
            if part == t:
                return ent.user

    return None


def extract_duration_target_reason(args: list[str], has_reply_target: bool) -> tuple[datetime | None, str | None, str | None, str]:
    a = [x for x in (args or []) if (x or "").strip()]
    if not a:
        return None, None, None, "-"

    until, dur_human = parse_duration(a[0])

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


def extract_target_reason(args: list[str], has_reply_target: bool) -> tuple[str | None, str]:
    a = [x for x in (args or []) if (x or "").strip()]
    if has_reply_target:
        return None, (" ".join(a).strip() or "-")
    if not a:
        return None, "-"
    return a[0], (" ".join(a[1:]).strip() or "-")


async def resolve_target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str | None) -> int | None:
    msg = update.message

    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return int(msg.reply_to_message.from_user.id)

    ent_user = text_mention_user_from_message(msg, token)
    if ent_user and getattr(ent_user, "id", None):
        return int(ent_user.id)

    raw = (token or "").strip()
    if not raw:
        return None

    if raw.isdigit():
        return int(raw)

    if raw.startswith("@"):
        raw = raw[1:].strip()

    return lookup_user_id(raw)


async def resolve_target_user_obj_for_display(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str | None):
    msg = update.message

    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user

    ent_user = text_mention_user_from_message(msg, token)
    if ent_user:
        return ent_user

    return None


async def resolve_user_obj_for_display_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    chat = update.effective_chat

    if chat and chat.type in ("group", "supergroup"):
        try:
            member = await context.bot.get_chat_member(chat.id, int(user_id))
            user = getattr(member, "user", None)
            if user:
                return user
        except Exception as e:
            log.warning(
                "Failed to get chat member for moderation display | chat_id=%s user_id=%s err=%s",
                getattr(chat, "id", None),
                user_id,
                e,
            )

    try:
        return await context.bot.get_chat(int(user_id))
    except Exception as e:
        log.warning("Failed to get user chat for moderation display | user_id=%s err=%s", user_id, e)
        return None


def display_name_from_token(token: str | None) -> str:
    t = (token or "").strip()
    if not t:
        return "User"
    if t.startswith("@"):
        return t
    return "User"