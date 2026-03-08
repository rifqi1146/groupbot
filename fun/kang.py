import re
from telegram import Update, InputSticker
from telegram.ext import ContextTypes


def _slug_name(text: str, fallback: str = "user") -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def _pick_user_pack_base(user) -> str:
    username = (getattr(user, "username", "") or "").strip()
    first_name = (getattr(user, "first_name", "") or "").strip()
    if username:
        return _slug_name(username, "user")
    if first_name:
        return _slug_name(first_name, "user")
    return f"user{getattr(user, 'id', 0)}"


def _pick_emoji(args: list[str]) -> str:
    if args:
        value = (args[0] or "").strip()
        if value:
            return value
    return "🤍"


async def kang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user

    if not msg or not user:
        return

    reply = msg.reply_to_message
    if not reply:
        return await msg.reply_text("Reply ke sticker yang mau dikang.")

    sticker = reply.sticker
    if not sticker:
        return await msg.reply_text("Reply ke sticker")

    if sticker.type and str(sticker.type).lower().endswith("custom_emoji"):
        return await msg.reply_text("Test.")

    wait = await msg.reply_text("Sedang nyolong sticker...")

    try:
        me = await context.bot.get_me()
        bot_username = (me.username or "bot").lower()
        bot_first_name = me.first_name or "Bot"

        pack_base = _pick_user_pack_base(user)
        pack_name = f"{pack_base}_by_{bot_username}"
        pack_name = pack_name[:64]

        if not pack_name.endswith(f"_by_{bot_username}"):
            suffix = f"_by_{bot_username}"
            room = 64 - len(suffix)
            pack_name = f"{pack_base[:room]}{suffix}"

        pack_title_name = user.first_name or user.username or f"User {user.id}"
        pack_title = f"{pack_title_name} by {bot_first_name}"
        emoji = _pick_emoji(context.args or [])

        input_sticker = InputSticker(
            sticker=sticker.file_id,
            emoji_list=[emoji],
            format=sticker.format,
        )

        created = False

        try:
            await context.bot.get_sticker_set(pack_name)
        except Exception:
            await context.bot.create_new_sticker_set(
                user_id=user.id,
                name=pack_name,
                title=pack_title[:64],
                stickers=[input_sticker],
            )
            created = True

        if not created:
            await context.bot.add_sticker_to_set(
                user_id=user.id,
                name=pack_name,
                sticker=input_sticker,
            )

        await wait.edit_text(
            "Berhasil dikang\n\n"
            f"Pack: https://t.me/addstickers/{pack_name}"
        )

    except Exception as e:
        await wait.edit_text(f"Gagal kang sticker: {e}")