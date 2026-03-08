import io
import os
import tempfile
import asyncio
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
from telegram import Update
from telegram.ext import ContextTypes


FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]

FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def _pick_font(paths: list[str], size: int):
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    if not text:
        return 0, 0
    box = draw.multiline_textbbox((0, 0), text, font=font, spacing=8)
    return box[2] - box[0], box[3] - box[1]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> str:
    raw = (text or "").replace("\r", "").strip()
    if not raw:
        return ""

    paragraphs = raw.split("\n")
    out_lines = []

    for para in paragraphs:
        words = para.split()
        if not words:
            if len(out_lines) < max_lines:
                out_lines.append("")
            continue

        current = words[0]

        for word in words[1:]:
            trial = f"{current} {word}"
            w, _ = _measure_text(draw, trial, font)
            if w <= max_width:
                current = trial
            else:
                out_lines.append(current)
                current = word
                if len(out_lines) >= max_lines:
                    break

        if len(out_lines) < max_lines:
            out_lines.append(current)

        if len(out_lines) >= max_lines:
            break

    wrapped = "\n".join(out_lines[:max_lines]).strip()

    original_joined = " ".join(raw.split())
    current_joined = " ".join(wrapped.split())

    if current_joined != original_joined:
        while True:
            candidate = wrapped.rstrip()
            if len(candidate) <= 3:
                wrapped = "..."
                break
            if candidate.endswith("..."):
                break
            candidate = candidate[:-1].rstrip() + "..."
            w, _ = _measure_text(draw, candidate, font)
            if w <= max_width * max_lines:
                wrapped = candidate
                break

    return wrapped


def _load_avatar(avatar_bytes: Optional[bytes], size: int) -> Optional[Image.Image]:
    if not avatar_bytes:
        return None
    try:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        avatar = ImageOps.fit(avatar, (size, size), method=Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, size, size), fill=255)
        avatar.putalpha(mask)
        return avatar
    except Exception:
        return None


def _make_fallback_avatar(name: str, size: int) -> Image.Image:
    avatar = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(avatar)
    draw.ellipse((0, 0, size, size), fill=(83, 60, 137, 255))

    initials = (name or "U").strip()[:1].upper()
    font = _pick_font(FONT_BOLD_CANDIDATES, int(size * 0.45))
    box = draw.textbbox((0, 0), initials, font=font)
    tw = box[2] - box[0]
    th = box[3] - box[1]
    draw.text(
        ((size - tw) / 2, (size - th) / 2 - 4),
        initials,
        font=font,
        fill=(255, 255, 255, 255),
    )
    return avatar


def _rounded_gradient(size: tuple[int, int], radius: int) -> Image.Image:
    w, h = size
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = base.load()

    c1 = (58, 40, 92, 245)
    c2 = (37, 29, 56, 245)

    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        a = int(c1[3] * (1 - t) + c2[3] * t)
        for x in range(w):
            px[x, y] = (r, g, b, a)

    mask = Image.new("L", (w, h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
    base.putalpha(mask)
    return base


def _render_quote_webp(author_name: str, text: str, avatar_bytes: Optional[bytes]) -> str:
    max_canvas_w = 512
    max_canvas_h = 512

    avatar_size = 82
    bubble_pad_x = 26
    bubble_pad_y = 22
    overlap = 30
    max_text_width = 320

    font_name = _pick_font(FONT_BOLD_CANDIDATES, 28)
    font_text = _pick_font(FONT_REGULAR_CANDIDATES, 30)

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))

    wrapped_text = _wrap_text(probe, text, font_text, max_text_width, 8)
    if not wrapped_text:
        wrapped_text = "..."

    name_w, name_h = _measure_text(probe, author_name, font_name)
    text_w, text_h = _measure_text(probe, wrapped_text, font_text)

    bubble_w = max(name_w, text_w) + bubble_pad_x * 2
    bubble_h = bubble_pad_y * 2 + name_h + 10 + text_h

    bubble_w = min(bubble_w, max_canvas_w - 40 - avatar_size // 2)
    bubble_h = min(bubble_h, max_canvas_h - 40)

    bubble_x = avatar_size - overlap + 12
    bubble_y = 20

    canvas_w = min(max_canvas_w, bubble_x + bubble_w + 20)
    canvas_h = min(max_canvas_h, bubble_y + bubble_h + 20)

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (bubble_w + 20, bubble_h + 20), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((10, 10, bubble_w + 10, bubble_h + 10), radius=32, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas.alpha_composite(shadow, (bubble_x - 10, bubble_y - 2))

    bubble = _rounded_gradient((bubble_w, bubble_h), 30)
    canvas.alpha_composite(bubble, (bubble_x, bubble_y))

    avatar = _load_avatar(avatar_bytes, avatar_size)
    if avatar is None:
        avatar = _make_fallback_avatar(author_name, avatar_size)

    avatar_y = bubble_y + 16
    avatar_x = 8
    canvas.alpha_composite(avatar, (avatar_x, avatar_y))

    draw = ImageDraw.Draw(canvas)

    text_x = bubble_x + bubble_pad_x
    name_y = bubble_y + bubble_pad_y - 2
    body_y = name_y + name_h + 10

    draw.text(
        (text_x, name_y),
        author_name,
        font=font_name,
        fill=(205, 151, 255, 255),
    )

    draw.multiline_text(
        (text_x, body_y),
        wrapped_text,
        font=font_text,
        fill=(255, 255, 255, 255),
        spacing=8,
    )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".webp")
    tmp.close()
    canvas.save(tmp.name, "WEBP", lossless=True, quality=100, method=6)
    return tmp.name


async def _download_avatar_bytes(bot, user_id: int) -> Optional[bytes]:
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if not photos.photos:
            return None
        file_id = photos.photos[0][-1].file_id
        tg_file = await bot.get_file(file_id)
        data = await tg_file.download_as_bytearray()
        return bytes(data) if data else None
    except Exception:
        return None


async def q_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    target = msg.reply_to_message
    if not target:
        return await msg.reply_text("Reply ke pesan yang mau dijadiin sticker.")

    source_user = target.from_user
    if not source_user:
        return await msg.reply_text("User tidak ditemukan.")

    text = (target.text or target.caption or "").strip()
    if not text:
        return await msg.reply_text("Pesan itu nggak punya teks.")

    if len(text) > 400:
        text = text[:400].rstrip() + "..."

    author_name = source_user.username or source_user.full_name or source_user.first_name or "User"

    wait = await msg.reply_text("Bentar, lagi bikin sticker...")

    avatar_bytes = await _download_avatar_bytes(context.bot, source_user.id)

    try:
        sticker_path = await asyncio.to_thread(
            _render_quote_webp,
            author_name,
            text,
            avatar_bytes,
        )

        with open(sticker_path, "rb") as f:
            await context.bot.send_sticker(
                chat_id=msg.chat_id,
                sticker=f,
                reply_to_message_id=target.message_id,
            )
    except Exception as e:
        await wait.edit_text(f"Gagal bikin sticker: {e}")
        return
    finally:
        try:
            if "sticker_path" in locals() and sticker_path and os.path.exists(sticker_path):
                os.remove(sticker_path)
        except Exception:
            pass

    try:
        await wait.delete()
    except Exception:
        pass