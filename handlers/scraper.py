import os
import re
import socket
import asyncio
import logging
import ipaddress
from urllib.parse import urlparse, urljoin
from telegram import Update
from telegram.ext import ContextTypes
from scrapling.fetchers import StealthyFetcher

log = logging.getLogger(__name__)

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

def _fetch_candidates(url: str) -> list[str]:
    page = StealthyFetcher.fetch(
        url,
        headless=True,
        real_chrome=True,
        network_idle=True,
        timeout=90000,
        wait=5000,
        block_webrtc=True,
        hide_canvas=True,
        load_dom=True,
        extra_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    
    html = str(page.body)
    candidates = set()

    for el in page.css("video[src], source[src], iframe[src], a[href]"):
        tag = el.attrib
        link = tag.get("src") or tag.get("href")
        if link:
            candidates.add(urljoin(url, link))

    for m in re.findall(r'https?://[^"\'<>\s]+(?:\.mp4|\.m3u8|\.mpd|\.webm)[^"\'<>\s]*', html, re.I):
        candidates.add(m)

    for m in re.findall(r'(?:file|src|source|url|hls|videoUrl|video_url)\s*[:=]\s*["\']([^"\']+)["\']', html, re.I):
        if any(x in m.lower() for x in [".mp4", ".m3u8", ".mpd", ".webm", "/e/", "embed"]):
            candidates.add(urljoin(url, m))

    valid = []
    for c in sorted(candidates):
        if _is_http_url(c) and not _is_ignored_url(c):
            valid.append(c)
            
    return valid

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
    
    status = await msg.reply_text("Scraping page...")
    
    try:
        candidates = await asyncio.to_thread(_fetch_candidates, url)
        if not candidates:
            return await status.edit_text("No candidates found.")
            
        out = []
        for i, c in enumerate(candidates, 1):
            out.append(f"Candidate {i}\n{c}\n")
            
        res = "\n".join(out).strip()
        
        if len(res) > 4000:
            file_path = "candidates.txt"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(res)
            with open(file_path, "rb") as f:
                await msg.reply_document(document=f)
            os.remove(file_path)
            await status.delete()
        else:
            await status.edit_text(res, disable_web_page_preview=True)
            
    except Exception as e:
        await status.edit_text(f"Scraper failed: {str(e)[:1000]}")
