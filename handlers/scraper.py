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

log = logging.getLogger(__name__)

TMP_DIR = os.getenv("TMP_DIR", "downloads")
SCRAPLING_BIN = os.getenv("SCRAPLING_BIN") or shutil.which("scrapling")
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "60"))
SCRAPER_IFRAME_DOMAINS = tuple(
    x.strip().lower()
    for x in os.getenv("SCRAPER_IFRAME_DOMAINS", "nozstream.site").split(",")
    if x.strip()
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

def _extract_iframe_srcs(raw_html: str, base_url: str) -> list[str]:
    found = []
    pattern = r"<iframe\b[^>]*\bsrc\s*=\s*(['\"])(.*?)\1"
    for m in re.finditer(pattern, raw_html or "", flags=re.I | re.S):
        src = html.unescape((m.group(2) or "").strip())
        if not src or src.lower().startswith(("javascript:", "data:")):
            continue
        abs_url = urljoin(base_url, src)
        if abs_url not in found:
            found.append(abs_url)
    return found

def _pick_target_iframe(srcs: list[str]) -> str | None:
    for src in srcs:
        host = _host(src)
        if any(_host_match(host, d) for d in SCRAPER_IFRAME_DOMAINS):
            return src
    return srcs[0] if srcs else None

async def _send_html_result(msg, status, out_path: str, src_count: int):
    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    await status.edit_text(
        f"No iframe link found.\n\nSending HTML file instead...\nFound iframe count: <code>{src_count}</code>\nSize: <code>{size} bytes</code>",
        parse_mode="HTML",
    )
    with open(out_path, "rb") as f:
        await msg.reply_document(
            document=f,
            filename=os.path.basename(out_path),
            caption="HTML scraper result",
        )
        
async def _run_scrapling(url: str, out_path: str):
    if not SCRAPLING_BIN:
        raise RuntimeError("scrapling binary not found. Install it or set SCRAPLING_BIN.")
    cmd = [SCRAPLING_BIN, "extract", "stealthy-fetch", url, out_path]
    log.info("Scraper start | url=%s out=%s", url, out_path)
    log.info("Scraper command | %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
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
    os.makedirs(TMP_DIR, exist_ok=True)
    out_path = os.path.join(TMP_DIR, f"scraper_{uuid.uuid4().hex}.html")
    started = time.monotonic()
    status = await msg.reply_text("🕷️ <b>Scraping page...</b>", parse_mode="HTML")
    try:
        await _run_scrapling(url, out_path)
        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
        srcs = _extract_iframe_srcs(raw, url)
        picked = _pick_target_iframe(srcs)
        if not picked:
            return await _send_html_result(msg, status, out_path, len(srcs))
        elapsed = time.monotonic() - started
        text = (
            "<b>Iframe found</b>\n\n"
            f"<code>{html.escape(picked)}</code>\n\n"
            f"Time <i>{elapsed:.2f}s</i>"
        )
        await status.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        err = html.escape((str(e) or repr(e)).strip())[:3500]
        await status.edit_text(f"<b>Scraper failed</b>\n\n<code>{err}</code>", parse_mode="HTML")
    finally:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
                log.info("Scraper temp deleted | file=%s", out_path)
        except Exception as e:
            log.warning("Failed to delete scraper temp | file=%s err=%r", out_path, e)