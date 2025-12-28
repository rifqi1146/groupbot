import time
from telegram import Update
from telegram.ext import ContextTypes

#ping
async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = time.perf_counter()

    msg = await update.message.reply_text("🏓 Pong...")

    end = time.perf_counter()
    latency = int((end - start) * 1000)

    await msg.edit_text(
        f"⚡ <b>Pong!</b>\n⏱️ Latency: <code>{latency} ms</code>",
        parse_mode="HTML"
    )

