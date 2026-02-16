import os
import uuid
import asyncio
import shutil
import subprocess
from urllib.parse import urlparse

import aiohttp

from .constants import COOKIES_PATH, TMP_DIR
from .utils import progress_bar

_SIZE_100MB = 100 * 1024 * 1024


def _is_instagram(url: str) -> bool:
    try:
        h = (urlparse((url or "").strip()).hostname or "").lower()
        return h == "instagram.com" or h.endswith(".instagram.com")
    except Exception:
        return "instagram.com" in (url or "").lower()


def _probe_ig_image_url_sync(url: str) -> str:
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        return ""

    cmd = [
        YT_DLP,
        "--cookies", COOKIES_PATH,
        "--no-playlist",
        "-J",
        url,
    ]

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return ""

    try:
        info = __import__("json").loads(p.stdout)
    except Exception:
        return ""

    def pick_best_thumb(obj: dict) -> str:
        thumbs = obj.get("thumbnails") or []
        if thumbs:
            def score(t):
                w = int(t.get("width") or 0)
                h = int(t.get("height") or 0)
                pref = int(t.get("preference") or 0)
                return (w * h, pref)
            thumbs = sorted(thumbs, key=score, reverse=True)
            u = (thumbs[0].get("url") or "").strip()
            if u.startswith("http"):
                return u
        return ""

    if info.get("_type") == "playlist" and info.get("entries"):
        for e in info["entries"]:
            if isinstance(e, dict):
                u = pick_best_thumb(e)
                if u:
                    return u
        return ""

    if isinstance(info, dict):
        return pick_best_thumb(info)

    return ""


async def _download_url_to_file(url: str, out_path: str) -> bool:
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (TelegramBot)"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as r:
                if r.status != 200:
                    return False
                with open(out_path, "wb") as f:
                    async for chunk in r.content.iter_chunked(256 * 1024):
                        f.write(chunk)
        return True
    except Exception:
        return False


def _probe_total_size_sync(url: str, fmt: str) -> int:
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        return 0

    cmd = [
        YT_DLP,
        "--cookies", COOKIES_PATH,
        "--no-playlist",
        "-J",
        "-f", fmt,
        url,
    ]

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return 0

    try:
        info = __import__("json").loads(p.stdout)
    except Exception:
        return 0

    total = info.get("filesize") or info.get("filesize_approx") or 0
    try:
        total = int(total) if total else 0
    except Exception:
        total = 0

    if total:
        return total

    req = info.get("requested_downloads") or []
    s = 0
    for d in req:
        fs = d.get("filesize") or d.get("filesize_approx") or 0
        try:
            fs = int(fs) if fs else 0
        except Exception:
            fs = 0
        s += fs
    return s


async def ytdlp_download(
    url,
    fmt_key,
    bot,
    chat_id,
    status_msg_id,
    format_id: str | None = None,
    has_audio: bool = False,
):
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        raise RuntimeError("yt-dlp not found in PATH")

    out_tpl = f"{TMP_DIR}/%(title)s.%(ext)s"

    update_interval = 3

    async def run(cmd):
        nonlocal update_interval

        print("\n[YTDLP CMD]")
        print(" ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        last_edit = 0
        last_pct = -1

        while True:
            line = await proc.stdout.readline()
            if not line:
                break

            raw = line.decode(errors="ignore").strip()
            print("[YTDLP STDOUT]", raw)

            if "|" not in raw:
                continue

            head = raw.split("|", 1)[0].replace("%", "")
            if not head.replace(".", "", 1).isdigit():
                continue

            pct = float(head)
            if pct <= last_pct:
                continue
            last_pct = pct

            now = __import__("time").time()
            if now - last_edit >= update_interval:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=(
                            "<b>Downloading...</b>\n\n"
                            f"<code>{progress_bar(pct)}</code>"
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    print("[TG EDIT ERROR]", e)

                last_edit = now

        stdout, stderr = await proc.communicate()

        if stdout:
            print("\n[YTDLP STDOUT REMAIN]")
            print(stdout.decode(errors="ignore"))

        if stderr:
            print("\n[YTDLP STDERR]")
            print(stderr.decode(errors="ignore"))

        print("[YTDLP EXIT CODE]", proc.returncode)
        return proc.returncode

    if fmt_key == "mp3":
        update_interval = 3
        code = await run(
            [
                YT_DLP,
                "--cookies", COOKIES_PATH,
                "--js-runtimes", "deno:/root/.deno/bin/deno",
                "--no-playlist",
                "-f", "bestaudio/best",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--newline",
                "--progress-template", "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
                "-o", out_tpl,
                url,
            ]
        )
        if code != 0:
            return None
    else:
        if format_id:
            if has_audio:
                fmt = format_id
            else:
                fmt = f"{format_id}+bestaudio/best"
        else:
            fmt = "bestvideo*+bestaudio/best"

        est_size = await asyncio.to_thread(_probe_total_size_sync, url, fmt)
        update_interval = 7 if (est_size and est_size >= _SIZE_100MB) else 3

        code = await run(
            [
                YT_DLP,
                "--cookies", COOKIES_PATH,
                "--js-runtimes", "deno:/root/.deno/bin/deno",
                "--no-playlist",
                "-f", fmt,
                "--merge-output-format", "mp4",
                "--newline",
                "--progress-template", "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
                "-o", out_tpl,
                url,
            ]
        )

        if code != 0:
            print("[YTDLP] video failed → trying bestimage")
            update_interval = 3
            code = await run(
                [
                    YT_DLP,
                    "--cookies", COOKIES_PATH,
                    "--no-playlist",
                    "-f", "bestimage",
                    "-o", out_tpl,
                    url,
                ]
            )
            if code != 0:
                if _is_instagram(url):
                    img_url = await asyncio.to_thread(_probe_ig_image_url_sync, url)
                    if img_url:
                        os.makedirs(TMP_DIR, exist_ok=True)
                        out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}.jpg")
                        ok = await _download_url_to_file(img_url, out_path)
                        if ok:
                            return out_path
                return None

    def media_priority(p):
        p = p.lower()
        if p.endswith(".mp4"):
            return 0
        if p.endswith(".mp3"):
            return 1
        if p.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return 2
        return 9

    files = sorted(
        (
            os.path.join(TMP_DIR, f)
            for f in os.listdir(TMP_DIR)
            if f.lower().endswith((".mp4", ".mp3", ".jpg", ".jpeg", ".png", ".webp"))
        ),
        key=lambda p: (media_priority(p), -os.path.getmtime(p)),
    )

    print("[YTDLP OUTPUT FILES]", files)
    return files[0] if files else None