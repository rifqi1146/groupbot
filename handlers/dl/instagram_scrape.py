import os
import re
import html
import uuid
import hashlib
import asyncio
import aiohttp
import aiofiles
from urllib.parse import urlparse, parse_qs, unquote

from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

from handlers.join import require_join_or_block
from utils.http import get_http_session
from .constants import TMP_DIR
from .instagram_api import is_instagram_url

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"


def _build_caption(source: str, count: int) -> str:
    label = "Instagram Media" if count > 1 else "Instagram Post"
    return (
        f"<blockquote expandable>{html.escape(label)}</blockquote>\n\n"
        f"🪄 <i>Source: {html.escape(source)}</i>"
    )


def _uniq_media_urls(items: list[str]) -> list[str]:
    out = []
    seen = set()

    for item in items:
        raw = (item or "").strip()
        if not raw:
            continue

        try:
            parsed = urlparse(raw)
            key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        except Exception:
            key = raw

        if key in seen:
            continue

        seen.add(key)
        out.append(raw)

    return out


def _decode_indown_fetch(link: str) -> str:
    try:
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        raw = (qs.get("url") or [""])[0]
        raw = unquote(raw or "").strip()
        return raw or link
    except Exception:
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

    async with session.get(
        "https://indown.io/en1",
        headers={"User-Agent": USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=25),
    ) as resp:
        page_data = await resp.text()

    token_match = re.search(r'''name=["']_token["'][^>]*value=["']([^"']+)["']''', page_data, flags=re.I)
    token = token_match.group(1).strip() if token_match else ""
    if not token:
        return {"status": False, "message": "Token Indown not found"}

    form = {
        "referer": "https://indown.io/en1",
        "locale": "en",
        "_token": token,
        "link": url,
        "p": "i",
    }

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

    return {
        "status": True,
        "source": "Indown",
        "urls": urls,
    }


async def _snapsave(url: str) -> dict:
    session = await get_http_session()

    form = {
        "url": url,
    }

    async with session.post(
        "https://snapsave.app/id/action.php?lang=id",
        data=form,
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

    return {
        "status": True,
        "source": "Snapsave",
        "urls": urls,
    }


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


async def _download_remote_media(url: str, source: str = "") -> dict:
    session = await get_http_session()

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    lower_url = (url or "").lower()
    source = (source or "").lower()

    if "rapidcdn.app" in lower_url or source == "snapsave":
        headers["Referer"] = "https://snapsave.app/"
        headers["Origin"] = "https://snapsave.app"
    elif "cdninstagram.com" in lower_url or "fbcdn.net" in lower_url or source == "indown":
        headers["Referer"] = "https://www.instagram.com/"
        headers["Origin"] = "https://www.instagram.com"

    last_error = None

    for attempt in range(3):
        try:
            async with session.get(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Failed to download media: HTTP {resp.status}")

                content_type = resp.headers.get("Content-Type", "")
                media_type = _guess_media_type_from_url(str(resp.url))
                if media_type != "video":
                    if content_type.lower().startswith("video/"):
                        media_type = "video"
                    else:
                        media_type = "photo"

                ext = _guess_ext(str(resp.url), content_type)
                out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}{ext}")

                async with aiofiles.open(out_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        await f.write(chunk)

            return {
                "path": out_path,
                "type": media_type,
            }
        except Exception as e:
            last_error = e
            if attempt < 2:
                await asyncio.sleep(1.2 * (attempt + 1))
            continue

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
        except Exception:
            unique.append(item)
            continue

        if sig in seen_hashes:
            try:
                os.remove(path)
            except Exception:
                pass
            continue

        seen_hashes.add(sig)
        unique.append(item)

    return unique


async def _send_ig_result(bot, chat_id: int, reply_to: int, items: list[dict], source: str):
    caption = _build_caption(source, len(items))
    album_chunk_size = 10
    album_cooldown = 3

    if len(items) == 1:
        item = items[0]

        while True:
            try:
                with open(item["path"], "rb") as f:
                    if item["type"] == "video":
                        await bot.send_video(
                            chat_id=chat_id,
                            video=f,
                            caption=caption,
                            parse_mode="HTML",
                            reply_to_message_id=reply_to,
                            supports_streaming=True,
                        )
                    else:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=f,
                            caption=caption,
                            parse_mode="HTML",
                            reply_to_message_id=reply_to,
                        )
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
                    media.append(
                        InputMediaVideo(
                            media=fh,
                            caption=item_caption,
                            parse_mode=item_parse_mode,
                            supports_streaming=True,
                        )
                    )
                else:
                    media.append(
                        InputMediaPhoto(
                            media=fh,
                            caption=item_caption,
                            parse_mode=item_parse_mode,
                        )
                    )

            while True:
                try:
                    await bot.send_media_group(
                        chat_id=chat_id,
                        media=media,
                        reply_to_message_id=reply_to if idx == 0 else None,
                    )
                    break
                except RetryAfter as e:
                    wait_time = int(getattr(e, "retry_after", album_cooldown)) + 1
                    await asyncio.sleep(wait_time)

            if idx < len(chunks) - 1:
                await asyncio.sleep(album_cooldown)

        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass


async def ig_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return

    msg = update.effective_message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "Send an Instagram link.\n\n<code>/ig https://www.instagram.com/p/...</code>",
            parse_mode="HTML",
        )

    url = (context.args[0] or "").strip()
    if not is_instagram_url(url):
        return await msg.reply_text("Invalid Instagram link.")

    status = await msg.reply_text(
        "<b>Fetching Instagram media...</b>",
        parse_mode="HTML",
        reply_to_message_id=msg.message_id,
    )

    downloaded = []
    try:
        result = await igdl_scrape(url)
        urls = result.get("urls") or []
        source = result.get("source") or "Instagram Scraper"

        if not urls:
            raise RuntimeError("No downloadable media found")

        try:
            await status.edit_text(
                "<b>Downloading Instagram media...</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass

        failed_count = 0

        for media_url in urls:
            try:
                downloaded.append(await _download_remote_media(media_url, source=source))
            except Exception as e:
                failed_count += 1
                print("[IG SCRAPER DOWNLOAD ERROR]", media_url, repr(e))
                continue

        if not downloaded:
            raise RuntimeError("All media downloads failed")

        downloaded = _dedupe_downloaded_items(downloaded)

        if not downloaded:
            raise RuntimeError("All media downloads were duplicates or invalid")

        if failed_count:
            try:
                await status.edit_text(
                    (
                        "<b>Uploading Instagram media...</b>\n\n"
                        f"<i>Downloaded {len(downloaded)} item(s), skipped {failed_count} item(s).</i>"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            try:
                await status.edit_text(
                    "<b>Uploading Instagram media...</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await _send_ig_result(
            bot=context.bot,
            chat_id=msg.chat_id,
            reply_to=msg.message_id,
            items=downloaded,
            source=source,
        )

        try:
            await status.delete()
        except Exception:
            pass

    except Exception as e:
        await status.edit_text(
            f"<b>Failed to download Instagram media</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )
    finally:
        for item in downloaded:
            try:
                if item.get("path") and os.path.exists(item["path"]):
                    os.remove(item["path"])
            except Exception:
                pass