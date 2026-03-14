from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def asupan_keyboard(owner_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔄 Next Asupan",
                callback_data=f"asupan:next:{owner_id}"
            )
        ]
    ])