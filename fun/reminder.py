import re
from datetime import datetime, timedelta
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
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

async def reminder_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    job = context.application.job_queue.get_jobs_by_name(q.data)

    if not job:
        return await q.answer("❌ Reminder udah ga ada", show_alert=True)

    job = job[0]
    owner_id = job.data["user_id"]

    if q.from_user.id != owner_id:
        return await q.answer("❌ Ini bukan reminder lu", show_alert=True)

    job.schedule_removal()
    await q.message.edit_text("🗑️ Reminder dibatalin")
    await q.answer("✅ Reminder cancelled")

async def reminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if len(context.args) < 2:
        return await msg.reply_text(
            "❌ Format salah\n\n"
            "Contoh:\n"
            "/reminder 18.30 main ml @user1"
        )

    time_str = context.args[0]
    target_time = parse_time_wib(time_str)

    if not target_time:
        return await msg.reply_text("❌ Format jam harus HH.MM (WIB)")

    text = " ".join(context.args[1:])

    delay = (target_time - (datetime.utcnow() + timedelta(hours=WIB_OFFSET))).total_seconds()
    job_name = f"reminder:{chat.id}:{msg.id}"

    reminder_text = (
        f"⏰ <b>REMINDER</b>\n\n"
        f"{text}\n\n"
        f"<i>Waktu: {time_str} WIB</i>"
    )

    job = context.application.job_queue.run_once(
        reminder_job,
        when=delay,
        name=job_name,
        data={
            "chat_id": chat.id,
            "user_id": user.id,
            "text": reminder_text,
        },
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "❌ Cancel Reminder",
            callback_data=job_name
        )]
    ])

    await msg.reply_text(
        f"✅ Reminder diset jam <b>{time_str} WIB</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )