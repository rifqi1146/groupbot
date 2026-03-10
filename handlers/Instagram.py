import os
import re
import uuid
import html
import json
import asyncio
import aiohttp
import aiofiles

from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import ContextTypes

from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR


IG_URL_RE = re.compile(r"https?://(?:www\.)?(?:dd)?instagram\.com/[^\s]+", re.I)
IG_POST_RE = re.compile(r"https?://(?:www\.)?(?:dd)?instagram\.com/(?P<kind>reels?|p|tv)/(?P<code>[A-Za-z0-9_-]+)", re.I)
IG_STORY_RE = re.compile(r"https?://(?:www\.)?(?:dd)?instagram\.com/stories/(?P<user>[A-Za-z0-9._]+)/(?P<id>\d+)", re.I)
IG_SHARE_RE = re.compile(r"https?://(?:www\.)?(?:dd)?instagram\.com/share/", re.I)


def is_instagram(url: str) -> bool:
    return "instagram.com" in (url or "").lower() or "ddinstagram.com" in (url or "").lower()


def _truncate_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return "." * limit
    return text[: limit - 3].rstrip() + "..."


def _build_safe_caption(title: str, desc: str, bot_name: str, max_len: int = 1024) -> str:
    clean_title = (title or "Instagram").strip() or "Instagram"
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
        short_title = "Instagram"

    if short_desc:
        return (
            f"<blockquote>📸 {html.escape(short_title)}</blockquote>\n\n"
            f"{html.escape(short_desc)}\n\n"
            f"🪄 <i>Powered by {html.escape(clean_bot)}</i>"
        )

    return (
        f"<blockquote>📸 {html.escape(short_title)}</blockquote>\n\n"
        f"🪄 <i>Powered by {html.escape(clean_bot)}</i>"
    )


def _find_instagram_url(text: str) -> str:
    match = IG_URL_RE.search(text or "")
    return match.group(0).rstrip(").,!?]}>\"'") if match else ""


def _headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
    }


def _meta_content(html_text: str, prop: str) -> str:
    patterns = [
        rf'<meta[^>]+property="{re.escape(prop)}"[^>]+content="([^"]+)"',
        rf'<meta[^>]+content="([^"]+)"[^>]+property="{re.escape(prop)}"',
        rf"<meta[^>]+property='{re.escape(prop)}'[^>]+content='([^']+)'",
        rf"<meta[^>]+content='([^']+)'[^>]+property='{re.escape(prop)}'",
        rf'<meta[^>]+name="{re.escape(prop)}"[^>]+content="([^"]+)"',
        rf'<meta[^>]+content="([^"]+)"[^>]+name="{re.escape(prop)}"',
    ]

    for pattern in patterns:
        m = re.search(pattern, html_text, re.I)
        if m:
            return html.unescape(m.group(1)).strip()

    return ""


def _best_candidate(candidates: list) -> dict:
    if not isinstance(candidates, list) or not candidates:
        return {}
    return max(
        candidates,
        key=lambda x: (
            x.get("width") or x.get("config_width") or 0,
            x.get("height") or x.get("config_height") or 0,
        ),
    )


def _normalize_graphql_node(node: dict, items: list):
    if not isinstance(node, dict):
        return

    typename = node.get("__typename")
    is_video = bool(node.get("is_video"))

    if typename == "GraphSidecar":
        edges = ((node.get("edge_sidecar_to_children") or {}).get("edges") or [])
        for edge in edges:
            _normalize_graphql_node((edge or {}).get("node") or {}, items)
        return

    if typename == "GraphVideo" or is_video:
        video_url = node.get("video_url")
        if video_url:
            items.append(
                {
                    "type": "video",
                    "url": video_url,
                    "thumbnail": node.get("display_url") or "",
                }
            )
        return

    image_url = node.get("display_url")
    if image_url:
        items.append(
            {
                "type": "photo",
                "url": image_url,
                "thumbnail": image_url,
            }
        )


def _parse_graphql_payload(data: dict) -> dict:
    node = ((data or {}).get("graphql") or {}).get("shortcode_media") or {}
    if not node:
        raise RuntimeError("shortcode_media tidak ditemukan")

    caption_edges = ((node.get("edge_media_to_caption") or {}).get("edges") or [])
    caption = ""
    if caption_edges:
        caption = (((caption_edges[0] or {}).get("node") or {}).get("text") or "").strip()

    owner = (node.get("owner") or {}).get("username") or "Instagram"
    items = []
    _normalize_graphql_node(node, items)

    if not items:
        raise RuntimeError("media kosong")

    return {
        "title": owner,
        "caption": caption,
        "items": items,
    }


def _normalize_mobile_item(item: dict, items: list):
    if not isinstance(item, dict):
        return

    media_type = item.get("media_type")

    if media_type == 8:
        for child in item.get("carousel_media") or []:
            _normalize_mobile_item(child, items)
        return

    if media_type == 2:
        best_video = _best_candidate(item.get("video_versions") or [])
        if best_video.get("url"):
            items.append(
                {
                    "type": "video",
                    "url": best_video["url"],
                    "thumbnail": (_best_candidate(((item.get("image_versions2") or {}).get("candidates") or [])) or {}).get("url", ""),
                }
            )
        return

    best_image = _best_candidate(((item.get("image_versions2") or {}).get("candidates") or []))
    if best_image.get("url"):
        items.append(
            {
                "type": "photo",
                "url": best_image["url"],
                "thumbnail": best_image["url"],
            }
        )


def _parse_mobile_payload(data: dict) -> dict:
    items_root = (data or {}).get("items") or []
    if not items_root:
        raise RuntimeError("items tidak ditemukan")

    first = items_root[0] or {}
    caption = ((first.get("caption") or {}).get("text") or "").strip()
    owner = ((first.get("user") or {}).get("username") or "Instagram").strip()

    items = []
    _normalize_mobile_item(first, items)

    if not items:
        raise RuntimeError("media kosong")

    return {
        "title": owner,
        "caption": caption,
        "items": items,
    }


async def _resolve_share_url(session: aiohttp.ClientSession, url: str) -> str:
    if not IG_SHARE_RE.search(url or ""):
        return url

    async with session.get(
        url,
        headers=_headers(),
        allow_redirects=True,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as resp:
        return str(resp.url)


def _extract_shortcode_and_kind(url: str) -> tuple[str, str]:
    m = IG_POST_RE.search(url or "")
    if m:
        kind = (m.group("kind") or "p").lower()
        code = m.group("code")
        if kind == "reels":
            kind = "reel"
        return code, kind

    m = IG_STORY_RE.search(url or "")
    if m:
        return m.group("id"), "stories"

    raise RuntimeError("URL Instagram tidak didukung")


async def _fetch_via_web_json(session: aiohttp.ClientSession, shortcode: str, kind: str) -> dict:
    candidates = []

    if kind in ("p", "reel", "tv"):
        candidates.append(f"https://www.instagram.com/{kind}/{shortcode}/?__a=1&__d=dis")

    if kind != "p":
        candidates.append(f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis")

    seen = set()
    urls = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            urls.append(item)

    last_error = None

    for api_url in urls:
        try:
            async with session.get(
                api_url,
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                data = await resp.json(content_type=None)

            if isinstance(data, dict) and data.get("graphql", {}).get("shortcode_media"):
                return _parse_graphql_payload(data)

            if isinstance(data, dict) and data.get("items"):
                return _parse_mobile_payload(data)

            raise RuntimeError("payload JSON tidak cocok")
        except Exception as e:
            last_error = e

    raise RuntimeError(f"web json gagal: {last_error}")


async def _fetch_via_embed(session: aiohttp.ClientSession, shortcode: str, kind: str) -> dict:
    candidates = []

    if kind in ("p", "reel", "tv"):
        candidates.append(f"https://www.instagram.com/{kind}/{shortcode}/embed/captioned")

    if kind != "p":
        candidates.append(f"https://www.instagram.com/p/{shortcode}/embed/captioned")

    last_error = None

    for embed_url in candidates:
        try:
            async with session.get(
                embed_url,
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"embed HTTP {resp.status}")
                body = await resp.text()

            video_url = _meta_content(body, "og:video")
            image_url = _meta_content(body, "og:image")
            title = _meta_content(body, "og:title") or "Instagram"
            desc = _meta_content(body, "og:description") or ""

            media_url = video_url or image_url
            if not media_url:
                raise RuntimeError("embed media tidak ditemukan")

            return {
                "title": title,
                "caption": desc,
                "items": [
                    {
                        "type": "video" if video_url else "photo",
                        "url": media_url,
                        "thumbnail": image_url or media_url,
                    }
                ],
            }
        except Exception as e:
            last_error = e

    raise RuntimeError(f"embed gagal: {last_error}")


def _flatten_candidate_container(payload):
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            return payload
        for key in ("data", "result", "results", "response"):
            val = payload.get(key)
            if isinstance(val, dict) and isinstance(val.get("items"), list):
                return val
    return payload


async def _fetch_via_fallback_api(session: aiohttp.ClientSession, url: str) -> dict:
    api_url = (os.getenv("IG_FALLBACK_API") or "").strip()
    api_key = (os.getenv("IG_FALLBACK_API_KEY") or "").strip()

    if not api_url:
        raise RuntimeError("fallback api belum diset")

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = None
    last_error = None

    for mode in ("get", "post"):
        try:
            if mode == "get":
                async with session.get(
                    api_url,
                    params={"url": url},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}: {await resp.text()}")
                    data = await resp.json(content_type=None)
            else:
                merged_headers = dict(headers)
                merged_headers["Content-Type"] = "application/json"
                async with session.post(
                    api_url,
                    json={"url": url},
                    headers=merged_headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}: {await resp.text()}")
                    data = await resp.json(content_type=None)

            if data is not None:
                break
        except Exception as e:
            last_error = e

    if data is None:
        raise RuntimeError(f"fallback api gagal: {last_error}")

    root = _flatten_candidate_container(data)

    title = ""
    caption = ""
    items = []

    if isinstance(root, dict):
        title = (
            root.get("title")
            or root.get("username")
            or root.get("author")
            or "Instagram"
        )
        caption = (
            root.get("caption")
            or root.get("description")
            or root.get("text")
            or ""
        )

        raw_items = root.get("items") or root.get("media") or []
    else:
        raw_items = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        media_url = (
            item.get("url")
            or item.get("download_url")
            or item.get("video_url")
            or item.get("image_url")
            or item.get("src")
        )

        if not media_url and isinstance(item.get("urls"), list) and item.get("urls"):
            media_url = item["urls"][0]

        media_type = str(
            item.get("type")
            or item.get("media_type")
            or item.get("kind")
            or ""
        ).lower()

        if not media_url:
            continue

        if "video" in media_type or str(media_url).lower().endswith(".mp4"):
            items.append(
                {
                    "type": "video",
                    "url": media_url,
                    "thumbnail": item.get("thumbnail") or item.get("thumb") or "",
                }
            )
        else:
            items.append(
                {
                    "type": "photo",
                    "url": media_url,
                    "thumbnail": item.get("thumbnail") or item.get("thumb") or media_url,
                }
            )

    if not items:
        raise RuntimeError("fallback api tidak mengembalikan media")

    return {
        "title": str(title).strip() or "Instagram",
        "caption": str(caption).strip(),
        "items": items,
    }


async def _get_instagram_media(url: str) -> dict:
    session = await get_http_session()
    resolved_url = await _resolve_share_url(session, url)
    shortcode, kind = _extract_shortcode_and_kind(resolved_url)

    errors = []

    if kind == "stories":
        try:
            return await _fetch_via_fallback_api(session, resolved_url)
        except Exception as e:
            raise RuntimeError(f"story gagal: {e}")

    try:
        return await _fetch_via_web_json(session, shortcode, kind)
    except Exception as e:
        errors.append(f"web={e}")

    try:
        return await _fetch_via_embed(session, shortcode)
    except Exception as e:
        errors.append(f"embed={e}")

    try:
        return await _fetch_via_fallback_api(session, resolved_url)
    except Exception as e:
        errors.append(f"fallback={e}")

    raise RuntimeError(" ; ".join(errors))


def _guess_ext(url: str, kind: str) -> str:
    lower = (url or "").lower()

    for ext in (".mp4", ".jpg", ".jpeg", ".png", ".webp", ".heic"):
        if ext in lower.split("?")[0]:
            return ext

    return ".mp4" if kind == "video" else ".jpg"


async def _download_to_temp(session: aiohttp.ClientSession, url: str, kind: str) -> str:
    ext = _guess_ext(url, kind)
    path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}{ext}")

    async with session.get(
        url,
        headers=_headers(),
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(f"download gagal HTTP {resp.status}")

        async with aiofiles.open(path, "wb") as f:
            async for chunk in resp.content.iter_chunked(64 * 1024):
                await f.write(chunk)

    return path


async def _send_instagram_result(bot, chat_id: int, reply_to: int, result: dict):
    session = await get_http_session()
    bot_name = (await bot.get_me()).first_name or "Bot"

    title = result.get("title") or "Instagram"
    desc = result.get("caption") or ""
    items = result.get("items") or []

    if not items:
        raise RuntimeError("media kosong")

    caption = _build_safe_caption(title, desc, bot_name)

    if len(items) == 1:
        item = items[0]
        path = await _download_to_temp(session, item["url"], item["type"])
        try:
            if item["type"] == "video":
                with open(path, "rb") as f:
                    await bot.send_video(
                        chat_id=chat_id,
                        video=f,
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=False,
                        reply_to_message_id=reply_to,
                        disable_notification=True,
                    )
            else:
                with open(path, "rb") as f:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=caption,
                        parse_mode="HTML",
                        reply_to_message_id=reply_to,
                        disable_notification=True,
                    )
        finally:
            try:
                os.remove(path)
            except Exception:
                pass
        return

    chunk_size = 10
    chunks = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    for idx, chunk in enumerate(chunks):
        files = []
        handles = []
        media = []

        try:
            for i, item in enumerate(chunk):
                path = await _download_to_temp(session, item["url"], item["type"])
                files.append(path)

                handle = open(path, "rb")
                handles.append(handle)

                if item["type"] == "video":
                    media.append(
                        InputMediaVideo(
                            media=handle,
                            caption=caption if idx == 0 and i == 0 else None,
                            parse_mode="HTML" if idx == 0 and i == 0 else None,
                            supports_streaming=False,
                        )
                    )
                else:
                    media.append(
                        InputMediaPhoto(
                            media=handle,
                            caption=caption if idx == 0 and i == 0 else None,
                            parse_mode="HTML" if idx == 0 and i == 0 else None,
                        )
                    )

            await bot.send_media_group(
                chat_id=chat_id,
                media=media,
                reply_to_message_id=reply_to if idx == 0 else None,
                disable_notification=True,
            )
        finally:
            for handle in handles:
                try:
                    handle.close()
                except Exception:
                    pass

            for path in files:
                try:
                    os.remove(path)
                except Exception:
                    pass


async def _typing_loop(bot, chat_id, stop_event: asyncio.Event):
    try:
        while not stop_event.is_set():
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
    except Exception:
        pass


async def ig_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    raw_text = ""

    if msg.text and msg.text.startswith("/ig"):
        raw_text = " ".join(context.args) if context.args else ""
    elif msg.reply_to_message:
        raw_text = (
            msg.reply_to_message.text
            or msg.reply_to_message.caption
            or ""
        )

    url = _find_instagram_url(raw_text)

    if not url:
        return await msg.reply_text(
            "Gunakan:\n"
            "/ig <url instagram>\n\n"
            "Atau reply pesan yang ada link Instagram-nya."
        )

    stop = asyncio.Event()
    typing = asyncio.create_task(_typing_loop(context.bot, update.effective_chat.id, stop))

    try:
        result = await _get_instagram_media(url)

        stop.set()
        typing.cancel()

        await _send_instagram_result(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            reply_to=msg.message_id,
            result=result,
        )

    except Exception as e:
        stop.set()
        typing.cancel()
        await msg.reply_text(f"❌ Error: {html.escape(str(e))}")