from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
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

    except Exception as e:
        print("[JOIN CHECK ERROR]", e)
        return False   # ⬅️ INI FIX UTAMA

def join_required_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Join Support Group",
                url=SUPPORT_GROUP_LINK
            )
        ]
    ])

async def require_join_or_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.callback_query:
        user = update.callback_query.from_user
        reply_target = update.callback_query.message
    elif update.message:
        user = update.message.from_user
        reply_target = update.message
    else:
        return False

    if not user:
        return False

    joined = await is_joined_support_group(user.id, context)
    if joined:
        return True

    text = (
        "<b>Untuk menggunakan fitur download</b>\n\n"
        "kamu wajib join dulu ke grup support.\n\n"
        "📢 <b>Support Group</b>\n"
    )

    try:
        if update.callback_query:
            await update.callback_query.answer(
                "Join dulu grup support ya 👀",
                show_alert=True
            )

        await reply_target.reply_text(
            text,
            reply_markup=join_required_keyboard(),
            parse_mode="HTML"
        )

    except Exception as e:
        print("[JOIN BLOCK ERROR]", e)

    return False