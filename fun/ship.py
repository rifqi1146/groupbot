import os
import json
import random
from telegram import Update
from telegram.ext import ContextTypes

DATA_FILE = "data/users.json"

SHIP_MESSAGES = [
    "🥰 Kalian keliatan nyaman satu sama lain",
    "💗 Vibes-nya lembut dan saling ngerti",
    "🌸 Cocoknya tuh keliatan natural",
    "💞 Kayak saling nenangin tanpa sadar",
    "✨ Bareng-bareng keliatan lebih hidup",
    "🫶 Ada rasa aman di situ",
    "🌷 Kalo ngobrol pasti nyambung",
    "💫 Energinya bikin hangat",
    "🤍 Sederhana tapi kerasa",
    "🌼 Keliatan saling support",
]

SHIP_ENDING = [
    "Semoga selalu akur ya 🤍",
    "Lucu kalo beneran 🥹",
    "Doain yang terbaik ✨",
    "Siapa tau ini pertanda 🌸",
    "Pelan-pelan aja 💗",
    "Enjoy the moment 🫶",
]

def tag(u):
    return f'<a href="tg://user?id={u["id"]}">{u["name"]}</a>'

def load_users():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(data):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_user(chat_id, user):
    if not user or user.is_bot:
        return
    data = load_users()
    cid = str(chat_id)
    data.setdefault(cid, {})
    data[cid][str(user.id)] = {
        "id": user.id,
        "name": user.first_name,
    }
    save_users(data)

async def ship_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat

    if not msg or not chat:
        return

    add_user(chat.id, msg.from_user)

    users = []

    if msg.reply_to_message and msg.reply_to_message.from_user:
        add_user(chat.id, msg.reply_to_message.from_user)
        users.append({
            "id": msg.reply_to_message.from_user.id,
            "name": msg.reply_to_message.from_user.first_name,
        })

    for ent in msg.entities or []:
        if ent.type == "text_mention" and ent.user:
            add_user(chat.id, ent.user)
            users.append({
                "id": ent.user.id,
                "name": ent.user.first_name,
            })

    data = load_users().get(str(chat.id), {})
    pool = list(data.values())

    if len(users) < 2:
        if len(pool) < 2:
            return await msg.reply_text("❌ Belum cukup orang buat di-ship.")
        users = random.sample(pool, 2)

    u1, u2 = users[:2]

    percent = random.randint(50, 100)
    msg_text = random.choice(SHIP_MESSAGES)
    ending = random.choice(SHIP_ENDING)

    text = (
        f"💖 <b>SHIP RESULT</b>\n\n"
        f"👤 {tag(u1)}\n"
        f"👤 {tag(u2)}\n\n"
        f"❤️ <b>Love Meter:</b> <code>{percent}%</code>\n\n"
        f"{msg_text}\n"
        f"<i>{ending}</i>"
    )

    await msg.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True
    )