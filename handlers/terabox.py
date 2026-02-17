import os
import re
import uuid
import html
import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR


SONZAIX_BASE = "https://api.sonzaix.indevs.in"


def _safe_name(name: str, max_len: int = 80) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return (name[:max_len] or "file").strip()


def _pick_files(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    for k in ("files", "result", "data", "items", "list"):
        v = payload.get(k)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            for kk in ("files", "items", "list", "result"):
                vv = v.get(kk)
                if isinstance(vv, list):
                    return [x for x in vv if isinstance(x, dict)]
    return []


def _pick_download_url(item: dict) -> str:
    for k in ("download", "download_url", "downloadUrl", "dlink", "url", "link", "direct", "direct_url"):
        v = item.get(k)
        if isinstance(v, str) and v.startswith(("http://", "https://")):
            return v
    return ""


def _pick_filename(item: dict) -> str:
    for k in ("filename", "name", "title", "file_name"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "file"


def _pick_size(item: dict) -> int:
    for k in ("size", "filesize", "file_size"):
        v = item.get(k)
        try:
            return int(v)
        except Exception:
            pass
    return 0


async def _download_to_path(session: aiohttp.ClientSession, url: str, out_path: str) -> None:
    headers = {"User-Agent": "Mozilla/5.0 (TelegramBot)"}
    async with session.get(url, headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=120)) as r:
        if r.status != 200:
            raise RuntimeError(f"Download failed (HTTP {r.status})")

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        with open(out_path, "wb") as f:
            async for chunk in r.content.iter_chunked(256 * 1024):
                if chunk:
                    f.write(chunk)

    if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
        raise RuntimeError("Downloaded file is missing or empty")


async def terabox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "<b>TeraBox Downloader</b>\n\n"
            "Usage:\n"
            "<code>/terabox &lt;url&gt;</code>\n"
            "<code>/terabox &lt;url&gt; &lt;password&gt;</code>",
            parse_mode="HTML",
        )

    url = (context.args[0] or "").strip()
    pwd = (context.args[1] or "").strip() if len(context.args) > 1 else ""

    status = await msg.reply_text("<b>Fetching TeraBox data...</b>", parse_mode="HTML")

    session = await get_http_session()

    try:
        async with session.get(
            f"{SONZAIX_BASE}/terabox",
            params={"url": url, "pwd": pwd} if pwd else {"url": url},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            if r.status != 200:
                return await status.edit_text(f"<b>API error</b>: HTTP {r.status}", parse_mode="HTML")

            data = await r.json()

        files = _pick_files(data)
        if not files:
            keys = ", ".join(sorted(data.keys())) if isinstance(data, dict) else type(data).__name__
            return await status.edit_text(
                "<b>No files found.</b>\n\n"
                f"<code>Top-level: {html.escape(keys)}</code>",
                parse_mode="HTML",
            )

        files.sort(key=_pick_size, reverse=True)
        item = files[0]

        dl_url = _pick_download_url(item)
        if not dl_url:
            return await status.edit_text(
                "<b>No downloadable URL found in API response.</b>\n\n"
                f"<code>Item keys: {html.escape(', '.join(sorted(item.keys())))}</code>",
                parse_mode="HTML",
            )

        filename = _safe_name(_pick_filename(item))
        ext = os.path.splitext(filename)[1].lower()
        if not ext:
            ext = ".bin"

        out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{filename}")

        await status.edit_text("<b>Downloading file...</b>", parse_mode="HTML")
        await _download_to_path(session, dl_url, out_path)

        await context.bot.send_document(
            chat_id=msg.chat_id,
            document=open(out_path, "rb"),
            caption=f"<b>Downloaded:</b> {html.escape(filename)}",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )

        try:
            os.remove(out_path)
        except Exception:
            pass

        await status.delete()

    except Exception as e:
        return await status.edit_text(
            f"<b>Failed:</b> <code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )