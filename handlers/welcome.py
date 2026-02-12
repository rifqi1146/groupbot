import os
import random
import time
import sqlite3

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
)
from telegram.ext import ContextTypes

from utils.config import OWNER_ID

WELCOME_VERIFY_DB = "data/welcome_verify.sqlite3"

WELCOME_ENABLED_CHATS = set()
VERIFIED_USERS = {}

PENDING_VERIFY = {}
WELCOME_MESSAGES = {}


def _wv_db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(WELCOME_VERIFY_DB)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS welcome_chats (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS verified_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                verified_at REAL NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_welcome (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )

        con.commit()
    finally:
        con.close()


def load_welcome_chats():
    global WELCOME_ENABLED_CHATS
    _wv_db_init()
    con = sqlite3.connect(WELCOME_VERIFY_DB)
    try:
        cur = con.execute("SELECT chat_id FROM welcome_chats WHERE enabled=1")
        WELCOME_ENABLED_CHATS = {int(r[0]) for r in cur.fetchall() if r and r[0] is not None}
    finally:
        con.close()


def save_welcome_chats():
    _wv_db_init()
    con = sqlite3.connect(WELCOME_VERIFY_DB)
    try:
        now = time.time()
        con.execute("BEGIN")
        con.execute("UPDATE welcome_chats SET enabled=0, updated_at=?", (now,))
        if WELCOME_ENABLED_CHATS:
            con.executemany(
                """
                INSERT INTO welcome_chats (chat_id, enabled, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  enabled=1,
                  updated_at=excluded.updated_at
                """,
                [(int(cid), now) for cid in WELCOME_ENABLED_CHATS],
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


def load_verified():
    global VERIFIED_USERS
    _wv_db_init()
    con = sqlite3.connect(WELCOME_VERIFY_DB)
    try:
        cur = con.execute("SELECT chat_id, user_id FROM verified_users")
        tmp = {}
        for chat_id, user_id in cur.fetchall():
            tmp.setdefault(int(chat_id), set()).add(int(user_id))
        VERIFIED_USERS = tmp
    finally:
        con.close()


def save_verified_user(chat_id: int, user_id: int):
    _wv_db_init()
    con = sqlite3.connect(WELCOME_VERIFY_DB)
    try:
        now = time.time()

        con.execute(
            """
            INSERT INTO verified_users (chat_id, user_id, verified_at)
            VALUES (?, ?, ?)
            """,
            (int(chat_id), int(user_id), now),
        )

        con.commit()
    except sqlite3.IntegrityError:
        try:
            con.execute(
                "UPDATE verified_users SET verified_at=? WHERE chat_id=? AND user_id=?",
                (now, int(chat_id), int(user_id)),
            )
            con.commit()
        finally:
            pass
    finally:
        con.close()


def save_pending_welcome(chat_id: int, user_id: int, message_id: int):
    _wv_db_init()
    con = sqlite3.connect(WELCOME_VERIFY_DB)
    try:
        now = time.time()
        con.execute(
            """
            INSERT INTO pending_welcome (chat_id, user_id, message_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (int(chat_id), int(user_id), int(message_id), now),
        )
        con.commit()
    except sqlite3.IntegrityError:
        try:
            con.execute(
                "UPDATE pending_welcome SET message_id=?, created_at=? WHERE chat_id=? AND user_id=?",
                (int(message_id), now, int(chat_id), int(user_id)),
            )
            con.commit()
        finally:
            pass
    finally:
        con.close()


def pop_pending_welcome(chat_id: int, user_id: int) -> int | None:
    _wv_db_init()
    con = sqlite3.connect(WELCOME_VERIFY_DB)
    try:
        cur = con.execute(
            "SELECT message_id FROM pending_welcome WHERE chat_id=? AND user_id=?",
            (int(chat_id), int(user_id)),
        )
        row = cur.fetchone()
        con.execute(
            "DELETE FROM pending_welcome WHERE chat_id=? AND user_id=?",
            (int(chat_id), int(user_id)),
        )
        con.commit()
        if not row:
            return None
        return int(row[0])
    finally:
        con.close()


def generate_math_question(user_id: int, chat_id: int):
    a = random.randint(20, 99)
    b = random.randint(1, 50)
    if b > a:
        a, b = b, a

    answer = a - b

    wrong = set()
    while len(wrong) < 3:
        x = random.randint(answer - 30, answer + 30)
        if x != answer and x > 0:
            wrong.add(x)

    options = list(wrong) + [answer]
    random.shuffle(options)

    PENDING_VERIFY[user_id] = {
        "chat_id": chat_id,
        "answer": answer
    }

    buttons = [
        [InlineKeyboardButton(str(o), callback_data=f"verify_ans:{chat_id}:{user_id}:{o}")]
        for o in options
    ]

    text = (
        "Jawab soal Matematika berikut 👇\n\n"
        f"<b>{a} - {b} = ?</b>\n\n"
    )

    return text, InlineKeyboardMarkup(buttons)


def verify_keyboard(user_id: int, chat_id: int, bot_username: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Verifikasi",
                url=f"https://t.me/{bot_username}?start=verify_{chat_id}_{user_id}"
            )
        ]
    ])


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


async def wlc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if not await is_admin_or_owner(update, context):
        return

    if not context.args:
        return await update.message.reply_text(
            "Gunakan:\n"
            "<code>/wlc enable</code>\n"
            "<code>/wlc disable</code>",
            parse_mode="HTML"
        )

    mode = context.args[0].lower()

    if mode == "enable":
        WELCOME_ENABLED_CHATS.add(chat.id)
        save_welcome_chats()
        await update.message.reply_text("✅ Welcome message diaktifkan.")
    elif mode == "disable":
        WELCOME_ENABLED_CHATS.discard(chat.id)
        save_welcome_chats()
        await update.message.reply_text("🚫 Welcome message dimatikan.")
    else:
        await update.message.reply_text(
            "❌ Gunakan <code>enable</code> atau <code>disable</code>.",
            parse_mode="HTML"
        )


async def welcome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat

    if chat.id not in WELCOME_ENABLED_CHATS:
        return

    for user in msg.new_chat_members:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False)
            )
        except Exception:
            pass

        username = f"@{user.username}" if user.username else "—"
        fullname = user.full_name
        chatname = chat.title or "this group"

        caption = (
            f"👋 <b>Hai {fullname}</b>\n"
            f"Selamat datang di <b>{chatname}</b> ✨\n\n"
            f"🧾 <b>User Information</b>\n"
            f"🆔 ID       : <code>{user.id}</code>\n"
            f"👤 Name     : {fullname}\n"
            f"🔖 Username : {username}\n\n"
            f"🔐 <b>Silakan verifikasi terlebih dahulu</b>"
        )

        try:
            photos = await context.bot.get_user_profile_photos(user_id=user.id, limit=1)
            if photos.total_count > 0:
                sent = await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=photos.photos[0][-1].file_id,
                    caption=caption,
                    reply_markup=verify_keyboard(user.id, chat.id, context.bot.username),
                    parse_mode="HTML"
                )
            else:
                sent = await msg.reply_text(
                    caption,
                    reply_markup=verify_keyboard(user.id, chat.id, context.bot.username),
                    parse_mode="HTML"
                )
        except Exception:
            sent = await msg.reply_text(
                caption,
                reply_markup=verify_keyboard(user.id, chat.id, context.bot.username),
                parse_mode="HTML"
            )

        WELCOME_MESSAGES[user.id] = (chat.id, sent.message_id)
        try:
            save_pending_welcome(chat.id, user.id, sent.message_id)
        except Exception:
            pass


async def start_verify_pm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return

    arg = context.args[0]
    if not arg.startswith("verify_"):
        return

    _, chat_id, user_id = arg.split("_")
    chat_id = int(chat_id)
    user_id = int(user_id)

    if update.effective_user.id != user_id:
        return

    text, keyboard = generate_math_question(user_id, chat_id)

    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


async def verify_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query

    _, chat_id, user_id, chosen = q.data.split(":")
    chat_id = int(chat_id)
    user_id = int(user_id)
    chosen = int(chosen)

    if q.from_user.id != user_id:
        await q.answer("❌ Bukan tombol lu.", show_alert=True)
        return

    pending = PENDING_VERIFY.get(user_id)
    if not pending or pending["chat_id"] != chat_id:
        await q.answer("❌ Verifikasi invalid.", show_alert=True)
        return

    if chosen != pending["answer"]:
        await q.answer("❌ Salah. Coba lagi.", show_alert=False)
        text, keyboard = generate_math_question(user_id, chat_id)
        try:
            await q.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await q.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
        return

    await q.answer("✅ Verifikasi berhasil!", show_alert=False)

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_invite_users=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_messages=True,
                can_send_other_messages=True,
                can_send_photos=True,
                can_send_polls=True,
                can_send_video_notes=True,
                can_send_videos=True,
                can_send_voice_notes=True,
            )
        )
    except Exception:
        pass

    VERIFIED_USERS.setdefault(chat_id, set()).add(user_id)
    try:
        save_verified_user(chat_id, user_id)
    except Exception:
        pass

    PENDING_VERIFY.pop(user_id, None)

    msg_id = None
    if user_id in WELCOME_MESSAGES:
        try:
            g_chat_id, m_id = WELCOME_MESSAGES.pop(user_id)
            if g_chat_id == chat_id:
                msg_id = m_id
        except Exception:
            msg_id = None

    if msg_id is None:
        try:
            msg_id = pop_pending_welcome(chat_id, user_id)
        except Exception:
            msg_id = None

    if msg_id:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

    try:
        await q.message.edit_text("✅ Verifikasi berhasil. Anda dapat kembali ke grup.")
    except Exception:
        try:
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="✅ Verifikasi berhasil. Anda dapat kembali ke grup."
            )
        except Exception:
            pass


try:
    _wv_db_init()
except Exception:
    pass

try:
    load_welcome_chats()
except Exception:
    pass

try:
    load_verified()
except Exception:
    pass
