from telegram import Update
from telegram.ext import ContextTypes

from utils.ai_utils import PERSONAS
from utils import premium_service
from utils import caca_db
from utils import caca_memory


async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    if not msg or not user:
        return

    user_id = user.id

    if not premium_service.check(user_id):
        return await msg.reply_text(
            "❌ Mode persona hanya untuk user premium.\n"
            "Selain premium dilarang ngatur 😤"
        )

    if not context.args:
        cur = caca_db.get_mode(user_id)
        return await msg.reply_text(
            f"🎭 Mode sekarang: <b>{cur}</b>\n\n"
            "Mode tersedia:\n"
            "• default\n"
            "• bokep\n"
            "• toxic",
            parse_mode="HTML"
        )

    mode = context.args[0].lower()
    if mode not in PERSONAS:
        return await msg.reply_text("❌ Mode tidak dikenal.")

    caca_db.set_mode(user_id, mode)
    await caca_memory.clear(user_id)

    return await msg.reply_text(
        f"🎭 Persona diubah ke <b>{mode}</b> ✨",
        parse_mode="HTML"
    )