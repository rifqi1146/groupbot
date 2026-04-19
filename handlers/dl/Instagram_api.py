import os
import re
import json
import time
import uuid
import html
import logging
import mimetypes
import aiohttp
import aiofiles
from urllib.parse import urlparse, unquote

from utils.http import get_http_session
from .constants import TMP_DIR
from .utils import sanitize_filename, progress_bar
from .instagram_scrape import igdl_download_for_fallback, send_instagram_fallback_result, cleanup_instagram_fallback_result

log = logging.getLogger(__name__)

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

def is_instagram_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
        return host == "instagram.com" or host.endswith(".instagram.com") or host == "instagr.am"
    except Exception as e:
        text = (url or "").lower()
        log.warning("Failed to parse Instagram URL host | url=%s err=%s", url, e)
        return "instagram.com" in text or "instagr.am" in text

def _normalize_instagram_url(raw_url: str) -> str:
    text = (raw_url or "").strip()
    if not text:
        return text
    if not re.match(r"^https?://", text, flags=re.I):
        text = "https://" + text
    p = urlparse(text)
    scheme = p.scheme or "https"
    host = (p.netloc or "").lower()
    path = p.path or "/"
    if path != "/" and not path.endswith("/"):
        path += "/"
    return f"{scheme}://{host}{path}"

def _extract_meta(html_text: str, key: str) -> str:
    pats = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for pat in pats:
        m = re.search(pat, html_text or "", flags=re.I)
        if m:
            return html.unescape((m.group(1) or "").strip())
    return ""

def _guess_ext_from_url(url: str) -> str:
    try:
        path = unquote(urlparse(url).path or "")
        ext = os.path.splitext(path)[1].lower()
        if ext in (".mp4", ".mov", ".m4v", ".jpg", ".jpeg", ".png", ".webp"):
            return ext
    except Exception as e:
        log.warning("Failed to guess extension from media URL | url=%s err=%s", url, e)
    return ""

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

def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[:n].rstrip() + "..."

def _build_title(meta: dict, media_type: str) -> str:
    nickname = (meta.get("nickname") or "").strip()
    username = (meta.get("username") or "").strip()
    caption = (meta.get("caption") or "").strip()
    if nickname and username:
        base = f"{nickname} (@{username})"
    elif username:
        base = f"@{username}"
    elif nickname:
        base = nickname
    else:
        base = "Instagram Media"
    if caption:
        return f"{base} - {_truncate(caption, 80)}"
    if media_type == "video":
        return f"{base} - Instagram Video"
    return f"{base} - Instagram Image"

def _best_candidate(candidates: list[dict]) -> str:
    best = None
    best_w = -1
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        u = str(item.get("url") or "").strip()
        if not u:
            continue
        w = int(item.get("width") or 0)
        if w >= best_w:
            best_w = w
            best = u
    return best or ""

def _best_video_version(versions: list[dict]) -> str:
    best = None
    best_w = -1
    for item in versions or []:
        if not isinstance(item, dict):
            continue
        u = str(item.get("url") or "").strip()
        if not u:
            continue
        w = int(item.get("width") or 0)
        if w >= best_w:
            best_w = w
            best = u
    return best or ""

def _caption_from_edges(edges) -> str:
    if not isinstance(edges, list) or not edges:
        return ""
    node = (edges[0] or {}).get("node") or {}
    return (node.get("text") or "").strip()

def _parse_gql_media(media: dict) -> dict:
    if not isinstance(media, dict):
        return {"caption": "", "username": "", "nickname": "", "items": []}
    typename = str(media.get("__typename") or media.get("typename") or "").strip()
    owner = media.get("owner") or {}
    username = (owner.get("username") or "").strip()
    nickname = (owner.get("full_name") or owner.get("fullName") or "").strip()
    caption = _caption_from_edges(((media.get("edge_media_to_caption") or {}).get("edges")) or [])
    items = []
    if typename in ("GraphVideo", "XDTGraphVideo"):
        video_url = str(media.get("video_url") or "").strip()
        display_url = str(media.get("display_url") or "").strip()
        if video_url:
            items.append({"type": "video", "url": video_url, "thumbnail": display_url})
    elif typename in ("GraphImage", "XDTGraphImage"):
        display_url = str(media.get("display_url") or "").strip()
        if display_url:
            items.append({"type": "photo", "url": display_url})
    elif typename in ("GraphSidecar", "XDTGraphSidecar"):
        edges = (((media.get("edge_sidecar_to_children") or {}).get("edges")) or [])
        for edge in edges:
            node = (edge or {}).get("node") or {}
            node_type = str(node.get("__typename") or node.get("typename") or "").strip()
            if node_type in ("GraphVideo", "XDTGraphVideo"):
                video_url = str(node.get("video_url") or "").strip()
                display_url = str(node.get("display_url") or "").strip()
                if video_url:
                    items.append({"type": "video", "url": video_url, "thumbnail": display_url})
            elif node_type in ("GraphImage", "XDTGraphImage"):
                display_url = str(node.get("display_url") or "").strip()
                if display_url:
                    items.append({"type": "photo", "url": display_url})
    return {"caption": caption, "username": username, "nickname": nickname, "items": items}

def _parse_v1_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return {"caption": "", "username": "", "nickname": "", "items": []}
    user = item.get("user") or {}
    username = (user.get("username") or "").strip()
    nickname = (user.get("full_name") or "").strip()
    caption_obj = item.get("caption") or {}
    caption = (caption_obj.get("text") or "").strip()
    items = []
    media_type = int(item.get("media_type") or 0)
    if media_type == 2:
        video_url = _best_video_version(item.get("video_versions") or [])
        thumb = _best_candidate((((item.get("image_versions2") or {}).get("candidates")) or []))
        if video_url:
            items.append({"type": "video", "url": video_url, "thumbnail": thumb})
    elif media_type == 1:
        image_url = _best_candidate((((item.get("image_versions2") or {}).get("candidates")) or []))
        if image_url:
            items.append({"type": "photo", "url": image_url})
    elif media_type == 8:
        for child in item.get("carousel_media") or []:
            child_type = int(child.get("media_type") or 0)
            if child_type == 2:
                video_url = _best_video_version(child.get("video_versions") or [])
                thumb = _best_candidate((((child.get("image_versions2") or {}).get("candidates")) or []))
                if video_url:
                    items.append({"type": "video", "url": video_url, "thumbnail": thumb})
            elif child_type == 1:
                image_url = _best_candidate((((child.get("image_versions2") or {}).get("candidates")) or []))
                if image_url:
                    items.append({"type": "photo", "url": image_url})
    return {"caption": caption, "username": username, "nickname": nickname, "items": items}

def _extract_shortcode_media_from_html(html_text: str):
    pats = [
        r'"shortcode_media":(\{.*?\})\s*,\s*"show_suggested_profiles"',
        r'"xdt_shortcode_media":(\{.*?\})\s*,\s*"viewer"',
        r'"shortcode_media":(\{.*?\})\s*\}\s*\]\s*\}',
    ]
    for pat in pats:
        m = re.search(pat, html_text or "", flags=re.S)
        if not m:
            continue
        raw = m.group(1)
        try:
            return json.loads(raw)
        except Exception:
            continue
    return None

async def _fetch_instagram_metadata(raw_url: str) -> dict:
    session = await get_http_session()
    url = _normalize_instagram_url(raw_url)
    attempts = [
        ("json", url.rstrip("/") + "/?__a=1&__d=dis"),
        ("html", url),
    ]
    last_err = None
    for mode, target in attempts:
        try:
            if mode == "json":
                async with session.get(target, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as resp:
                    if resp.status >= 400:
                        raise RuntimeError(f"Instagram JSON HTTP {resp.status}")
                    data = await resp.json(content_type=None)
                if isinstance(data, dict):
                    if isinstance((data.get("graphql") or {}).get("shortcode_media"), dict):
                        parsed = _parse_gql_media((data.get("graphql") or {}).get("shortcode_media"))
                        if parsed["items"]:
                            return parsed
                    if isinstance((((data.get("data") or {}).get("xdt_shortcode_media"))), dict):
                        parsed = _parse_gql_media(((data.get("data") or {}).get("xdt_shortcode_media")))
                        if parsed["items"]:
                            return parsed
                    items = data.get("items") or []
                    if isinstance(items, list) and items:
                        parsed = _parse_v1_item(items[0])
                        if parsed["items"]:
                            return parsed
                raise RuntimeError("Instagram JSON metadata not found")
            async with session.get(target, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Instagram HTML HTTP {resp.status}")
                html_text = await resp.text()
            media = _extract_shortcode_media_from_html(html_text)
            if isinstance(media, dict):
                parsed = _parse_gql_media(media)
                if parsed["items"]:
                    return parsed
            og_video = _extract_meta(html_text, "og:video") or _extract_meta(html_text, "og:video:secure_url")
            og_image = _extract_meta(html_text, "og:image")
            caption = _extract_meta(html_text, "og:title") or _extract_meta(html_text, "og:description")
            if og_video:
                return {"caption": caption, "username": "", "nickname": "", "items": [{"type": "video", "url": og_video, "thumbnail": og_image}]}
            if og_image:
                return {"caption": caption, "username": "", "nickname": "", "items": [{"type": "photo", "url": og_image}]}
            raise RuntimeError("Instagram HTML metadata not found")
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("Failed to fetch Instagram metadata")

def _pick_media_for_format(items: list[dict], fmt_key: str) -> list[dict]:
    if not items:
        return []
    if fmt_key == "mp3":
        for item in items:
            if item.get("type") == "video":
                return [item]
        return []
    if len(items) == 1:
        return items
    has_video = any(item.get("type") == "video" for item in items)
    if has_video:
        return items
    return items

async def _safe_edit_status(bot, chat_id, message_id, text: str):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML")
    except Exception as e:
        log.warning("Failed to edit Instagram status message | chat_id=%s message_id=%s err=%s", chat_id, message_id, e)

async def _download_media_with_progress(session, media_url: str, media_type: str, out_path: str, bot, chat_id, status_msg_id, title_text: str):
    async with session.get(media_url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=180), allow_redirects=True) as media_resp:
        if media_resp.status >= 400:
            raise RuntimeError(f"Failed to download media: HTTP {media_resp.status}")
        total = int(media_resp.headers.get("Content-Length", 0))
        downloaded = 0
        last = 0.0
        async with aiofiles.open(out_path, "wb") as f:
            async for chunk in media_resp.content.iter_chunked(64 * 1024):
                await f.write(chunk)
                downloaded += len(chunk)
                if total and time.time() - last >= 1.0:
                    pct = downloaded / total * 100
                    await _safe_edit_status(
                        bot=bot,
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=f"<b>{title_text}</b>\n\n<code>{progress_bar(pct)}</code>",
                    )
                    last = time.time()

async def instagram_api_download(raw_url: str, fmt_key: str, bot, chat_id, status_msg_id):
    session = await get_http_session()
    created_paths = []
    await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>Fetching Instagram media...</b>")
    try:
        meta = await _fetch_instagram_metadata(raw_url)
        picked_items = _pick_media_for_format(meta.get("items") or [], fmt_key)
        if not picked_items:
            if fmt_key == "mp3":
                raise RuntimeError("Instagram image post does not contain audio")
            raise RuntimeError("No downloadable Instagram media found")
        title = _build_title(meta, picked_items[0].get("type") or "photo")
        if len(picked_items) == 1:
            item = picked_items[0]
            media_type = item.get("type") or "photo"
            media_url = str(item.get("url") or "").strip()
            if not media_url:
                raise RuntimeError("Instagram media URL is empty")
            async with session.get(media_url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Failed to probe media: HTTP {resp.status}")
                content_type = resp.headers.get("Content-Type", "")
            ext = _guess_ext(content_type, media_type, media_url)
            safe_title = sanitize_filename(title)
            out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{safe_title}{ext}")
            await _download_media_with_progress(
                session=session,
                media_url=media_url,
                media_type=media_type,
                out_path=out_path,
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
                title_text="<b>Downloading Instagram media...</b>",
            )
            created_paths.append(out_path)
            return {"path": out_path, "title": title}
        items = []
        total_items = len(picked_items)
        for idx, item in enumerate(picked_items, start=1):
            media_type = item.get("type") or "photo"
            media_url = str(item.get("url") or "").strip()
            if not media_url:
                continue
            async with session.get(media_url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Failed to probe media: HTTP {resp.status}")
                content_type = resp.headers.get("Content-Type", "")
            item_title = title if idx == 1 else f"{title} {idx}"
            ext = _guess_ext(content_type, media_type, media_url)
            safe_title = sanitize_filename(item_title)
            out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{safe_title}{ext}")
            await _download_media_with_progress(
                session=session,
                media_url=media_url,
                media_type=media_type,
                out_path=out_path,
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
                title_text=f"<b>Downloading Instagram media {idx}/{total_items}...</b>",
            )
            created_paths.append(out_path)
            items.append({"path": out_path, "type": media_type})
        if not items:
            raise RuntimeError("No Instagram media downloaded")
        return {"items": items, "title": title, "source": "Instagram"}
    except Exception as e:
        log.warning("Instagram direct extractor failed, falling back to Indown | url=%s fmt=%s err=%r", raw_url, fmt_key, e)
        for path in created_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception as cleanup_err:
                log.warning("Failed to remove partial Instagram file | path=%s err=%s", path, cleanup_err)
    await _safe_edit_status(bot=bot, chat_id=chat_id, message_id=status_msg_id, text="<b>Instagram extractor failed, fallback to Indown...</b>")
    return await igdl_download_for_fallback(
        bot=bot,
        chat_id=chat_id,
        reply_to=None,
        status_msg_id=status_msg_id,
        url=raw_url,
    )

async def send_instagram_result(bot, chat_id: int, reply_to: int, result: dict):
    if result.get("items"):
        await send_instagram_fallback_result(bot=bot, chat_id=chat_id, reply_to=reply_to, result=result)
        return
    path = result.get("path")
    title = result.get("title") or "Instagram Media"
    if not path or not os.path.exists(path):
        raise RuntimeError("Instagram media file not found")
    with open(path, "rb") as f:
        if path.lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
            await bot.send_video(chat_id=chat_id, video=f, caption=title, reply_to_message_id=reply_to, supports_streaming=True)
        else:
            await bot.send_photo(chat_id=chat_id, photo=f, caption=title, reply_to_message_id=reply_to)

async def cleanup_instagram_result(result: dict):
    await cleanup_instagram_fallback_result(result)