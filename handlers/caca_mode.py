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
            "❌ Persona mode is available for premium users only.\n"
            "Non-premium users are not allowed to change it 😤"
        )

    if not context.args:
        cur = caca_db.get_mode(user_id)
        return await msg.reply_text(
            f"🎭 Current mode: <b>{cur}</b>\n\n"
            "Available modes:\n"
            "• default\n"
            "• bokep\n"
            "• sarkas\n"
            "• toxic\n"
            "• yandere\n"
            "• loli",
            parse_mode="HTML"
        )

    mode = context.args[0].lower()
    if mode not in PERSONAS:
        return await msg.reply_text("❌ Unknown mode.")

    await caca_db.set_mode(user_id, mode)
    await caca_memory.clear(user_id)

    return await msg.reply_text(
        f"🎭 Persona changed to <b>{mode}</b> ✨",
        parse_mode="HTML"
    )