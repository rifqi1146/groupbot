from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

SUPPORT_GROUP_ID = -1003707701162
SUPPORT_GROUP_LINK = "https://t.me/kiyoshibot"


async def is_joined_support_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(
            SUPPORT_GROUP_ID,
            user_id
        )
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


def join_required_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔔 Join Support Group",
                url=SUPPORT_GROUP_LINK
            )
        ]
    ])


async def require_join_or_block(update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Return True kalau BOLEH lanjut
    Return False kalau HARUS DIHENTIKAN
    """
    user = update.effective_user
    chat = update.effective_chat

    if not user:
        return False

    joined = await is_joined_support_group(user.id, context)
    if joined:
        return True

    text = (
        "🚫 <b>Akses Ditolak</b>\n\n"
        "Untuk menggunakan fitur download,\n"
        "kamu wajib join dulu ke grup support bot.\n\n"
        "📢 <b>Support Group:</b>\n"
        "➡️ kiyoshi bot community"
    )

    try:
        if update.callback_query:
            await update.callback_query.answer("Join dulu grup support ya 👀", show_alert=True)
            await update.callback_query.message.reply_text(
                text,
                reply_markup=join_required_keyboard(),
                parse_mode="HTML"
            )
        elif update.message:
            await update.message.reply_text(
                text,
                reply_markup=join_required_keyboard(),
                parse_mode="HTML"
            )
    except Exception:
        pass

    return False