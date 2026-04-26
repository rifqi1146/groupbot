import os
import re
import socket
import shutil
import asyncio
import logging
import tempfile
import subprocess
import ipaddress
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, urljoin
from telegram import Update
from telegram.ext import ContextTypes
from scrapling.fetchers import StealthyFetcher

log = logging.getLogger(__name__)

SCRAPLING_BIN = os.getenv("SCRAPLING_BIN") or shutil.which("scrapling")
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "120"))

SCRAPER_IGNORE_DOMAINS = tuple(
    x.strip().lower()
    for x in os.getenv(
        "SCRAPER_IGNORE_DOMAINS",
        "googletagmanager.com,google.com,doubleclick.net,googlesyndication.com,facebook.com,analytics.google.com,google-analytics.com"
    ).split(",")
    if x.strip()
)

CHALLENGE_SIGNS = (
    "SafeLine WAF",
    "Client Verifying",
    "SafeLineChallenge",
    "waf.chaitin.com/challenge",
    "/cdn-cgi/challenge-platform",
    "cf-challenge",
    "cf-turnstile",
    "challenges.cloudflare.com",
    "Just a moment",
    "Checking your browser",
    "DDoS-Guard",
    "ddos-guard",
    "Incapsula",
    "Imperva",
    "_Incapsula_Resource",
    "AkamaiGHost",
    "akamai bot manager",
    "Bot Management",
    "DataDome",
    "datadome",
    "PerimeterX",
    "px-captcha",
    "hcaptcha",
    "g-recaptcha",
)

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
        return (
            obj.is_private
            or obj.is_loopback
            or obj.is_link_local
            or obj.is_multicast
            or obj.is_reserved
            or obj.is_unspecified
        )
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

def _decode(data: bytes) -> str:
    return (data or b"").decode("utf-8", errors="ignore").strip()

def _body_to_text(body) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="ignore")
    return str(body)

def _safe_title(page) -> str:
    try:
        return page.css("title::text").get() or ""
    except Exception:
        return ""

def _detect_challenge(html: str) -> tuple[bool, list[str]]:
    found = []
    low = html.lower()
    for sign in CHALLENGE_SIGNS:
        if sign.lower() in low:
            found.append(sign)
    return bool(found), found

def _run_scrapling_extract(url: str) -> tuple[str, str]:
    if not SCRAPLING_BIN:
        raise RuntimeError("scrapling binary not found. Install scrapling or set SCRAPLING_BIN.")

    with tempfile.TemporaryDirectory(prefix="scrapling_extract_") as tmpdir:
        out_path = Path(tmpdir) / "scrapling.md"

        result = subprocess.run(
            [SCRAPLING_BIN, "extract", "stealthy-fetch", url, str(out_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SCRAPER_TIMEOUT,
        )

        stdout = _decode(result.stdout)
        stderr = _decode(result.stderr)
        log_text = "\n".join(x for x in [stdout, stderr] if x).strip()

        if result.returncode != 0:
            raise RuntimeError(log_text or f"scrapling failed with exit code {result.returncode}")

        if not out_path.exists():
            raise RuntimeError(log_text or "scrapling finished but output file not found")

        md_text = out_path.read_text(encoding="utf-8", errors="ignore")

        if not md_text.strip():
            raise RuntimeError(log_text or "scrapling output is empty")

        return md_text, log_text

def _fetch_candidates(url: str) -> tuple[list[str], str, dict]:
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
        extra_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
        },
    )

    html = _body_to_text(page.body)
    final_url = getattr(page, "url", None) or url
    status = getattr(page, "status", None)
    title = _safe_title(page)
    still_challenge, challenge_found = _detect_challenge(html)
    candidates = set()

    for el in page.css("video[src], source[src], iframe[src], a[href]"):
        tag = el.attrib
        link = tag.get("src") or tag.get("href")
        if link:
            candidates.add(urljoin(final_url, link))

    for m in re.findall(r'https?://[^"\'<>\s]+(?:\.mp4|\.m3u8|\.mpd|\.webm)[^"\'<>\s]*', html, re.I):
        candidates.add(m)

    for m in re.findall(r'(?:file|src|source|url|hls|videoUrl|video_url)\s*[:=]\s*["\']([^"\']+)["\']', html, re.I):
        if any(x in m.lower() for x in [".mp4", ".m3u8", ".mpd", ".webm", "/e/", "embed"]):
            candidates.add(urljoin(final_url, m))

    valid = []
    for c in sorted(candidates):
        if _is_http_url(c) and not _is_ignored_url(c):
            valid.append(c)

    meta = {
        "status": status,
        "url": final_url,
        "title": title,
        "still_challenge": still_challenge,
        "challenge_found": challenge_found,
    }

    return valid, html, meta

async def _send_text_document(msg, text: str, filename: str):
    data = BytesIO((text or "").encode("utf-8", errors="ignore"))
    data.name = filename
    data.seek(0)
    await msg.reply_document(document=data, filename=filename)

def _format_candidates(candidates: list[str]) -> str:
    out = []
    for i, c in enumerate(candidates, 1):
        out.append(f"Candidate {i}\n{c}\n")
    return "\n".join(out).strip()

def _format_meta(meta: dict, log_text: str, candidates_count: int) -> str:
    challenge_found = meta.get("challenge_found") or []
    challenge_text = ", ".join(challenge_found) if challenge_found else "-"
    parts = [
        "Scrapling debug result",
        "",
        f"status: {meta.get('status')}",
        f"url: {meta.get('url')}",
        f"title: {meta.get('title') or '-'}",
        f"still_challenge: {meta.get('still_challenge')}",
        f"challenge_found: {challenge_text}",
        f"candidates: {candidates_count}",
    ]
    if log_text:
        parts.extend(["", "CLI log:", log_text])
    return "\n".join(parts).strip()

async def scraper_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "Example: <code>/scraper https://link.com</code>",
            parse_mode="HTML"
        )

    url = (context.args[0] or "").strip()

    if not _is_http_url(url):
        return await msg.reply_text("Invalid URL. Use http/https link.")

    if not await _is_safe_public_url(url):
        return await msg.reply_text("Blocked URL. Public http/https URL only.")

    status = await msg.reply_text("Running scrapling extract stealthy-fetch...")

    try:
        md_task = asyncio.to_thread(_run_scrapling_extract, url)
        debug_task = asyncio.to_thread(_fetch_candidates, url)

        md_text, log_text = await md_task
        candidates, debug_html, meta = await debug_task

        meta_text = _format_meta(meta, log_text, len(candidates))

        if len(meta_text) > 4000:
            await _send_text_document(msg, meta_text, "scrapling-log.txt")
            await status.edit_text("Scrapling finished.")
        else:
            await status.edit_text(meta_text, disable_web_page_preview=True)

        await _send_text_document(msg, md_text, "scrapling.md")
        await _send_text_document(msg, debug_html, "debug_page.html")

        if candidates:
            candidates_text = _format_candidates(candidates)
            if len(candidates_text) > 4000:
                await _send_text_document(msg, candidates_text, "candidates.txt")
            else:
                await msg.reply_text(candidates_text, disable_web_page_preview=True)

        try:
            await status.delete()
        except Exception:
            pass

    except subprocess.TimeoutExpired:
        await status.edit_text(f"Scraper failed: timeout after {SCRAPER_TIMEOUT}s")
    except Exception as e:
        log.exception("scraper_cmd failed")
        await status.edit_text(f"Scraper failed: {str(e)[:1000]}")