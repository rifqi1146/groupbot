import os
import re
import time
import uuid
import html
import asyncio
import hashlib
import mimetypes
import aiohttp
import aiofiles
from urllib.parse import urlparse, parse_qs, unquote

from telegram import InputMediaPhoto, InputMediaVideo
from telegram.error import RetryAfter

from utils.http import get_http_session
from .constants import TMP_DIR
from .utils import sanitize_filename, progress_bar

INSTAGRAM_API_URL = "https://api.sonzaix.indevs.in/sosmed/instagram"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"


def is_instagram_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
        return host == "instagram.com" or host.endswith(".instagram.com") or host == "instagr.am"
    except Exception:
        text = (url or "").lower()
        return "instagram.com" in text or "instagr.am" in text


def _truncate_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return "." * limit
    return text[:limit - 3].rstrip() + "..."


def _build_safe_instagram_caption(title: str, desc: str, bot_name: str, max_len: int = 1024) -> str:
    clean_title = (title or "Instagram Media").strip() or "Instagram Media"
    clean_desc = (desc or "").strip()
    clean_bot = (bot_name or "Bot").strip() or "Bot"

    if clean_desc == clean_title:
        clean_desc = ""

    footer_plain = f"🪄 Powered by {clean_bot}"

    def plain_len(t: str, d: str) -> int:
        if d:
            return len(f"📸 {t}\n\n{d}\n\n{footer_plain}")
        return len(f"📸 {t}\n\n{footer_plain}")

    short_title = clean_title
    short_desc = clean_desc

    if short_desc:
        allowed_desc = max_len - len(f"📸 {short_title}\n\n\n\n{footer_plain}")
        short_desc = _truncate_text(short_desc, allowed_desc)

    if plain_len(short_title, short_desc) > max_len:
        if short_desc:
            allowed_title = max_len - len(f"📸 \n\n{short_desc}\n\n{footer_plain}")
        else:
            allowed_title = max_len - len(f"📸 \n\n{footer_plain}")
        short_title = _truncate_text(short_title, allowed_title)

    if short_desc and plain_len(short_title, short_desc) > max_len:
        allowed_desc = max_len - len(f"📸 {short_title}\n\n\n\n{footer_plain}")
        short_desc = _truncate_text(short_desc, allowed_desc)

    if not short_title:
        short_title = "Instagram Media"

    if short_desc:
        return (
            f"<blockquote expandable>📸 {html.escape(short_title)}</blockquote>\n\n"
            f"{html.escape(short_desc)}\n\n"
            f"🪄 <i>Powered by {html.escape(clean_bot)}</i>"
        )

    return (
        f"<blockquote expandable>📸 {html.escape(short_title)}</blockquote>\n\n"
        f"🪄 <i>Powered by {html.escape(clean_bot)}</i>"
    )


def _guess_ext_from_url(url: str) -> str:
    try:
        path = unquote(urlparse(url).path or "")
        ext = os.path.splitext(path)[1].lower()
        if ext in (".mp4", ".mov", ".m4v", ".jpg", ".jpeg", ".png", ".webp", ".webm"):
            return ext
    except Exception:
        pass
    return ""


def _guess_media_type_from_url(url: str) -> str:
    path = (urlparse(url).path or "").lower()
    if path.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return "video"
    return "photo"


def _guess_ext(content_type: str, media_type: str, media_url: str) -> str:
    ext = _guess_ext_from_url(media_url)
    if ext:
        return ext

    ctype = (content_type or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(ctype) or ""
    if guessed:
        return guessed

    if media_type == "video":
        return ".mp4"
    return ".jpg"


def _build_title(data: dict, media_type: str) -> str:
    nickname = (data.get("nickname") or "").strip()
    username = (data.get("username") or "").strip()
    description = (data.get("description") or "").strip()

    if nickname and username:
        base = f"{nickname} (@{username})"
    elif nickname:
        base = nickname
    elif username:
        base = f"@{username}"
    else:
        base = "Instagram Media"

    if description:
        short_desc = description[:80].strip()
        return f"{base} - {short_desc}"

    if media_type == "video":
        return f"{base} - Instagram Video"

    return f"{base} - Instagram Image"


def _extract_media_candidates(data: dict) -> list[tuple[str, str]]:
    out = []

    def add_candidate(kind: str, url: str):
        u = (url or "").strip()
        if not u:
            return
        item = (kind, u)
        if item not in out:
            out.append(item)

    add_candidate("video", data.get("video_url"))
    add_candidate("photo", data.get("image_url"))
    add_candidate("photo", data.get("photo_url"))
    add_candidate("photo", data.get("image"))

    for key in ("images", "image_urls", "photos"):
        items = data.get(key) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    add_candidate("photo", item)
                elif isinstance(item, dict):
                    add_candidate("photo", item.get("url") or item.get("image") or item.get("src"))

    for key in ("videos", "video_urls"):
        items = data.get(key) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    add_candidate("video", item)
                elif isinstance(item, dict):
                    add_candidate("video", item.get("url") or item.get("video") or item.get("src"))

    for key in ("media", "medias", "items", "carousel", "carousel_media"):
        items = data.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, str):
                add_candidate("photo", item)
                continue
            if not isinstance(item, dict):
                continue

            media_type = str(
                item.get("type")
                or item.get("media_type")
                or item.get("kind")
                or ""
            ).lower()

            media_url = (
                item.get("url")
                or item.get("download_url")
                or item.get("media_url")
                or item.get("video_url")
                or item.get("image_url")
                or item.get("src")
            )

            if not media_url:
                continue

            if "video" in media_type or media_type in ("2", "clip", "reel"):
                add_candidate("video", media_url)
            else:
                add_candidate("photo", media_url)

    return out


def _pick_media_for_format(candidates: list[tuple[str, str]], fmt_key: str) -> tuple[str, str] | None:
    if not candidates:
        return None

    if fmt_key == "mp3":
        for kind, url in candidates:
            if kind == "video":
                return kind, url
        return None

    for kind, url in candidates:
        if kind == "video":
            return kind, url

    return candidates[0]


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


async def _instagram_scrape_fallback(url: str) -> dict:
    result = await _indown(url)
    if result.get("status") and result.get("urls"):
        return result

    result = await _snapsave(url)
    if result.get("status") and result.get("urls"):
        return result

    raise RuntimeError(result.get("message") or "No media found")


async def _download_with_progress(
    session,
    media_url: str,
    media_type: str,
    title: str,
    bot,
    chat_id,
    status_msg_id,
    progress_text: str,
    source: str = "",
) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    lower_url = (media_url or "").lower()
    source = (source or "").lower()

    if "rapidcdn.app" in lower_url or source == "snapsave":
        headers["Referer"] = "https://snapsave.app/"
        headers["Origin"] = "https://snapsave.app"
    elif "cdninstagram.com" in lower_url or "fbcdn.net" in lower_url or source == "indown":
        headers["Referer"] = "https://www.instagram.com/"
        headers["Origin"] = "https://www.instagram.com"

    async with session.get(
        media_url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=180),
    ) as media_resp:
        if media_resp.status >= 400:
            raise RuntimeError(f"Failed to download media: HTTP {media_resp.status}")

        total = int(media_resp.headers.get("Content-Length", 0))
        content_type = media_resp.headers.get("Content-Type", "")
        ext = _guess_ext(content_type, media_type, media_url)

        safe_title = sanitize_filename(title)
        out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{safe_title}{ext}")

        downloaded = 0
        last = 0.0

        async with aiofiles.open(out_path, "wb") as f:
            async for chunk in media_resp.content.iter_chunked(64 * 1024):
                await f.write(chunk)
                downloaded += len(chunk)

                if total and time.time() - last >= 1.0:
                    pct = downloaded / total * 100
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=status_msg_id,
                            text=(
                                f"<b>{progress_text}</b>\n\n"
                                f"<code>{progress_bar(pct)}</code>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                    last = time.time()

    return {
        "path": out_path,
        "title": title,
    }


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

                ext = _guess_ext(str(resp.url), content_type, str(resp.url))
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


async def send_instagram_album_result(bot, chat_id: int, reply_to: int, result: dict):
    items = result.get("items") or []
    if not items:
        raise RuntimeError("Instagram album result is empty")

    title = (result.get("title") or "Instagram Media").strip() or "Instagram Media"
    source = (result.get("source") or "").strip()
    desc = f"Source: {source}" if source else ""
    bot_name = (await bot.get_me()).first_name or "Bot"
    caption = _build_safe_instagram_caption(title, desc, bot_name)

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


async def cleanup_instagram_result(result):
    if not isinstance(result, dict):
        return

    path = result.get("path")
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass

    for item in result.get("items") or []:
        try:
            p = item.get("path")
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


async def instagram_api_download(
    raw_url: str,
    fmt_key: str,
    bot,
    chat_id,
    status_msg_id,
):
    session = await get_http_session()

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text="<b>Fetching Instagram media...</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        async with session.get(
            INSTAGRAM_API_URL,
            params={"url": raw_url},
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            data = await resp.json(content_type=None)

        if not isinstance(data, dict):
            raise RuntimeError("Instagram API returned invalid response")

        if str(data.get("status") or "").lower() != "success":
            raise RuntimeError(data.get("message") or "Instagram API request failed")

        candidates = _extract_media_candidates(data)
        picked = _pick_media_for_format(candidates, fmt_key)

        if not picked:
            raise RuntimeError("No downloadable Instagram media found")

        media_type, media_url = picked
        title = _build_title(data, media_type)

        return await _download_with_progress(
            session=session,
            media_url=media_url,
            media_type=media_type,
            title=title,
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            progress_text="Download use sonzai api...",
        )

    except Exception as primary_error:
        print("[INSTAGRAM SONZAI FAILED]", repr(primary_error))

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg_id,
            text="<b>Sonzai failed, fallback to Indown...</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    result = await _instagram_scrape_fallback(raw_url)
    urls = result.get("urls") or []
    source = result.get("source") or "Indown"

    if not urls:
        raise RuntimeError("No downloadable Instagram media found")

    if fmt_key == "mp3":
        video_urls = []
        for media_url in urls:
            if _guess_media_type_from_url(media_url) == "video":
                video_urls.append(media_url)
        if not video_urls:
            raise RuntimeError("Instagram image post does not contain audio")
        urls = video_urls[:1]

    downloaded = []

    try:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text="<b>Downloading Instagram media...</b>",
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
                print("[INSTAGRAM FALLBACK DOWNLOAD ERROR]", media_url, repr(e))
                continue

        if not downloaded:
            raise RuntimeError("All media downloads failed")

        downloaded = _dedupe_downloaded_items(downloaded)

        if not downloaded:
            raise RuntimeError("All media downloads were duplicates or invalid")

        if len(downloaded) == 1:
            only = downloaded[0]
            title = "Instagram Post" if only["type"] == "photo" else "Instagram Video"
            safe_title = sanitize_filename(title)
            ext = os.path.splitext(only["path"])[1]
            final_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{safe_title}{ext}")

            if os.path.abspath(final_path) != os.path.abspath(only["path"]):
                os.replace(only["path"], final_path)

            return {
                "path": final_path,
                "title": title,
            }

        return {
            "items": downloaded,
            "title": "Instagram Media",
            "source": source,
        }

    except Exception:
        for item in downloaded:
            try:
                p = item.get("path")
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        raise