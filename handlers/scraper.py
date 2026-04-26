import os
import socket
import shutil
import asyncio
import logging
import tempfile
import subprocess
import ipaddress
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

SCRAPLING_BIN = os.getenv("SCRAPLING_BIN") or shutil.which("scrapling")
SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "120"))

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

def _fetch_candidates(url: str) -> tuple[list[str], str]:
    if not SCRAPLING_BIN:
        raise RuntimeError("scrapling binary not found. Install scrapling or set SCRAPLING_BIN.")

    with tempfile.TemporaryDirectory(prefix="scrapling_") as tmpdir:
        out_path = Path(tmpdir) / "scrapling.md"

        result = subprocess.run(
            [
                SCRAPLING_BIN,
                "extract",
                "stealthy-fetch",
                url,
                str(out_path),
            ],
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

        logs = [log_text] if log_text else []
        return logs, md_text

async def _send_text_document(msg, text: str, filename: str):
    data = BytesIO((text or "").encode("utf-8", errors="ignore"))
    data.name = filename
    data.seek(0)
    await msg.reply_document(document=data, filename=filename)

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
        logs, md_text = await asyncio.to_thread(_fetch_candidates, url)

        if logs:
            log_text = "\n".join(logs).strip()
            if len(log_text) > 4000:
                await _send_text_document(msg, log_text, "scrapling-log.txt")
            else:
                await status.edit_text(log_text)
        else:
            await status.edit_text("Scrapling extract finished.")

        await _send_text_document(msg, md_text, "scrapling.md")

        try:
            await status.delete()
        except Exception:
            pass

    except subprocess.TimeoutExpired:
        await status.edit_text(f"Scraper failed: timeout after {SCRAPER_TIMEOUT}s")
    except Exception as e:
        log.exception("scraper_cmd failed")
        await status.edit_text(f"Scraper failed: {str(e)[:1000]}")