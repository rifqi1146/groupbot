import os
import uuid
import asyncio
import shutil
import subprocess
from urllib.parse import urlparse

from .constants import COOKIES_PATH, TMP_DIR
from .utils import progress_bar

_SIZE_100MB = 100 * 1024 * 1024


def _is_instagram(url: str) -> bool:
    try:
        h = (urlparse((url or "").strip()).hostname or "").lower()
        return h == "instagram.com" or h.endswith(".instagram.com")
    except Exception:
        return "instagram.com" in (url or "").lower()


def _pick_latest_media_file(since_ts: float) -> str | None:
    exts = (".mp4", ".mp3", ".jpg", ".jpeg", ".png", ".webp")
    try:
        files = []
        for f in os.listdir(TMP_DIR):
            p = os.path.join(TMP_DIR, f)
            if not os.path.isfile(p):
                continue
            if not f.lower().endswith(exts):
                continue
            try:
                mt = os.path.getmtime(p)
            except Exception:
                continue
            if mt >= since_ts - 1:
                files.append((mt, p))
        if not files:
            return None
        files.sort(key=lambda x: x[0], reverse=True)
        return files[0][1]
    except Exception:
        return None


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

    unique_id = uuid.uuid4().hex
    out_tpl = f"{TMP_DIR}/{unique_id}_%(title)s.%(ext)s"
    update_interval = 3
    is_ig = _is_instagram(url)

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

    start_ts = __import__("time").time()

    if fmt_key == "mp3":
        update_interval = 3
        cmd = [
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
        code = await run(cmd)
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

        cmd = [
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
        if is_ig:
            cmd.insert(1, "--ignore-errors")
            cmd.insert(2, "--no-abort-on-error")

        code = await run(cmd)

        if code != 0:
            if is_ig:
                picked = _pick_latest_media_file(start_ts)
                if picked:
                    return picked

            print("[YTDLP] video failed → trying bestimage")
            update_interval = 3

            cmd2 = [
                YT_DLP,
                "--cookies", COOKIES_PATH,
                "--no-playlist",
                "-f", "bestimage",
                "-o", out_tpl,
                url,
            ]
            if is_ig:
                cmd2.insert(1, "--ignore-errors")
                cmd2.insert(2, "--no-abort-on-error")

            code2 = await run(cmd2)

            if code2 != 0:
                if is_ig:
                    picked = _pick_latest_media_file(start_ts)
                    if picked:
                        return picked
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

    import glob

    pattern = os.path.join(TMP_DIR, f"{unique_id}_*")
    files = glob.glob(pattern)
    
    print("[YTDLP OUTPUT FILES]", files)
    return files[0] if files else None
    