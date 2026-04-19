import os
import re
import html
import uuid
import hashlib
import logging
import asyncio
import aiohttp
import aiofiles
from urllib.parse import urlparse, parse_qs, unquote
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.error import RetryAfter
from telegram.ext import ContextTypes
from handlers.join import require_join_or_block
from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)

class RetryableDownloadError(RuntimeError):
    pass

def is_instagram_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
        return host == "instagram.com" or host.endswith(".instagram.com") or host == "instagr.am"
    except Exception as e:
        text = (url or "").lower()
        log.warning("Failed to parse Instagram URL host | url=%s err=%s", url, e)
        return "instagram.com" in text or "instagr.am" in text

def _ensure_tmp_dir():
    os.makedirs(TMP_DIR, exist_ok=True)

def _truncate_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return "." * limit
    return text[:limit - 3].rstrip() + "..."

def _build_caption(source: str, count: int, bot_name: str, max_len: int = 1024) -> str:
    clean_title = "Instagram Media" if count > 1 else "Instagram Post"
    clean_bot = (bot_name or "Bot").strip() or "Bot"
    title = _truncate_text(clean_title, max_len)
    return f"<blockquote expandable>📸 {html.escape(title)}</blockquote>\n\n🪄 <i>Powered by {html.escape(clean_bot)}</i>"

def _uniq_media_urls(items: list[str]) -> list[str]:
    out = []
    seen = set()
    cdn_hosts_strip_query = ("cdninstagram.com", "fbcdn.net", "d.rapidcdn.app")
    for item in items:
        raw = (item or "").strip()
        if not raw:
            continue
        try:
            parsed = urlparse(raw)
            host = (parsed.hostname or "").lower()
            path = parsed.path or ""
            if any(host == h or host.endswith("." + h) for h in cdn_hosts_strip_query):
                normalized = f"{parsed.scheme}://{host}{path}"
            else:
                normalized = parsed._replace(fragment="").geturl()
        except Exception as e:
            log.warning("Failed to normalize media URL | url=%s err=%s", raw, e)
            normalized = raw
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(raw)
    return out

def _decode_indown_fetch(link: str) -> str:
    try:
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        raw = (qs.get("url") or [""])[0]
        raw = unquote(raw or "").strip()
        return raw or link
    except Exception as e:
        log.warning("Failed to decode Indown fetch URL | url=%s err=%s", link, e)
        return link

def _collect_urls_from_html(text: str) -> list[str]:
    found = []
    for match in re.findall(r'''(?:src|href)=["']([^"']+)["']''', text, flags=re.I):
        link = (match or "").strip()
        if not link:
            continue
        if "indown.io/fetch" in link:
            link = _decode_indown_fetch(link)
        link = link.replace("&amp;", "&")
        if re.search(r"(cdninstagram\.com|fbcdn\.net|d\.rapidcdn\.app)", link, flags=re.I):
            found.append(link)
    for match in re.findall(r'''https://[^"'\s<>]+''', text, flags=re.I):
        link = (match or "").strip().replace("&amp;", "&")
        if re.search(r"(cdninstagram\.com|fbcdn\.net|d\.rapidcdn\.app)", link, flags=re.I):
            found.append(link)
    cleaned = []
    for link in _uniq_media_urls(found):
        cleaned.append(re.sub(r"&dl=1$", "", link))
    return cleaned

async def _indown(url: str) -> dict:
    session = await get_http_session()
    async with session.get("https://indown.io/en1", headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=25)) as resp:
        page_data = await resp.text()
    token_match = re.search(r'''name=["']_token["'][^>]*value=["']([^"']+)["']''', page_data, flags=re.I)
    token = token_match.group(1).strip() if token_match else ""
    if not token:
        return {"status": False, "message": "Token Indown not found"}
    form = {"referer": "https://indown.io/en1", "locale": "en", "_token": token, "link": url, "p": "i"}
    async with session.post(
        "https://indown.io/download",
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
            "Referer": "https://indown.io/en1",
            "Origin": "https://indown.io",
        },
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        result_data = await resp.text()
    urls = _collect_urls_from_html(result_data)
    if not urls:
        return {"status": False, "message": "No media found"}
    return {"status": True, "source": "Indown", "urls": urls}

async def _snapsave(url: str) -> dict:
    session = await get_http_session()
    async with session.post(
        "https://snapsave.app/id/action.php?lang=id",
        data={"url": url},
        headers={
            "Origin": "https://snapsave.app",
            "Referer": "https://snapsave.app/id/download-video-instagram",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        data = await resp.text()
    urls = _collect_urls_from_html(data)
    if not urls:
        rapid = re.findall(r'''https://d\.rapidcdn\.app/v2\?[^"'<> ]+''', data, flags=re.I)
        urls = _uniq_media_urls([x.replace("&amp;", "&") for x in rapid])
    if not urls:
        return {"status": False, "message": "No media found"}
    return {"status": True, "source": "Snapsave", "urls": urls}

async def igdl_scrape(url: str) -> dict:
    result = await _indown(url)
    if result.get("status") and result.get("urls"):
        return result
    result = await _snapsave(url)
    if result.get("status") and result.get("urls"):
        return result
    raise RuntimeError(result.get("message") or "No media found")

def _guess_media_type_from_url(url: str) -> str:
    path = (urlparse(url).path or "").lower()
    if path.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return "video"
    return "photo"

def _guess_ext(url: str, content_type: str) -> str:
    path = (urlparse(url).path or "").lower()
    for ext in (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext):
            return ext
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype.startswith("video/"):
        return ".mp4"
    if ctype == "image/png":
        return ".png"
    if ctype == "image/webp":
        return ".webp"
    return ".jpg"

def _is_valid_media_content_type(content_type: str) -> bool:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if not ctype:
        return False
    if ctype.startswith("image/") or ctype.startswith("video/"):
        return True
    if ctype == "application/octet-stream":
        return True
    return False

def _is_retryable_download_exception(exc: Exception) -> bool:
    if isinstance(exc, RetryableDownloadError):
        return True
    if isinstance(exc, (aiohttp.ClientError, asyncio.TimeoutError)):
        return True
    return False

async def _safe_edit_message(bot, chat_id: int, message_id: int, text: str):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML")
    except Exception as e:
        log.warning("Failed to edit Instagram status message | chat_id=%s message_id=%s err=%s", chat_id, message_id, e)

async def _safe_edit_status_message(status, text: str):
    try:
        await status.edit_text(text, parse_mode="HTML")
    except Exception as e:
        log.warning("Failed to edit status message | chat_id=%s message_id=%s err=%s", getattr(status, "chat_id", None), getattr(status, "message_id", None), e)

async def _safe_delete_message(message):
    try:
        await message.delete()
    except Exception as e:
        log.warning("Failed to delete message | chat_id=%s message_id=%s err=%s", getattr(message, "chat_id", None), getattr(message, "message_id", None), e)

def _safe_remove_file(path: str, context: str = ""):
    if not path or not os.path.exists(path):
        return
    try:
        os.remove(path)
    except Exception as e:
        log.warning("Failed to remove file | path=%s context=%s err=%s", path, context, e)

def _safe_close_handle(fh, context: str = ""):
    try:
        fh.close()
    except Exception as e:
        log.warning("Failed to close file handle | context=%s err=%s", context, e)

async def _download_remote_media(url: str, source: str = "") -> dict:
    _ensure_tmp_dir()
    session = await get_http_session()
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    lower_url = (url or "").lower()
    source_lower = (source or "").lower()
    if "rapidcdn.app" in lower_url or source_lower == "snapsave":
        headers["Referer"] = "https://snapsave.app/"
        headers["Origin"] = "https://snapsave.app"
    elif "cdninstagram.com" in lower_url or "fbcdn.net" in lower_url or source_lower == "indown":
        headers["Referer"] = "https://www.instagram.com/"
        headers["Origin"] = "https://www.instagram.com"
    last_error = None
    for attempt in range(3):
        out_path = None
        try:
            async with session.get(url, headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                if resp.status in (408, 429, 500, 502, 503, 504):
                    raise RetryableDownloadError(f"Temporary download failure: HTTP {resp.status}")
                if resp.status >= 400:
                    raise RuntimeError(f"Failed to download media: HTTP {resp.status}")
                content_type = resp.headers.get("Content-Type", "")
                if not _is_valid_media_content_type(content_type):
                    preview = ""
                    try:
                        preview = await resp.text()
                        preview = _truncate_text(preview.replace("\n", " ").strip(), 120)
                    except Exception as preview_err:
                        log.warning("Failed to read invalid media response preview | url=%s err=%s", url, preview_err)
                        preview = ""
                    msg = f"Invalid media response: {content_type or 'unknown content-type'}"
                    if preview:
                        msg += f" ({preview})"
                    raise RuntimeError(msg)
                final_url = str(resp.url)
                media_type = _guess_media_type_from_url(final_url)
                if media_type != "video" and content_type.lower().startswith("video/"):
                    media_type = "video"
                ext = _guess_ext(final_url, content_type)
                out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}{ext}")
                total_written = 0
                async with aiofiles.open(out_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        if not chunk:
                            continue
                        total_written += len(chunk)
                        await f.write(chunk)
                if total_written <= 0:
                    raise RuntimeError("Downloaded media is empty")
                return {"path": out_path, "type": media_type}
        except Exception as e:
            last_error = e
            if out_path and os.path.exists(out_path):
                _safe_remove_file(out_path, context="download_remote_media_cleanup")
            if attempt < 2 and _is_retryable_download_exception(e):
                log.warning("Retryable Instagram media download error | url=%s source=%s attempt=%s err=%r", url, source, attempt + 1, e)
                await asyncio.sleep(1.2 * (attempt + 1))
                continue
            break
    raise last_error or RuntimeError("Failed to download media")

def _file_sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def _dedupe_downloaded_items(items: list[dict]) -> list[dict]:
    unique = []
    seen_hashes = set()
    for item in items:
        path = item.get("path")
        if not path or not os.path.exists(path):
            continue
        try:
            sig = _file_sha1(path)
        except Exception as e:
            log.warning("Failed to hash downloaded Instagram media | path=%s err=%s", path, e)
            unique.append(item)
            continue
        if sig in seen_hashes:
            _safe_remove_file(path, context="dedupe_downloaded_items")
            continue
        seen_hashes.add(sig)
        unique.append(item)
    return unique

async def _collect_instagram_downloads(url: str) -> dict:
    result = await igdl_scrape(url)
    urls = _uniq_media_urls(result.get("urls") or [])
    source = result.get("source") or "Instagram Scraper"
    if not urls:
        raise RuntimeError("No downloadable media found")
    downloaded = []
    failed_count = 0
    last_error = None
    for media_url in urls:
        try:
            downloaded.append(await _download_remote_media(media_url, source=source))
        except Exception as e:
            failed_count += 1
            last_error = e
            log.warning("Instagram media download failed: %s | %r", media_url, e)
            continue
    if not downloaded:
        if last_error:
            raise RuntimeError(f"All media downloads failed: {last_error}")
        raise RuntimeError("All media downloads failed")
    downloaded = _dedupe_downloaded_items(downloaded)
    if not downloaded:
        raise RuntimeError("All media downloads were duplicates or invalid")
    return {"items": downloaded, "source": source, "failed_count": failed_count}

async def igdl_download_for_fallback(bot, chat_id: int, reply_to: int, status_msg_id: int, url: str) -> dict:
    await _safe_edit_message(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>Downloading Instagram media...</b>")
    collected = await _collect_instagram_downloads(url)
    downloaded = collected["items"]
    source = collected["source"]
    if len(downloaded) == 1:
        item = downloaded[0]
        title = "Instagram Post" if item["type"] == "photo" else "Instagram Video"
        return {"path": item["path"], "title": title}
    return {"items": downloaded, "title": "Instagram Media", "source": source}

async def send_instagram_fallback_result(bot, chat_id: int, reply_to: int, result: dict):
    if result.get("items"):
        await _send_ig_result(bot=bot, chat_id=chat_id, reply_to=reply_to, items=result["items"], source=result.get("source") or "Instagram")
        return
    path = result.get("path")
    if not path or not os.path.exists(path):
        raise RuntimeError("Fallback result path not found")
    bot_name = (await bot.get_me()).first_name or "Bot"
    caption = _build_caption("Instagram", 1, bot_name)
    with open(path, "rb") as f:
        if path.lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
            await bot.send_video(chat_id=chat_id, video=f, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to, supports_streaming=True)
        else:
            await bot.send_photo(chat_id=chat_id, photo=f, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to)

async def cleanup_instagram_fallback_result(result: dict):
    if not isinstance(result, dict):
        return
    path = result.get("path")
    if path and os.path.exists(path):
        _safe_remove_file(path, context="cleanup_instagram_fallback_result_single")
    for item in result.get("items") or []:
        try:
            p = item.get("path")
            if p and os.path.exists(p):
                _safe_remove_file(p, context="cleanup_instagram_fallback_result_items")
        except Exception as e:
            log.warning("Failed while cleaning Instagram fallback item | err=%s", e)

async def _send_ig_result(bot, chat_id: int, reply_to: int, items: list[dict], source: str):
    if not items:
        raise RuntimeError("No media items to send")
    bot_name = (await bot.get_me()).first_name or "Bot"
    caption = _build_caption(source, len(items), bot_name)
    album_chunk_size = 10
    album_cooldown = 3
    if len(items) == 1:
        item = items[0]
        while True:
            try:
                with open(item["path"], "rb") as f:
                    if item["type"] == "video":
                        await bot.send_video(chat_id=chat_id, video=f, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to, supports_streaming=True)
                    else:
                        await bot.send_photo(chat_id=chat_id, photo=f, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to)
                break
            except RetryAfter as e:
                wait_time = int(getattr(e, "retry_after", album_cooldown)) + 1
                await asyncio.sleep(wait_time)
        return
    chunks = [items[i:i + album_chunk_size] for i in range(0, len(items), album_chunk_size)]
    for idx, chunk in enumerate(chunks):
        media = []
        handles = []
        try:
            for i, item in enumerate(chunk):
                fh = open(item["path"], "rb")
                handles.append(fh)
                is_first = idx == 0 and i == 0
                item_caption = caption if is_first else None
                item_parse_mode = "HTML" if is_first else None
                if item["type"] == "video":
                    media.append(InputMediaVideo(media=fh, caption=item_caption, parse_mode=item_parse_mode, supports_streaming=True))
                else:
                    media.append(InputMediaPhoto(media=fh, caption=item_caption, parse_mode=item_parse_mode))
            while True:
                try:
                    await bot.send_media_group(chat_id=chat_id, media=media, reply_to_message_id=reply_to if idx == 0 else None)
                    break
                except RetryAfter as e:
                    wait_time = int(getattr(e, "retry_after", album_cooldown)) + 1
                    await asyncio.sleep(wait_time)
            if idx < len(chunks) - 1:
                await asyncio.sleep(album_cooldown)
        finally:
            for fh in handles:
                _safe_close_handle(fh, context="_send_ig_result")

async def ig_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return
    msg = update.effective_message
    if not msg:
        return
    if not context.args:
        return await msg.reply_text("Send an Instagram link.\n\n<code>/ig https://www.instagram.com/p/...</code>", parse_mode="HTML")
    url = (context.args[0] or "").strip()
    if not is_instagram_url(url):
        return await msg.reply_text("Invalid Instagram link.")
    status = await msg.reply_text("<b>Fetching Instagram media...</b>", parse_mode="HTML", reply_to_message_id=msg.message_id)
    downloaded = []
    try:
        await _safe_edit_status_message(status, "<b>Downloading Instagram media...</b>")
        collected = await _collect_instagram_downloads(url)
        downloaded = collected["items"]
        source = collected["source"]
        failed_count = collected["failed_count"]
        if failed_count:
            await _safe_edit_status_message(status, f"<b>Uploading Instagram media...</b>\n\n<i>Downloaded {len(downloaded)} item(s), skipped {failed_count} item(s).</i>")
        else:
            await _safe_edit_status_message(status, "<b>Uploading Instagram media...</b>")
        await _send_ig_result(bot=context.bot, chat_id=msg.chat_id, reply_to=msg.message_id, items=downloaded, source=source)
        await _safe_delete_message(status)
    except Exception as e:
        await status.edit_text(f"<b>Failed to download Instagram media</b>\n\n<code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        for item in downloaded:
            try:
                path = item.get("path")
                if path and os.path.exists(path):
                    _safe_remove_file(path, context="ig_cmd_finally")
            except Exception as e:
                log.warning("Failed while cleaning downloaded Instagram item | err=%s", e)
