import os
import json
import html 

from telegram import Update
from telegram.ext import ContextTypes

from utils.config import OWNER_ID

#welcome 
WELCOME_ENABLED_CHATS = set()
WELCOME_FILE = "welcome_chats.json"

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
      
async def wlc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if user.id != OWNER_ID:
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
        )

        try:
            photos = await context.bot.get_user_profile_photos(user.id, limit=1)
            if photos.total_count > 0:
                await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=photos.photos[0][-1].file_id,
                    caption=caption,
                    parse_mode="HTML"
                )
            else:
                await msg.reply_text(caption, parse_mode="HTML")
        except Exception:
            await msg.reply_text(caption, parse_mode="HTML")
                
