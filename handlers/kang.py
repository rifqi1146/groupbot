import os
import re
import io
import tempfile
from PIL import Image
from telegram import Update, InputSticker, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from handlers.join import require_join_or_block

MAX_STICKERS_PER_PACK = 120

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

def _sticker_format_from_obj(sticker) -> str | None:
    if not sticker:
        return None
    if getattr(sticker, "is_video", False):
        return "video"
    if getattr(sticker, "is_animated", False):
        return "animated"
    return "static"

def _pack_identity(user, bot_username: str, bot_first_name: str, sticker_format: str) -> tuple[str, str, str]:
    pack_base = _pick_user_pack_base(user)
    if sticker_format == "animated":
        name_prefix = f"{pack_base}_anim"
    elif sticker_format == "video":
        name_prefix = f"{pack_base}_vid"
    else:
        name_prefix = pack_base
    name_suffix = f"_by_{bot_username}"
    pack_title_name = user.first_name or user.username or f"User {user.id}"
    if sticker_format == "animated":
        base_title = f"{pack_title_name} animated by {bot_first_name}"
    elif sticker_format == "video":
        base_title = f"{pack_title_name} video by {bot_first_name}"
    else:
        base_title = f"{pack_title_name} by {bot_first_name}"
    return name_prefix, name_suffix, base_title[:64]

def _make_pack_name(name_prefix: str, name_suffix: str, version: int) -> str:
    middle = "" if version <= 1 else f"_v{version}"
    max_prefix_len = 64 - len(name_suffix) - len(middle)
    if max_prefix_len <= 0:
        raise RuntimeError("Bot username is too long for Telegram sticker pack naming")
    trimmed_prefix = name_prefix[:max_prefix_len]
    return f"{trimmed_prefix}{middle}{name_suffix}"

def _make_pack_title(base_title: str, version: int) -> str:
    if version <= 1:
        return base_title[:64]
    suffix = f" v{version}"
    return (base_title[:64 - len(suffix)] + suffix)[:64]

async def _find_or_create_target_pack(bot, user_id: int, name_prefix: str, name_suffix: str, base_title: str, input_sticker: InputSticker, max_stickers: int = MAX_STICKERS_PER_PACK, max_versions: int = 999):
    for version in range(1, max_versions + 1):
        pack_name = _make_pack_name(name_prefix, name_suffix, version)
        pack_title = _make_pack_title(base_title, version)
        try:
            sticker_set = await bot.get_sticker_set(pack_name)
        except Exception:
            await bot.create_new_sticker_set(user_id=user_id, name=pack_name, title=pack_title, stickers=[input_sticker])
            return pack_name, True
        stickers = getattr(sticker_set, "stickers", None) or []
        if len(stickers) < max_stickers:
            return pack_name, False
    raise RuntimeError("All sticker pack versions are full, cannot add more stickers")

async def _download_file_bytes(bot, file_id: str) -> bytes:
    tg_file = await bot.get_file(file_id)
    data = await tg_file.download_as_bytearray()
    return bytes(data)

def _image_to_static_sticker(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size
    if w <= 0 or h <= 0:
        raise RuntimeError("Invalid image")
    scale = min(512 / w, 512 / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    x = (512 - new_w) // 2
    y = (512 - new_h) // 2
    canvas.alpha_composite(resized, (x, y))
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    canvas.save(tmp.name, "PNG", optimize=True)
    return tmp.name

async def _build_input_sticker_from_reply(reply, bot, emoji: str):
    if reply.sticker:
        sticker = reply.sticker
        if getattr(sticker, "type", None) and str(sticker.type).lower().endswith("custom_emoji"):
            raise RuntimeError("Custom emoji stickers are not supported for /kang yet")
        sticker_format = _sticker_format_from_obj(sticker)
        if sticker_format in ("animated", "video"):
            return InputSticker(sticker=sticker.file_id, emoji_list=[emoji], format=sticker_format), sticker_format, None
        sticker_bytes = await _download_file_bytes(bot, sticker.file_id)
        temp_path = _image_to_static_sticker(sticker_bytes)
        return InputSticker(sticker=open(temp_path, "rb"), emoji_list=[emoji], format="static"), "static", temp_path
    if reply.photo:
        photo = reply.photo[-1]
        photo_bytes = await _download_file_bytes(bot, photo.file_id)
        temp_path = _image_to_static_sticker(photo_bytes)
        return InputSticker(sticker=open(temp_path, "rb"), emoji_list=[emoji], format="static"), "static", temp_path
    if reply.document:
        mime = (getattr(reply.document, "mime_type", "") or "").lower()
        file_name = (getattr(reply.document, "file_name", "") or "").lower()
        is_image_doc = mime.startswith("image/") or file_name.endswith((".png", ".jpg", ".jpeg", ".webp"))
        if not is_image_doc:
            raise RuntimeError("The document must be an image")
        doc_bytes = await _download_file_bytes(bot, reply.document.file_id)
        temp_path = _image_to_static_sticker(doc_bytes)
        return InputSticker(sticker=open(temp_path, "rb"), emoji_list=[emoji], format="static"), "static", temp_path
    raise RuntimeError("Reply to a sticker, photo, or image document")

async def kang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return
    reply = msg.reply_to_message
    if not reply:
        return await msg.reply_text("Reply to a sticker, photo, or image document you want to kang.")
    wait = await msg.reply_text("Stealing sticker...")
    temp_path = None
    opened_file = None
    try:
        me = await context.bot.get_me()
        bot_username = (me.username or "bot").lower()
        bot_first_name = me.first_name or "Bot"
        emoji = _pick_emoji(context.args or [])
        input_sticker, sticker_format, temp_path = await _build_input_sticker_from_reply(reply, context.bot, emoji)
        if hasattr(input_sticker.sticker, "read"):
            opened_file = input_sticker.sticker
        name_prefix, name_suffix, base_title = _pack_identity(user, bot_username, bot_first_name, sticker_format)
        pack_name, created = await _find_or_create_target_pack(
            bot=context.bot,
            user_id=user.id,
            name_prefix=name_prefix,
            name_suffix=name_suffix,
            base_title=base_title,
            input_sticker=input_sticker,
        )
        if not created:
            try:
                await context.bot.add_sticker_to_set(user_id=user.id, name=pack_name, sticker=input_sticker)
            except Exception as e:
                if "Stickers_too_much" in str(e):
                    pack_name, created = await _find_or_create_target_pack(
                        bot=context.bot,
                        user_id=user.id,
                        name_prefix=name_prefix,
                        name_suffix=name_suffix,
                        base_title=base_title,
                        input_sticker=input_sticker,
                    )
                    if not created:
                        await context.bot.add_sticker_to_set(user_id=user.id, name=pack_name, sticker=input_sticker)
                else:
                    raise
        pack_url = f"https://t.me/addstickers/{pack_name}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Sticker Pack", url=pack_url)]])
        await wait.edit_text("Sticker added successfully", reply_markup=keyboard)
    except Exception as e:
        await wait.edit_text(f"Failed to kang sticker: {e}")
    finally:
        try:
            if opened_file:
                opened_file.close()
        except Exception:
            pass
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass