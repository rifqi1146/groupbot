import random
from telegram import Update
from telegram.ext import ContextTypes

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

async def ship_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat

    users = []

    if msg.reply_to_message and msg.reply_to_message.from_user:
        users.append(msg.reply_to_message.from_user)

    for ent in msg.entities or []:
        if ent.type == "text_mention" and ent.user:
            users.append(ent.user)

    if len(users) < 2:
        admins = await context.bot.get_chat_administrators(chat.id)
        members = [m.user for m in admins if m.user]
    
        if len(members) < 2:
            return await msg.reply_text("❌ Belum cukup orang buat di-ship.")
    
        users = random.sample(members, 2)

    u1, u2 = users[:2]

    percent = random.randint(50, 100)
    msg_text = random.choice(SHIP_MESSAGES)
    ending = random.choice(SHIP_ENDING)

    text = (
        f"💖 <b>SHIP RESULT</b>\n\n"
        f"👤 {u1.first_name}\n"
        f"👤 {u2.first_name}\n\n"
        f"❤️ <b>Love Meter:</b> <code>{percent}%</code>\n\n"
        f"{msg_text}\n"
        f"<i>{ending}</i>"
    )

    await msg.reply_text(text, parse_mode="HTML")