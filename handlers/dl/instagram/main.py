import os
import re
import json
import time
import uuid
import html
import shutil
import asyncio
import base64
import random
import string
import logging
import mimetypes
import aiohttp
import aiofiles
from urllib.parse import urlparse, unquote
from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR
from handlers.dl.utils import progress_bar
from handlers.dl.instagram.fallback import igdl_download_for_fallback, cleanup_instagram_fallback_result

log = logging.getLogger(__name__)
GRAPHQL_ENDPOINT = "https://www.instagram.com/graphql/query/"
POLARIS_ACTION = "PolarisPostActionLoadPostQueryQuery"
GRAPHQL_DOC_ID = "8845758582119845"
WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "max-age=0",
    "Dnt": "1",
    "Priority": "u=0, i",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
_LAST_IG_STATUS_TEXT = {}

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

def _extract_shortcode(raw_url: str) -> str:
    text = _normalize_instagram_url(raw_url)
    m = re.search(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", text, flags=re.I)
    return (m.group(1) if m else "").strip()

def _extract_meta(html_text: str, key: str) -> str:
    for pat in (
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ):
        m = re.search(pat, html_text or "", flags=re.I)
        if m:
            return html.unescape((m.group(1) or "").strip())
    return ""

def _extract_json_ld_metadata(html_text: str) -> dict:
    matches = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text or "", flags=re.I | re.S)
    for raw in matches:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(html.unescape(raw))
        except Exception:
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if not isinstance(obj, dict):
                continue
            caption = str(obj.get("caption") or obj.get("description") or obj.get("name") or "").strip()
            username = ""
            nickname = ""
            author = obj.get("author")
            if isinstance(author, dict):
                nickname = str(author.get("name") or "").strip()
                alt = str(author.get("alternateName") or "").strip()
                if alt:
                    username = alt.lstrip("@")
                elif nickname.startswith("@"):
                    username = nickname.lstrip("@")
                    nickname = ""
            if caption or username or nickname:
                return {"caption": caption, "username": username, "nickname": nickname}
    return {"caption": "", "username": "", "nickname": ""}

def _fallback_caption_meta(primary_html: str, secondary_html: str = "") -> dict:
    for source in (primary_html or "", secondary_html or ""):
        meta = _extract_json_ld_metadata(source)
        if meta.get("caption") or meta.get("username") or meta.get("nickname"):
            return meta
    caption = (
        _extract_meta(primary_html, "og:description")
        or _extract_meta(primary_html, "twitter:description")
        or _extract_meta(primary_html, "description")
        or _extract_meta(primary_html, "og:title")
        or _extract_meta(primary_html, "twitter:title")
        or _extract_meta(secondary_html, "og:description")
        or _extract_meta(secondary_html, "twitter:description")
        or _extract_meta(secondary_html, "description")
        or _extract_meta(secondary_html, "og:title")
        or _extract_meta(secondary_html, "twitter:title")
    ).strip()
    username = ""
    nickname = ""
    m = re.search(r"@([A-Za-z0-9._]+)", caption)
    if m:
        username = m.group(1).strip()
    title_tag = (
        _extract_meta(primary_html, "og:title")
        or _extract_meta(primary_html, "twitter:title")
        or _extract_meta(secondary_html, "og:title")
        or _extract_meta(secondary_html, "twitter:title")
    ).strip()
    if title_tag:
        nickname = title_tag.split(" on Instagram", 1)[0].strip() if " on Instagram" in title_tag else title_tag
    return {"caption": caption, "username": username, "nickname": nickname}

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
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip().lower()) or ""
    if guessed:
        return guessed
    return ".mp4" if media_type == "video" else ".jpg"

def _safe_name(text: str, fallback: str = "instagram_media", limit: int = 120) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", (text or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = fallback
    return text[:limit].rstrip(" .")

def _normalize_caption_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", text)

def _build_title(meta: dict, media_type: str) -> str:
    nickname = (meta.get("nickname") or "").strip()
    username = (meta.get("username") or "").strip()
    caption = _normalize_caption_text(meta.get("caption") or "")
    if nickname and username:
        base = f"{nickname} (@{username})"
    elif username:
        base = f"@{username}"
    elif nickname:
        base = nickname
    else:
        base = "Instagram Media"
    full = f"{base} - {caption}".strip() if caption else f"{base} - Instagram {'Video' if media_type == 'video' else 'Image'}"
    return full[:1024].rstrip()

def _caption_from_media(media: dict) -> str:
    if not isinstance(media, dict):
        return ""
    edges = (((media.get("edge_media_to_caption") or {}).get("edges")) or [])
    if isinstance(edges, list) and edges:
        text = (((edges[0] or {}).get("node") or {}).get("text") or "").strip()
        if text:
            return text
    caption_obj = media.get("caption") or {}
    if isinstance(caption_obj, dict):
        text = (caption_obj.get("text") or "").strip()
        if text:
            return text
    for key in ("accessibility_caption", "title"):
        text = str(media.get(key) or "").strip()
        if text:
            return text
    return ""

def _parse_gql_media(media: dict) -> dict:
    if not isinstance(media, dict):
        return {"caption": "", "username": "", "nickname": "", "items": []}
    typename = str(media.get("__typename") or media.get("typename") or "").strip()
    owner = media.get("owner") or {}
    username = (owner.get("username") or "").strip()
    nickname = (owner.get("full_name") or owner.get("fullName") or "").strip()
    caption = _caption_from_media(media)
    items = []
    def add_item(kind: str, url: str, thumb: str = "", dims: dict | None = None):
        url = str(url or "").strip()
        if not url:
            return
        dims = dims or {}
        items.append({"type": kind, "url": url, "thumbnail": str(thumb or "").strip(), "width": int(dims.get("width") or 0), "height": int(dims.get("height") or 0)})
    if typename in ("GraphVideo", "XDTGraphVideo"):
        add_item("video", media.get("video_url"), media.get("display_url"), media.get("dimensions"))
    elif typename in ("GraphImage", "XDTGraphImage"):
        add_item("photo", media.get("display_url"), "", media.get("dimensions"))
    elif typename in ("GraphSidecar", "XDTGraphSidecar"):
        for edge in (((media.get("edge_sidecar_to_children") or {}).get("edges")) or []):
            node = (edge or {}).get("node") or {}
            node_type = str(node.get("__typename") or node.get("typename") or "").strip()
            if node_type in ("GraphVideo", "XDTGraphVideo"):
                add_item("video", node.get("video_url"), node.get("display_url"), node.get("dimensions"))
            elif node_type in ("GraphImage", "XDTGraphImage"):
                add_item("photo", node.get("display_url"), "", node.get("dimensions"))
    return {"caption": caption, "username": username, "nickname": nickname, "items": items}

def _rand_alpha(n: int) -> str:
    return "".join(random.choice(string.ascii_letters) for _ in range(n))

def _rand_b64(n_bytes: int) -> str:
    return base64.urlsafe_b64encode(os.urandom(n_bytes)).decode().rstrip("=")

def _build_gql_request():
    rollout_hash = "1019933358"
    session_data = _rand_b64(8)
    csrf_token = _rand_b64(24)
    device_id = _rand_b64(18)
    machine_id = _rand_b64(18)
    headers = {
        "x-ig-app-id": "936619743392459",
        "x-fb-lsd": session_data,
        "x-csrftoken": csrf_token,
        "x-bloks-version-id": "6309c8d03d8a3f47a1658ba38b304a3f837142ef5f637ebf1f8f52d4b802951e",
        "x-asbd-id": "129477",
        "x-fb-friendly-name": POLARIS_ACTION,
        "content-type": "application/x-www-form-urlencoded",
        "cookie": "; ".join([f"csrftoken={csrf_token}", f"ig_did={device_id}", "wd=1280x720", "dpr=2", f"mid={machine_id}", "ig_nrcb=1"]),
    }
    body = {
        "__d": "www",
        "__a": "1",
        "__s": "::" + _rand_alpha(6),
        "__hs": "20126.HYP:instagram_web_pkg.2.1...0",
        "__req": "b",
        "__ccg": "EXCELLENT",
        "__rev": rollout_hash,
        "__hsi": "7436540909012459023",
        "__dyn": _rand_b64(90),
        "__csr": _rand_b64(90),
        "__user": "0",
        "__comet_req": "7",
        "libav": "0",
        "dpr": "2",
        "lsd": session_data,
        "jazoest": str(random.randint(1000, 99999)),
        "__spin_r": rollout_hash,
        "__spin_b": "trunk",
        "__spin_t": str(int(time.time())),
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": POLARIS_ACTION,
        "server_timestamps": "true",
        "doc_id": GRAPHQL_DOC_ID,
    }
    return headers, body

async def _fetch_gql_metadata(raw_url: str) -> dict:
    shortcode = _extract_shortcode(raw_url)
    if not shortcode:
        raise RuntimeError("Instagram shortcode not found")
    gql_headers, gql_body = _build_gql_request()
    headers = {**WEB_HEADERS, **gql_headers}
    body = dict(gql_body)
    body["variables"] = json.dumps({"shortcode": shortcode, "fetch_tagged_user_count": None, "hoisted_comment_id": None, "hoisted_reply_id": None}, separators=(",", ":"))
    session = await get_http_session()
    async with session.post(GRAPHQL_ENDPOINT, data=body, headers=headers, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Instagram GraphQL HTTP {resp.status}")
        data = await resp.json(content_type=None)
    if not isinstance(data, dict):
        raise RuntimeError("Instagram GraphQL invalid response")
    if str(data.get("status") or "").lower() not in ("ok", ""):
        raise RuntimeError(f"Instagram GraphQL bad status: {data.get('status')}")
    media = (data.get("data") or {}).get("xdt_shortcode_media") or (data.get("data") or {}).get("shortcode_media")
    if not isinstance(media, dict):
        raise RuntimeError("Instagram GraphQL shortcode_media not found")
    parsed = _parse_gql_media(media)
    if not parsed.get("items"):
        raise RuntimeError("Instagram GraphQL media empty")
    return parsed

def _extract_context_json_string(serverjs_blob: str) -> str:
    if not serverjs_blob:
        return ""
    m = re.search(r'"contextJSON"\s*:\s*"((?:\\.|[^"\\])*)"', serverjs_blob, flags=re.S)
    if m:
        try:
            return json.loads('"' + m.group(1) + '"')
        except Exception:
            pass
    m = re.search(r'"contextJSON"\s*:\s*(\{.*?\})(?:,|})', serverjs_blob, flags=re.S)
    return m.group(1) if m else ""

def _extract_embed_shortcode_media(html_text: str):
    m = re.search(r'new ServerJS\(\)\);s\.handle\((\{.*?\})\);requireLazy', html_text or "", flags=re.S)
    if not m:
        return None
    ctx_raw = _extract_context_json_string(m.group(1))
    if not ctx_raw:
        return None
    try:
        ctx_data = json.loads(ctx_raw)
    except Exception:
        return None
    media = (ctx_data.get("gql_data") or {}).get("shortcode_media")
    return media if isinstance(media, dict) else None

async def _fetch_embed_metadata(raw_url: str) -> dict:
    shortcode = _extract_shortcode(raw_url)
    if not shortcode:
        raise RuntimeError("Instagram shortcode not found")
    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned"
    session = await get_http_session()
    async with session.get(embed_url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Instagram embed HTTP {resp.status}")
        html_text = await resp.text()
    media = _extract_embed_shortcode_media(html_text)
    if not isinstance(media, dict):
        raise RuntimeError("Instagram embed shortcode_media not found")
    parsed = _parse_gql_media(media)
    if not parsed.get("items"):
        raise RuntimeError("Instagram embed media empty")
    if not parsed.get("caption") or not parsed.get("username") or not parsed.get("nickname"):
        fallback = _fallback_caption_meta(html_text)
        parsed["caption"] = parsed.get("caption") or fallback.get("caption") or ""
        parsed["username"] = parsed.get("username") or fallback.get("username") or ""
        parsed["nickname"] = parsed.get("nickname") or fallback.get("nickname") or ""
    return parsed

async def _fetch_instagram_caption_meta(raw_url: str) -> dict:
    session = await get_http_session()
    url = _normalize_instagram_url(raw_url)
    last_err = None
    for target in (url.rstrip("/") + "/embed/captioned/", url):
        try:
            async with session.get(target, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Instagram metadata HTTP {resp.status}")
                html_text = await resp.text()
            meta = _extract_json_ld_metadata(html_text)
            if meta.get("caption") or meta.get("username") or meta.get("nickname"):
                return meta
            meta = _fallback_caption_meta(html_text)
            if meta.get("caption") or meta.get("username") or meta.get("nickname"):
                return meta
        except Exception as e:
            last_err = e
    if last_err:
        log.warning("Instagram metadata scrape failed | url=%s err=%r", raw_url, last_err)
    return {"caption": "", "username": "", "nickname": ""}

async def _fetch_instagram_metadata(raw_url: str) -> dict:
    errors = []
    for func in (_fetch_gql_metadata, _fetch_embed_metadata):
        try:
            meta = await func(raw_url)
            if meta.get("caption") or meta.get("username") or meta.get("nickname") or meta.get("items"):
                return meta
        except Exception as e:
            errors.append(repr(e))
    raise RuntimeError(" ; ".join(errors) if errors else "Instagram metadata not found")

def _pick_direct_items(items: list[dict], fmt_key: str) -> list[dict]:
    if not items:
        return []
    if fmt_key == "mp3":
        for item in items:
            if item.get("type") == "video" and item.get("url"):
                return [item]
        return []
    return [{"type": str(item.get("type") or "").strip().lower(), "url": str(item.get("url") or "").strip(), "thumbnail": str(item.get("thumbnail") or "").strip()} for item in items if isinstance(item, dict) and str(item.get("type") or "").strip().lower() in ("photo", "video") and str(item.get("url") or "").strip()]

async def _safe_edit_status(bot, chat_id, message_id, text: str):
    key = (int(chat_id), int(message_id))
    text = str(text or "")
    if _LAST_IG_STATUS_TEXT.get(key) == text:
        return
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML")
        _LAST_IG_STATUS_TEXT[key] = text
        log.info("Instagram status updated | chat_id=%s message_id=%s text=%r", chat_id, message_id, text)
    except Exception as e:
        err = str(e or "")
        if "Message is not modified" in err or "message is not modified" in err:
            _LAST_IG_STATUS_TEXT[key] = text
            return
        log.warning("Failed to edit Instagram status message | chat_id=%s message_id=%s err=%s", chat_id, message_id, e)

async def _probe_total_bytes(session, url: str, headers: dict | None = None) -> int:
    try:
        async with session.head(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            if total > 0:
                return total
    except Exception:
        pass
    try:
        h = dict(headers or {})
        h["Range"] = "bytes=0-0"
        async with session.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
            content_range = resp.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)$", content_range)
            if m:
                return int(m.group(1))
            if resp.headers.get("Content-Length"):
                return int(resp.headers.get("Content-Length", 0) or 0)
    except Exception:
        pass
    return 0

def _format_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 B"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"

async def _aria2c_download_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str, headers: dict | None = None):
    aria2 = shutil.which("aria2c")
    if not aria2:
        raise RuntimeError("aria2c not found in PATH")
    total = await _probe_total_bytes(session, media_url, headers=headers)
    out_dir = os.path.dirname(out_path) or "."
    out_name = os.path.basename(out_path)
    cmd = [
        aria2,
        "--dir", out_dir,
        "--out", out_name,
        "--file-allocation=none",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--continue=true",
        "--max-connection-per-server=8",
        "--split=8",
        "--min-split-size=1M",
        "--summary-interval=0",
        "--download-result=hide",
        "--console-log-level=warn",
    ]
    for k, v in (headers or {}).items():
        if v:
            cmd.extend(["--header", f"{k}: {v}"])
    cmd.append(media_url)
    log.info("Instagram aria2c download start | out=%s total=%s", out_path, _format_size(total))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    last_edit = 0.0
    while proc.returncode is None:
        await asyncio.sleep(0.7)
        if not os.path.exists(out_path):
            continue
        try:
            downloaded = os.path.getsize(out_path)
        except Exception:
            continue
        if downloaded <= 0:
            continue
        now = time.time()
        if total > 0 and now - last_edit >= 1.5:
            pct = min(downloaded * 100 / total, 100.0)
            await _safe_edit_status(
                bot,
                chat_id,
                status_msg_id,
                f"<b>{html.escape(title_text)}</b>\n\n<code>{html.escape(progress_bar(pct))}</code>\n<code>{html.escape(_format_size(downloaded))}/{html.escape(_format_size(total))}</code>",
            )
            last_edit = now
    _, stderr = await proc.communicate()
    err = stderr.decode(errors="ignore").strip() if stderr else ""
    if proc.returncode != 0:
        raise RuntimeError(err or f"aria2c exited with code {proc.returncode}")
    if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
        raise RuntimeError("aria2c download output empty")
    log.info("Instagram aria2c download success | file=%s size=%s", out_path, _format_size(os.path.getsize(out_path)))
    
async def _download_media_with_progress(session, media_url: str, out_path: str, bot, chat_id, status_msg_id, title_text: str):
    try:
        await _aria2c_download_with_progress(
            session=session,
            media_url=media_url,
            out_path=out_path,
            bot=bot,
            chat_id=chat_id,
            status_msg_id=status_msg_id,
            title_text=title_text,
            headers=WEB_HEADERS,
        )
        return
    except Exception as e:
        log.warning("Instagram aria2c failed, fallback aiohttp | err=%r", e)
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
    async with session.get(media_url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=180), allow_redirects=True) as media_resp:
        if media_resp.status >= 400:
            raise RuntimeError(f"Failed to download media: HTTP {media_resp.status}")
        total = int(media_resp.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        last = 0.0
        async with aiofiles.open(out_path, "wb") as f:
            async for chunk in media_resp.content.iter_chunked(256 * 1024):
                if not chunk:
                    continue
                await f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if total and now - last >= 1.5:
                    pct = downloaded / total * 100
                    await _safe_edit_status(
                        bot,
                        chat_id,
                        status_msg_id,
                        f"<b>{html.escape(title_text)}</b>\n\n<code>{html.escape(progress_bar(pct))}</code>",
                    )
                    last = now
    log.info("Instagram aiohttp download success | file=%s size=%s", out_path, _format_size(os.path.getsize(out_path) if os.path.exists(out_path) else 0))

async def _download_direct_instagram_items(meta: dict, fmt_key: str, bot, chat_id, status_msg_id) -> dict:
    session = await get_http_session()
    picked_items = _pick_direct_items(meta.get("items") or [], fmt_key)
    if not picked_items:
        if fmt_key == "mp3":
            raise RuntimeError("Instagram image post does not contain audio")
        raise RuntimeError("No direct Instagram media found")
    title = _build_title(meta, picked_items[0].get("type") or "photo")
    file_stub = _safe_name(title)
    created_paths = []
    try:
        if len(picked_items) == 1:
            item = picked_items[0]
            media_type = item.get("type") or "photo"
            media_url = item.get("url") or ""
            async with session.get(media_url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Failed to probe media: HTTP {resp.status}")
                content_type = resp.headers.get("Content-Type", "")
            out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{file_stub}{_guess_ext(content_type, media_type, media_url)}")
            await _download_media_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id, "Downloading Instagram media (direct)...")
            created_paths.append(out_path)
            log.info("Instagram direct download success | file=%s", out_path)
            return {"path": out_path, "title": title}
        result_items = []
        total_items = len(picked_items)
        for idx, item in enumerate(picked_items, start=1):
            media_type = item.get("type") or "photo"
            media_url = item.get("url") or ""
            async with session.get(media_url, headers=WEB_HEADERS, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Failed to probe media: HTTP {resp.status}")
                content_type = resp.headers.get("Content-Type", "")
            out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{file_stub}_{idx}{_guess_ext(content_type, media_type, media_url)}")
            await _download_media_with_progress(session, media_url, out_path, bot, chat_id, status_msg_id, f"Downloading Instagram media {idx}/{total_items} (direct)...")
            created_paths.append(out_path)
            result_items.append({"path": out_path, "type": media_type})
            log.info("Instagram direct item success | index=%s/%s file=%s", idx, total_items, out_path)
        if not result_items:
            raise RuntimeError("No Instagram media downloaded")
        return {"items": result_items, "title": title, "source": "instagram_direct"}
    except Exception as e:
        log.warning("Instagram direct media download failed | err=%r", e)
        for path in created_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        raise

async def instagram_api_download(raw_url: str, fmt_key: str, bot, chat_id, status_msg_id):
    meta = {"caption": "", "username": "", "nickname": "", "items": []}
    await _safe_edit_status(bot, chat_id, status_msg_id, "<b>Fetching Instagram metadata...</b>")
    try:
        meta = await _fetch_instagram_metadata(raw_url)
        log.info("Instagram primary metadata success | url=%s caption_len=%s username=%r nickname=%r items=%s", raw_url, len(meta.get("caption") or ""), meta.get("username"), meta.get("nickname"), len(meta.get("items") or []))
    except Exception as e:
        log.warning("Primary Instagram metadata extractor failed | url=%s err=%r", raw_url, e)
        meta = await _fetch_instagram_caption_meta(raw_url)
        log.info("Instagram fallback metadata success | url=%s caption_len=%s username=%r nickname=%r", raw_url, len(meta.get("caption") or ""), meta.get("username"), meta.get("nickname"))
    log.info("Instagram metadata result | url=%s caption=%r username=%r nickname=%r items=%r", raw_url, meta.get("caption"), meta.get("username"), meta.get("nickname"), len(meta.get("items") or []))
    try:
        await _safe_edit_status(bot, chat_id, status_msg_id, "<b>Downloading Instagram media (direct)...</b>")
        result = await _download_direct_instagram_items(meta, fmt_key, bot, chat_id, status_msg_id)
        _LAST_IG_STATUS_TEXT.pop((int(chat_id), int(status_msg_id)), None)
        return result
    except Exception as e:
        log.warning("Instagram direct media failed, falling back | url=%s err=%r", raw_url, e)
    await _safe_edit_status(bot, chat_id, status_msg_id, "<b>Direct download failed, fallback to scraper...</b>")
    result = await igdl_download_for_fallback(bot=bot, chat_id=chat_id, reply_to=None, status_msg_id=status_msg_id, url=raw_url)
    if isinstance(result, dict):
        media_type = "photo"
        if result.get("path"):
            if str(result.get("path") or "").lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
                media_type = "video"
        elif result.get("items"):
            media_type = ((result.get("items") or [{}])[0]).get("type") or "photo"
        if (meta.get("caption") or "").strip() or (meta.get("username") or "").strip() or (meta.get("nickname") or "").strip():
            result["title"] = _build_title({"caption": meta.get("caption") or "", "username": meta.get("username") or "", "nickname": meta.get("nickname") or ""}, media_type)
    log.info("Instagram fallback download success | url=%s", raw_url)
    _LAST_IG_STATUS_TEXT.pop((int(chat_id), int(status_msg_id)), None)
    return result

async def cleanup_instagram_result(result: dict):
    await cleanup_instagram_fallback_result(result)