import os
import re
import html
import uuid
import time
import shutil
import socket
import asyncio
import logging
import ipaddress
from urllib.parse import urlparse, urljoin
from telegram import Update
from telegram.ext import ContextTypes
from handlers.dl.ytdlp import ytdlp_download
from handlers.dl.service import send_downloaded_media
from handlers.dl.remux import prepare_download_result_for_send

log = logging.getLogger(__name__)

TMP_DIR = os.getenv("TMP_DIR", "downloads")
SCRAPLING_BIN = os.getenv("SCRAPLING_BIN") or shutil.which("scrapling")
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "60"))
SCRAPER_IFRAME_DOMAINS = tuple(x.strip().lower() for x in os.getenv("SCRAPER_IFRAME_DOMAINS", "nozstream.site").split(",") if x.strip())
SCRAPER_IGNORE_DOMAINS = tuple(x.strip().lower() for x in os.getenv("SCRAPER_IGNORE_DOMAINS", "googletagmanager.com,google.com,doubleclick.net,googlesyndication.com,facebook.com,analytics.google.com,google-analytics.com").split(",") if x.strip())

def _host(url: str) -> str:
    try:
        return (urlparse((url or "").strip()).hostname or "").lower()
    except Exception:
        return ""

def _host_match(host: str, domain: str) -> bool:
    host = (host or "").lower()
    domain = (domain or "").lower()
    return host == domain or host.endswith("." + domain)

def _is_http_url(url: str) -> bool:
    try:
        p = urlparse((url or "").strip())
        return p.scheme in ("http", "https") and bool(p.hostname)
    except Exception:
        return False

def _is_ignored_url(url: str) -> bool:
    host = _host(url)
    return any(_host_match(host, d) for d in SCRAPER_IGNORE_DOMAINS)

def _is_blocked_ip(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
        return obj.is_private or obj.is_loopback or obj.is_link_local or obj.is_multicast or obj.is_reserved or obj.is_unspecified
    except Exception:
        return True

async def _is_safe_public_url(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        ips = {x[4][0] for x in infos if x and x[4]}
        if not ips:
            return False
        return not any(_is_blocked_ip(ip) for ip in ips)
    except Exception:
        return False

def _clean_found_url(value: str, base_url: str) -> str | None:
    value = html.unescape((value or "").strip().strip("'\""))
    value = value.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/").replace("\\u0026", "&").replace("\\u0026amp;", "&")
    if not value or value.lower().startswith(("javascript:", "data:", "blob:")):
        return None
    abs_url = urljoin(base_url, value)
    return abs_url if _is_http_url(abs_url) else None

def _add_unique(items: list[str], url: str | None):
    if url and url not in items:
        items.append(url)

def _clean_links(links: list[str]) -> list[str]:
    return [x for x in links if x and not _is_ignored_url(x)]

def _short_url(url: str, limit: int = 220) -> str:
    url = str(url or "")
    return url if len(url) <= limit else url[:limit - 3] + "..."

def _fmt_links(title: str, links: list[str], limit: int = 4) -> str:
    usable = _clean_links(links)
    if not usable:
        return f"<b>{title}</b>\n<code>-</code>"
    out = [f"<b>{title}</b>"]
    for i, link in enumerate(usable[:limit], start=1):
        out.append(f"{i}. <code>{html.escape(_short_url(link))}</code>")
    if len(usable) > limit:
        out.append(f"...and {len(usable) - limit} more")
    return "\n".join(out)

def _build_caption(iframes: list[str], embeds: list[str], picked: str | None, elapsed: float | None = None) -> str:
    clean_iframes = _clean_links(iframes)
    clean_embeds = _clean_links(embeds)
    lines = [
        "<b>HTML scraper result</b>",
        "",
        f"Iframe count: <code>{len(clean_iframes)}</code> usable / <code>{len(iframes)}</code> raw",
        f"embedUrl count: <code>{len(clean_embeds)}</code> usable / <code>{len(embeds)}</code> raw",
        f"Matched link: <code>{html.escape(_short_url(picked or '-'))}</code>",
    ]
    if elapsed is not None:
        lines.append(f"Time: <i>{elapsed:.2f}s</i>")
    lines.extend(["", _fmt_links("Iframe links", iframes), "", _fmt_links("embedUrl links", embeds)])
    caption = "\n".join(lines)
    return caption[:1010] + "..." if len(caption) > 1024 else caption

def _extract_iframe_srcs(raw_html: str, base_url: str) -> list[str]:
    found = []
    text = html.unescape(raw_html or "")
    pattern = r"<iframe\b[^>]*\bsrc\s*=\s*(['\"])(.*?)\1"
    for m in re.finditer(pattern, text, flags=re.I | re.S):
        _add_unique(found, _clean_found_url(m.group(2), base_url))
    return found

def _extract_embed_urls(raw_html: str, base_url: str) -> list[str]:
    found = []
    text = html.unescape(raw_html or "")
    for m in re.finditer(r"""["']embedUrl["']\s*:\s*["']([^"']+)["']""", text, flags=re.I | re.S):
        _add_unique(found, _clean_found_url(m.group(1), base_url))
    for m in re.finditer(r"""\bembedUrl\b\s*[:=]\s*["']([^"']+)["']""", text, flags=re.I | re.S):
        _add_unique(found, _clean_found_url(m.group(1), base_url))
    for tag in re.findall(r"""<(?:meta|link)\b[^>]*>""", text, flags=re.I | re.S):
        attrs = dict((k.lower(), html.unescape(v.strip())) for k, _, v in re.findall(r"""([a-zA-Z_:.-]+)\s*=\s*(['"])(.*?)\2""", tag, flags=re.S))
        key = (attrs.get("itemprop") or attrs.get("property") or attrs.get("name") or "").lower()
        val = attrs.get("content") or attrs.get("href") or ""
        if key in ("embedurl", "embed_url", "og:video", "og:video:url", "og:video:secure_url", "twitter:player"):
            _add_unique(found, _clean_found_url(val, base_url))
    return found

def _extract_target_links(raw_html: str, base_url: str) -> tuple[list[str], list[str], list[str]]:
    iframes = _extract_iframe_srcs(raw_html, base_url)
    embeds = _extract_embed_urls(raw_html, base_url)
    links = []
    for x in _clean_links(iframes) + _clean_links(embeds):
        _add_unique(links, x)
    return iframes, embeds, links

def _pick_target_link(links: list[str]) -> str | None:
    links = _clean_links(links)
    for src in links:
        host = _host(src)
        if any(_host_match(host, d) for d in SCRAPER_IFRAME_DOMAINS):
            return src
    return links[0] if links else None

async def _send_html_result(msg, status, out_path: str, iframes: list[str], embeds: list[str], picked: str | None = None, elapsed: float | None = None):
    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    await status.edit_text(
        "<b>Sending HTML file...</b>\n\n"
        f"Iframe: <code>{len(_clean_links(iframes))}</code> usable / <code>{len(iframes)}</code> raw\n"
        f"embedUrl: <code>{len(_clean_links(embeds))}</code> usable / <code>{len(embeds)}</code> raw\n"
        f"Size: <code>{size} bytes</code>",
        parse_mode="HTML",
    )
    with open(out_path, "rb") as f:
        await msg.reply_document(document=f, filename=os.path.basename(out_path), caption=_build_caption(iframes, embeds, picked, elapsed), parse_mode="HTML")

async def _run_scrapling(url: str, out_path: str):
    if not SCRAPLING_BIN:
        raise RuntimeError("scrapling binary not found. Install it or set SCRAPLING_BIN.")
    cmd = [SCRAPLING_BIN, "extract", "stealthy-fetch", url, out_path]
    log.info("Scraper start | url=%s out=%s", url, out_path)
    log.info("Scraper command | %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SCRAPER_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(f"Scraper timeout after {SCRAPER_TIMEOUT}s")
    stdout_text = stdout.decode(errors="ignore") if stdout else ""
    stderr_text = stderr.decode(errors="ignore") if stderr else ""
    log.info("Scraper exit | code=%s", proc.returncode)
    if stdout_text:
        log.debug("Scraper stdout\n%s", stdout_text)
    if stderr_text:
        log.debug("Scraper stderr\n%s", stderr_text)
    if proc.returncode != 0:
        err = (stderr_text or stdout_text or f"scrapling exited with code {proc.returncode}").strip()
        raise RuntimeError(err[-1200:])
    if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
        raise RuntimeError("Scraper finished but HTML output is empty")

async def _scrape_target_link(url: str) -> tuple[str | None, str, list[str], list[str]]:
    os.makedirs(TMP_DIR, exist_ok=True)
    out_path = os.path.join(TMP_DIR, f"scraper_{uuid.uuid4().hex}.html")
    await _run_scrapling(url, out_path)
    with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    iframes, embeds, links = _extract_target_links(raw, url)
    picked = _pick_target_link(links)
    log.info("Scraper extracted | iframe=%s embedUrl=%s picked=%s", _clean_links(iframes), _clean_links(embeds), picked)
    return picked, out_path, iframes, embeds

async def scraper_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    if not context.args:
        return await msg.reply_text("Example: <code>/scraper https://link.com</code>", parse_mode="HTML")
    url = (context.args[0] or "").strip()
    if not _is_http_url(url):
        return await msg.reply_text("Invalid URL. Use http/https link.")
    if not await _is_safe_public_url(url):
        return await msg.reply_text("Blocked URL. Public http/https URL only.")
    started = time.monotonic()
    status = await msg.reply_text("🕷️ <b>Scraping page...</b>", parse_mode="HTML")
    out_path = None
    try:
        picked, out_path, iframes, embeds = await _scrape_target_link(url)
        elapsed = time.monotonic() - started
        await _send_html_result(msg, status, out_path, iframes, embeds, picked, elapsed)
        try:
            await status.delete()
        except Exception:
            pass
    except Exception as e:
        err = html.escape((str(e) or repr(e)).strip())[:3500]
        await status.edit_text(f"<b>Scraper failed</b>\n\n<code>{err}</code>", parse_mode="HTML")
    finally:
        try:
            if out_path and os.path.exists(out_path):
                os.remove(out_path)
                log.info("Scraper temp deleted | file=%s", out_path)
        except Exception as e:
            log.warning("Failed to delete scraper temp | file=%s err=%r", out_path, e)

async def sdl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    if not context.args:
        return await msg.reply_text("Example: <code>/sdl https://link.com</code>", parse_mode="HTML")
    url = (context.args[0] or "").strip()
    if not _is_http_url(url):
        return await msg.reply_text("Invalid URL. Use http/https link.")
    if not await _is_safe_public_url(url):
        return await msg.reply_text("Blocked URL. Public http/https URL only.")
    status = await msg.reply_text("🕷️ <b>Scraping page...</b>", parse_mode="HTML")
    out_path = None
    try:
        picked, out_path, iframes, embeds = await _scrape_target_link(url)
        if not picked:
            return await _send_html_result(msg, status, out_path, iframes, embeds)
        if not await _is_safe_public_url(picked):
            return await _send_html_result(msg, status, out_path, iframes, embeds, picked)
        await status.edit_text(
            "<b>Target link found</b>\n\n"
            f"<code>{html.escape(picked)}</code>\n\n"
            "<b>Downloading with yt-dlp...</b>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        log.info("SDL target picked | source=%s picked=%s", url, picked)
        path = await ytdlp_download(
            url=picked,
            fmt_key="video",
            bot=context.bot,
            chat_id=msg.chat_id,
            status_msg_id=status.message_id,
            format_id=None,
            has_audio=False,
        )
        path = await prepare_download_result_for_send(path, fmt_key="video")
        await send_downloaded_media(
            bot=context.bot,
            chat_id=msg.chat_id,
            reply_to=msg.message_id,
            status_msg_id=status.message_id,
            path=path,
            fmt_key="video",
            message_thread_id=getattr(msg, "message_thread_id", None),
        )
        await context.bot.delete_message(msg.chat_id, status.message_id)
    except Exception as e:
        err = html.escape((str(e) or repr(e)).strip())[:3500]
        try:
            await status.edit_text(f"<b>SDL failed</b>\n\n<code>{err}</code>", parse_mode="HTML")
        except Exception:
            pass
    finally:
        try:
            if out_path and os.path.exists(out_path):
                os.remove(out_path)
                log.info("Scraper temp deleted | file=%s", out_path)
        except Exception as e:
            log.warning("Failed to delete scraper temp | file=%s err=%r", out_path, e)