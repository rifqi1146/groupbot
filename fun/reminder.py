import re
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes

WIB_OFFSET = 7

def parse_time_wib(time_str: str):
    if not re.match(r"^\d{2}\.\d{2}$", time_str):
        return None

    h, m = map(int, time_str.split("."))
    if h > 23 or m > 59:
        return None

    now_utc = datetime.utcnow()
    now_wib = now_utc + timedelta(hours=WIB_OFFSET)

    target = now_wib.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now_wib:
        target += timedelta(days=1)

    return target

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=data["text"],
        parse_mode="HTML"
    )

async def reminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat

    if len(context.args) < 2:
        return await msg.reply_text(
            "❌ Format salah\n\n"
            "Contoh:\n"
            "/reminder 18.30 main ml @user1 @user2"
        )

    time_str = context.args[0]
    target_time = parse_time_wib(time_str)

    if not target_time:
        return await msg.reply_text("❌ Format jam harus HH.MM (WIB)")

    text_args = context.args[1:]
    text = " ".join(text_args)

    mentions = []
    for ent in msg.entities or []:
        if ent.type == "mention":
            mentions.append(ent.user)

    delay = (target_time - (datetime.utcnow() + timedelta(hours=WIB_OFFSET))).total_seconds()

    reminder_text = (
        f"⏰ <b>REMINDER</b>\n\n"
        f"{text}\n\n"
        f"<i>Waktu: {time_str} WIB</i>"
    )

    context.application.job_queue.run_once(
        reminder_job,
        when=delay,
        data={
            "chat_id": chat.id,
            "text": reminder_text,
        },
    )

    await msg.reply_text(
        f"✅ Reminder diset jam <b>{time_str} WIB</b>",
        parse_mode="HTML"
    )
    