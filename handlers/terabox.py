import os
import re
import html
import uuid
import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

from utils.config import SONZAIX_API_BASE
from utils.http import get_http_session
from handlers.dl.constants import TMP_DIR, MAX_TG_SIZE


def _pick_first(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k]:
            return d[k]
    return None


def _sanitize_filename(name: str, max_len: int = 80) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name[:max_len] or "file"


def _extract_files(obj):
    out = []

    def walk(x):
        if isinstance(x, dict):
            url = _pick_first(x, ["download", "download_url", "downloadUrl", "direct", "direct_url", "url", "link"])
            name = _pick_first(x, ["name", "filename", "file_name", "title"])
            size = _pick_first(x, ["size", "filesize", "file_size", "content_length"])
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                out.append({"name": str(name) if name else "File", "url": url, "size": size})
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(obj)

    seen = set()
    uniq = []
    for f in out:
        u = f["url"]
        if u in seen:
            continue
        seen.add(u)
        uniq.append(f)
    return uniq


async def _head_content_length(session, url: str) -> int:
    try:
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True) as r:
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl)
    except Exception:
        pass
    return 0


async def _download_to_file(session, url: str, path: str) -> int:
    size = 0
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=300), allow_redirects=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            async for chunk in r.content.iter_chunked(256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                size += len(chunk)
                if MAX_TG_SIZE and size > int(MAX_TG_SIZE):
                    raise RuntimeError("File too large (exceeds Telegram limit).")
    return size


async def terabox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "<b>Terabox Downloader</b>\n\n"
            "Usage:\n"
            "<code>/terabox &lt;url&gt; [password]</code>\n\n"
            "Example:\n"
            "<code>/terabox https://terabox.com/s/xxxx</code>\n"
            "<code>/terabox https://terabox.com/s/xxxx mypass</code>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    tb_url = context.args[0].strip()
    pwd = context.args[1].strip() if len(context.args) > 1 else ""

    os.makedirs(TMP_DIR, exist_ok=True)

    status = await msg.reply_text(
        "<b>Fetching Terabox info...</b>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    api_url = SONZAIX_API_BASE.rstrip("/") + "/terabox"
    session = await get_http_session()

    try:
        params = {"url": tb_url}
        if pwd:
            params["pwd"] = pwd

        async with session.get(api_url, params=params, timeout=aiohttp.ClientTimeout(total=25)) as r:
            if r.status != 200:
                return await status.edit_text(
                    f"<b>Failed to fetch data</b>\n\nHTTP <code>{r.status}</code>",
                    parse_mode="HTML",
                )
            data = await r.json(content_type=None)
    except Exception as e:
        return await status.edit_text(
            f"<b>Failed to contact API</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )

    files = _extract_files(data)
    if not files:
        return await status.edit_text(
            "<b>No downloadable files found.</b>\n\n"
            "Possible reasons:\n"
            "• The link is invalid/expired\n"
            "• The link requires a password\n"
            "• The API response format changed",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    pick = files[0]
    direct_url = pick["url"]
    filename = _sanitize_filename(pick.get("name") or "file")
    if not filename.lower().endswith((".mp4", ".mkv", ".webm", ".mp3", ".zip", ".rar", ".7z", ".pdf", ".jpg", ".jpeg", ".png", ".webp")):
        filename += ".bin"

    tmp_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{filename}")

    try:
        est = 0
        try:
            if pick.get("size"):
                est = int(pick["size"])
        except Exception:
            est = 0

        if not est:
            est = await _head_content_length(session, direct_url)

        if est and MAX_TG_SIZE and est > int(MAX_TG_SIZE):
            return await status.edit_text(
                "<b>File too large</b>\n"
                "This file exceeds Telegram upload limit.",
                parse_mode="HTML",
            )

        await status.edit_text(
            "<b>Downloading file...</b>",
            parse_mode="HTML",
        )

        await _download_to_file(session, direct_url, tmp_path)

        await status.edit_text(
            "<b>Uploading to Telegram...</b>",
            parse_mode="HTML",
        )

        await context.bot.send_document(
            chat_id=msg.chat_id,
            document=open(tmp_path, "rb"),
            filename=os.path.basename(tmp_path),
            caption=f"<b>Terabox Download</b>\n<code>{html.escape(filename)}</code>",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
            disable_notification=True,
        )

        try:
            await status.delete()
        except Exception:
            pass

    except Exception as e:
        try:
            await status.edit_text(
                f"<b>Failed</b>\n\n<code>{html.escape(str(e))}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass

    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass