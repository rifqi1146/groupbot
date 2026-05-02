import os
import re
import html
import uuid
import json
import inspect
import logging
import mimetypes
import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

from handlers.join import require_join_or_block
from utils.http import get_http_session
from utils.config import NEOXR_API_KEY

log = logging.getLogger(__name__)

TMP_DIR = os.getenv("TMP_DIR", "downloads")
NEOXR_WASITAI_API = os.getenv("NEOXR_WASITAI_API", "https://api.neoxr.eu/api/wasitai").strip()
TMPFILES_UPLOAD_API = os.getenv("TMPFILES_UPLOAD_API", "https://tmpfiles.org/api/v1/upload").strip()
AI_IMAGE_DETECTOR_MAX_SIZE = int(os.getenv("AI_IMAGE_DETECTOR_MAX_SIZE", str(10 * 1024 * 1024)))
AI_IMAGE_DETECTOR_TIMEOUT = int(os.getenv("AI_IMAGE_DETECTOR_TIMEOUT", "60"))

async def _shared_http_session():
    session = get_http_session()
    if inspect.isawaitable(session):
        session = await session
    return session

def esc(text) -> str:
    return html.escape(str(text or "-"))

def _safe_name(name: str, default: str = "image.jpg") -> str:
    name = os.path.basename(str(name or "").strip()) or default
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return name[:120] or default

def _is_image_mime(mime: str) -> bool:
    return str(mime or "").lower().startswith("image/")

def _guess_content_type(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    mime = str(mime or "").lower()
    if mime.startswith("image/"):
        return mime
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    return "image/jpeg"

def _guess_ext(mime: str, fallback: str = ".jpg") -> str:
    mime = str(mime or "").lower()
    if "png" in mime:
        return ".png"
    if "webp" in mime:
        return ".webp"
    if "jpeg" in mime or "jpg" in mime:
        return ".jpg"
    return fallback

def _tmpfiles_direct_url(url: str) -> str:
    url = str(url or "").strip()
    if url.startswith("http://tmpfiles.org/"):
        url = "https://" + url[len("http://"):]
    if url.startswith("https://tmpfiles.org/") and "/dl/" not in url:
        return url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/", 1)
    return url

def _usage_text() -> str:
    return (
        "<b>AI Image Detector</b>\n\n"
        "Reply to an image:\n"
        "<code>/aiimagedetector</code>\n\n"
        "Or use image URL:\n"
        "<code>/aiimagedetector https://example.com/image.jpg</code>"
    )

def _is_url(text: str) -> bool:
    text = str(text or "").strip()
    return text.startswith(("http://", "https://"))

async def _download_replied_media(bot, msg) -> tuple[str, str]:
    target = msg.reply_to_message
    if not target:
        raise RuntimeError("NO_REPLY")
    os.makedirs(TMP_DIR, exist_ok=True)
    if target.photo:
        photo = target.photo[-1]
        tg_file = await bot.get_file(photo.file_id)
        filename = f"ai_detector_{uuid.uuid4().hex}.jpg"
    elif target.document:
        doc = target.document
        if not _is_image_mime(doc.mime_type):
            raise RuntimeError("The replied document is not an image.")
        if doc.file_size and doc.file_size > AI_IMAGE_DETECTOR_MAX_SIZE:
            raise RuntimeError(f"Image is too large. Max size is {AI_IMAGE_DETECTOR_MAX_SIZE // 1024 // 1024}MB.")
        tg_file = await bot.get_file(doc.file_id)
        ext = os.path.splitext(doc.file_name or "")[1] or _guess_ext(doc.mime_type)
        filename = f"ai_detector_{uuid.uuid4().hex}{ext}"
    elif target.sticker:
        sticker = target.sticker
        if sticker.is_animated or sticker.is_video:
            raise RuntimeError("Animated/video stickers are not supported. Use a static sticker.")
        tg_file = await bot.get_file(sticker.file_id)
        filename = f"ai_detector_{uuid.uuid4().hex}.webp"
    else:
        raise RuntimeError("NO_REPLY")
    input_path = os.path.join(TMP_DIR, _safe_name(filename))
    await tg_file.download_to_drive(input_path)
    if not os.path.exists(input_path) or os.path.getsize(input_path) <= 0:
        raise RuntimeError("Failed to download image from Telegram.")
    if os.path.getsize(input_path) > AI_IMAGE_DETECTOR_MAX_SIZE:
        raise RuntimeError(f"Image is too large. Max size is {AI_IMAGE_DETECTOR_MAX_SIZE // 1024 // 1024}MB.")
    return input_path, filename

async def _upload_to_tmpfiles(path: str) -> str:
    if not os.path.exists(path):
        raise RuntimeError("Upload file does not exist.")
    if os.path.getsize(path) <= 0:
        raise RuntimeError("Upload file is empty.")
    content_type = _guess_content_type(path)
    filename = _safe_name(os.path.basename(path), "image.jpg")
    session = await _shared_http_session()
    log.info("Tmpfiles upload start | file=%s size=%s content_type=%s", path, os.path.getsize(path), content_type)
    with open(path, "rb") as fh:
        form = aiohttp.FormData()
        form.add_field("file", fh, filename=filename, content_type=content_type)
        async with session.post(TMPFILES_UPLOAD_API, data=form, timeout=aiohttp.ClientTimeout(total=AI_IMAGE_DETECTOR_TIMEOUT)) as resp:
            text = (await resp.text()).strip()
            log.info("Tmpfiles upload response | status=%s body=%s", resp.status, text[:800])
            if resp.status != 200:
                raise RuntimeError(f"Tmpfiles upload failed {resp.status}: {text[:500]}")
            try:
                data = json.loads(text)
            except Exception:
                data = None
    raw_url = ""
    if isinstance(data, dict):
        raw_url = str(((data.get("data") or {}).get("url")) or data.get("url") or "").strip()
    if not raw_url:
        m = re.search(r"https?://tmpfiles\.org/[^\s\"'<>]+", text)
        raw_url = m.group(0).strip() if m else ""
    direct_url = _tmpfiles_direct_url(raw_url)
    if not direct_url.startswith(("http://", "https://")):
        raise RuntimeError(f"Invalid Tmpfiles response: {text[:500] or 'empty response'}")
    log.info("Tmpfiles upload success | url=%s direct=%s", raw_url, direct_url)
    return direct_url

async def _call_wasitai_api(image_url: str) -> dict:
    if not NEOXR_API_KEY:
        raise RuntimeError("NEOXR_API_KEY is not set.")
    session = await _shared_http_session()
    params = {"image": image_url, "apikey": NEOXR_API_KEY}
    async with session.get(NEOXR_WASITAI_API, params=params, timeout=aiohttp.ClientTimeout(total=AI_IMAGE_DETECTOR_TIMEOUT)) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"Neoxr API error {resp.status}: {text[:500]}")
        try:
            data = await resp.json(content_type=None)
        except Exception:
            raise RuntimeError(f"Invalid Neoxr JSON: {text[:500]}")
    if not isinstance(data, dict):
        raise RuntimeError("Invalid Neoxr response.")
    if not data.get("status"):
        raise RuntimeError(data.get("message") or data.get("msg") or "AI image detection failed.")
    result = data.get("data")
    if not isinstance(result, dict):
        raise RuntimeError("Invalid AI image detection result.")
    return result

def _format_result(result: dict) -> str:
    is_ai = str(result.get("is_ai") or "-").strip().upper()
    description = result.get("description") or "-"
    verdict = "AI Generated" if is_ai == "YES" else "Likely Human Made"
    return (
        "<b>AI Image Detector</b>\n\n"
        f"<b>Result:</b> <code>{esc(verdict)}</code>\n"
        f"<b>AI:</b> <code>{esc(is_ai)}</code>\n\n"
        f"📝 <b>Description:</b>\n{esc(description)}"
    )

async def aiimagedetector_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    msg = update.effective_message
    if not msg:
        return
    args = context.args or []
    input_path = None
    status = None
    try:
        image_url = ""
        if args and _is_url(args[0]):
            image_url = args[0].strip()
        else:
            input_path, _ = await _download_replied_media(context.bot, msg)
            image_url = await _upload_to_tmpfiles(input_path)
        status = await msg.reply_text("<b>Analyzing image...</b>", parse_mode="HTML", reply_to_message_id=msg.message_id)
        result = await _call_wasitai_api(image_url)
        await status.edit_text(_format_result(result), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        err_raw = str(e) or repr(e)
        if err_raw == "NO_REPLY":
            text = _usage_text()
        else:
            err = esc(err_raw.strip())[:3500]
            text = f"<b>AI image detection failed</b>\n\n<code>{err}</code>"
        if status:
            try:
                await status.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)
            except Exception as edit_error:
                log.warning("Failed to edit AI detector status | error=%s", edit_error)
                await msg.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await msg.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
    finally:
        if input_path and os.path.exists(input_path):
            try:
                os.remove(input_path)
                log.info("AI detector temp deleted | file=%s", input_path)
            except Exception as e:
                log.warning("Failed to delete AI detector temp | file=%s err=%r", input_path, e)