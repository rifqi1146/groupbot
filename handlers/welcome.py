import os
import json
import random

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
)
from telegram.ext import ContextTypes

from utils.config import OWNER_ID

WELCOME_ENABLED_CHATS = set()
WELCOME_FILE = "data/welcome_chats.json"

VERIFY_FILE = "data/verified_users.json"
VERIFIED_USERS = {}

PENDING_VERIFY = {}
WELCOME_MESSAGES = {}  

def load_verified():
    global VERIFIED_USERS
    if not os.path.exists(VERIFY_FILE):
        VERIFIED_USERS = {}
        return
    try:
        with open(VERIFY_FILE, "r") as f:
            data = json.load(f)
            VERIFIED_USERS = {int(k): set(v) for k, v in data.items()}
    except Exception:
        VERIFIED_USERS = {}


def save_verified():
    os.makedirs("data", exist_ok=True)
    with open(VERIFY_FILE, "w") as f:
        json.dump(
            {str(k): list(v) for k, v in VERIFIED_USERS.items()},
            f,
            indent=2
        )


def load_welcome_chats():
    global WELCOME_ENABLED_CHATS
    if not os.path.exists(WELCOME_FILE):
        WELCOME_ENABLED_CHATS = set()
        return
    try:
        with open(WELCOME_FILE, "r") as f:
            data = json.load(f)
            WELCOME_ENABLED_CHATS = set(data.get("chats", []))
    except Exception:
        WELCOME_ENABLED_CHATS = set()


def save_welcome_chats():
    os.makedirs("data", exist_ok=True)
    with open(WELCOME_FILE, "w") as f:
        json.dump({"chats": list(WELCOME_ENABLED_CHATS)}, f, indent=2)

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
        "Jawab soal Matetika berikut 👇\n\n"
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
    await q.answer()

    _, chat_id, user_id, chosen = q.data.split(":")
    chat_id = int(chat_id)
    user_id = int(user_id)
    chosen = int(chosen)

    if q.from_user.id != user_id:
        return await q.answer("❌ Bukan tombol lu.", show_alert=True)

    pending = PENDING_VERIFY.get(user_id)
    if not pending or pending["chat_id"] != chat_id:
        return await q.answer("❌ Verifikasi invalid.", show_alert=True)

    if chosen != pending["answer"]:
        text, keyboard = generate_math_question(user_id, chat_id)
        return await q.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

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

    VERIFIED_USERS.setdefault(chat_id, set()).add(user_id)
    save_verified()
    PENDING_VERIFY.pop(user_id, None)

    if user_id in WELCOME_MESSAGES:
        g_chat_id, msg_id = WELCOME_MESSAGES.pop(user_id)
        try:
            await context.bot.delete_message(g_chat_id, msg_id)
        except Exception:
            pass

    await q.message.edit_text("✅ Verifikasi berhasil. Balik ke grup.")