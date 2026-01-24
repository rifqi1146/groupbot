import os
import json
import html 

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
)
from telegram.ext import ContextTypes

from utils.config import OWNER_ID

#welcome 
WELCOME_ENABLED_CHATS = set()
WELCOME_FILE = "data/welcome_chats.json"

VERIFY_FILE = "data/verified_users.json"
VERIFIED_USERS = {}

def load_verified():
    global VERIFIED_USERS
    if not os.path.exists(VERIFY_FILE):
        VERIFIED_USERS = {}
        return
    try:
        with open(VERIFY_FILE, "r") as f:
            data = json.load(f)
            VERIFIED_USERS = {
                int(k): set(v) for k, v in data.items()
            }
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
    with open(WELCOME_FILE, "w") as f:
        json.dump({"chats": list(WELCOME_ENABLED_CHATS)}, f, indent=2)
      
def verify_keyboard(user_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Klik Untuk Verifikasi",
                callback_data=f"verify:{user_id}"
            )
        ]
    ])
    
async def wlc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id not in OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    if not context.args:
        return await update.message.reply_text(
            "Gunakan:\n"
            "<code>/wlc on</code>\n"
            "<code>/wlc off</code>",
            parse_mode="HTML"
        )

    mode = context.args[0].lower()

    if mode == "on":
        WELCOME_ENABLED_CHATS.add(chat.id)
        save_welcome_chats()
        await update.message.reply_text("✅ Welcome message diaktifkan.")
    elif mode == "off":
        WELCOME_ENABLED_CHATS.discard(chat.id)
        save_welcome_chats()
        await update.message.reply_text("🚫 Welcome message dimatikan.")
    else:
        await update.message.reply_text("❌ Gunakan <code>on</code> atau <code>off</code>.", parse_mode="HTML")
          
async def welcome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat

    if chat.id not in WELCOME_ENABLED_CHATS:
        return

    for user in msg.new_chat_members:
        # mute user
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False)
        )

        username = f"@{user.username}" if user.username else "—"
        chatname = chat.title or "this group"
        fullname = user.full_name

        text = (
            f"👋 <b>Hai {fullname}</b>\n"
            f"Selamat datang di <b>{chatname}</b> ✨\n\n"
            f"🧾 <b>User Information</b>\n"
            f"🆔 ID       : <code>{user.id}</code>\n"
            f"👤 Name     : {fullname}\n"
            f"🔖 Username : {username}\n\n"
        )

        await msg.reply_text(
            text,
            reply_markup=verify_keyboard(user.id),
            parse_mode="HTML"
        )

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return

    await q.answer()

    chat = q.message.chat
    user = q.from_user
    data = q.data

    if not data.startswith("verify:"):
        return

    target_id = int(data.split(":")[1])

    if user.id != target_id:
        return await q.answer("❌ Ini bukan tombol kamu.", show_alert=True)

    VERIFIED_USERS.setdefault(chat.id, set()).add(user.id)
    save_verified()

    await context.bot.restrict_chat_member(
        chat_id=chat.id,
        user_id=user.id,
        permissions=ChatPermissions(
            can_send_messages=True,
        )
    )

    await q.edit_message_text(
        "✅ <b>Verifikasi berhasil!</b>\n"
        "Sekarang kamu bisa ngobrol di grup 😄",
        parse_mode="HTML"
    )
    