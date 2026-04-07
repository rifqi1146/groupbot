import os
import uuid
import asyncio
import shutil
import json
import subprocess
from urllib.parse import urlparse

from .instagram_api import is_instagram_url
from .constants import COOKIES_PATH, TMP_DIR
from .utils import progress_bar

_SIZE_100MB = 100 * 1024 * 1024

def _extract_title_from_path(path: str, prefix: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    if base.startswith(prefix + "_"):
        base = base[len(prefix) + 1:]
    return base.strip() or "Media"
    
def _looks_like_media_id(text: str) -> bool:
    s = (text or "").strip()
    return bool(s) and len(s) >= 8 and s.isdigit()

def is_x_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
        return host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com")
    except Exception:
        text = (url or "").lower()
        return "x.com/" in text or "twitter.com/" in text

def _fallback_title_from_url(url: str) -> str:
    try:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").strip("/")
        parts = [x for x in path.split("/") if x]

        if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
            return "X Media"

        if len(parts) >= 2 and parts[0] in ("p", "reel", "reels", "tv"):
            kind = parts[0]
            if kind in ("reel", "reels"):
                return "Instagram Reel"
            if kind == "p":
                return "Instagram Post"
            if kind == "tv":
                return "Instagram TV"

        if len(parts) >= 3 and parts[0] == "stories":
            return f"Instagram Story @{parts[1]}"

        return "Media"
    except Exception:
        return "Media"


def title_gallerydl(path: str, prefix: str, url: str = "") -> str:
    title = _extract_title_from_path(path, prefix)
    title = title.replace("_", " ").strip(" -_.")

    if title and not _looks_like_media_id(title):
        return title

    parent = os.path.basename(os.path.dirname(path))
    parent = (parent or "").replace("_", " ").strip(" -_.")
    if parent and "gallerydl" not in parent.lower() and not _looks_like_media_id(parent):
        return parent

    return _fallback_title_from_url(url)
    
def _strip_job_prefix(path: str, prefix: str) -> str:
    try:
        base = os.path.basename(path)
        if not base.startswith(prefix + "_"):
            return path

        clean_name = base[len(prefix) + 1:]
        new_path = os.path.join(os.path.dirname(path), clean_name)

        if os.path.abspath(new_path) == os.path.abspath(path):
            return path

        if os.path.exists(new_path):
            stem, ext = os.path.splitext(clean_name)
            new_path = os.path.join(os.path.dirname(path), f"{stem}_{prefix}{ext}")

        os.rename(path, new_path)
        return new_path
    except Exception:
        return path
        
def _pick_latest_media_file(since_ts: float, prefix: str) -> str | None:
    exts = (".mp4", ".mp3", ".jpg", ".jpeg", ".png", ".webp")
    try:
        files = []
        for f in os.listdir(TMP_DIR):
            if not f.startswith(prefix + "_"):
                continue
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

def _collect_media_files_recursive(root_dir: str) -> list[str]:
    exts = (".mp4", ".mp3", ".jpg", ".jpeg", ".png", ".webp")
    files = []

    try:
        for root, _, names in os.walk(root_dir):
            for name in names:
                if not name.lower().endswith(exts):
                    continue
                p = os.path.join(root, name)
                if not os.path.isfile(p):
                    continue
                files.append(p)
    except Exception:
        return []

    files.sort(key=lambda p: os.path.getmtime(p))
    return files
        
async def gallerydl_fallback(
    url: str,
    job_id: str,
    bot,
    chat_id,
    status_msg_id,
    status_text: str = "<b>yt-dlp failed, fallback to gallery-dl...</b>",
):
    GALLERY_DL = shutil.which("gallery-dl")
    if not GALLERY_DL:
        print("[GALLERY-DL] not found in PATH")
        return None

    job_dir = os.path.join(TMP_DIR, f"{job_id}_gallerydl")
    os.makedirs(job_dir, exist_ok=True)

    try:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=status_text,
                parse_mode="HTML",
            )
        except Exception as e:
            print("[TG EDIT ERROR]", e)

        cmd = [GALLERY_DL]

        if COOKIES_PATH and os.path.exists(COOKIES_PATH):
            cmd += ["--cookies", COOKIES_PATH]

        cmd += [url]

        print("\n[GALLERY-DL CMD]")
        print(" ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=job_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if stdout:
            print("\n[GALLERY-DL STDOUT]")
            print(stdout.decode(errors="ignore"))

        if stderr:
            print("\n[GALLERY-DL STDERR]")
            print(stderr.decode(errors="ignore"))

        print("[GALLERY-DL EXIT CODE]", proc.returncode)

        if proc.returncode != 0:
            return None

        files = _collect_media_files_recursive(job_dir)
        if not files:
            print("[GALLERY-DL] no downloaded media file found")
            return None

        moved_items = []
        for src in files:
            final_name = f"{job_id}_{os.path.basename(src)}"
            final_path = os.path.join(TMP_DIR, final_name)

            if os.path.abspath(src) != os.path.abspath(final_path):
                if os.path.exists(final_path):
                    stem, ext = os.path.splitext(final_name)
                    final_path = os.path.join(TMP_DIR, f"{stem}_{uuid.uuid4().hex[:6]}{ext}")
                shutil.move(src, final_path)

            moved_items.append({
                "path": final_path,
                "title": title_gallerydl(final_path, job_id, url),
            })

        if len(moved_items) == 1:
            return moved_items[0]

        return {
            "items": moved_items,
            "title": _fallback_title_from_url(url),
        }

    except Exception as e:
        print("[GALLERY-DL FALLBACK ERROR]", e)
        return None
    finally:
        try:
            shutil.rmtree(job_dir, ignore_errors=True)
        except Exception:
            pass

def _probe_total_size_sync(url: str, fmt: str) -> int:
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        return 0

    cmd = [
        YT_DLP,
        "--cookies", COOKIES_PATH,
        "--extractor-args", "youtube:player_client=web",
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

def _extract_tool_error(stdout_text: str, stderr_text: str, code: int, tool_name: str = "yt-dlp") -> str:
    skip_starts = (
        "[download]",
        "[info]",
        "[debug]",
        "[generic]",
        "[redirect]",
        "[metadata]",
    )

    merged_lines = []
    if stderr_text:
        merged_lines.extend(stderr_text.splitlines())
    if stdout_text:
        merged_lines.extend(stdout_text.splitlines())

    for raw in reversed(merged_lines):
        line = (raw or "").strip()
        if not line:
            continue

        lower = line.lower()

        if lower.startswith(skip_starts):
            continue

        if "error:" in lower:
            idx = lower.rfind("error:")
            msg = line[idx + len("error:"):].strip()
            return msg or f"{tool_name} exited with code {code}"

        if any(key in lower for key in (
            "unsupported url",
            "unable to extract",
            "video unavailable",
            "private video",
            "sign in to confirm",
            "requested format is not available",
            "http error",
            "forbidden",
            "cloudflare",
            "login required",
            "members only",
            "429",
            "403",
        )):
            return line

    tail = [x.strip() for x in merged_lines if (x or "").strip()]
    if tail:
        return tail[-1][:700]

    return f"{tool_name} exited with code {code}"
    
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

    os.makedirs(TMP_DIR, exist_ok=True)

    job_id = uuid.uuid4().hex[:10]
    out_tpl = f"{TMP_DIR}/{job_id}_%(title)s.%(ext)s"
    update_interval = 3
    is_ig = is_instagram_url(url)
    is_x = is_x_url(url)

    async def run(cmd):
        nonlocal update_interval

        print("\n[YTDLP CMD]")
        print(" ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        last_edit = 0
        last_pct = -1
        stdout_lines = []

        while True:
            line = await proc.stdout.readline()
            if not line:
                break

            raw = line.decode(errors="ignore").strip()
            stdout_lines.append(raw)
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

        stdout_rest, stderr = await proc.communicate()

        stdout_text = "\n".join(stdout_lines)
        if stdout_rest:
            rest_text = stdout_rest.decode(errors="ignore")
            if rest_text:
                stdout_text = (stdout_text + "\n" + rest_text).strip() if stdout_text else rest_text

        stderr_text = stderr.decode(errors="ignore") if stderr else ""

        if stdout_text:
            print("\n[YTDLP STDOUT REMAIN]")
            print(stdout_text)

        if stderr_text:
            print("\n[YTDLP STDERR]")
            print(stderr_text)

        print("[YTDLP EXIT CODE]", proc.returncode)
        return proc.returncode, stdout_text, stderr_text

    start_ts = __import__("time").time()

    if fmt_key == "mp3":
        update_interval = 2
        cmd = [
            YT_DLP,
            "--cookies", COOKIES_PATH,
            "--js-runtimes", "deno:/root/.deno/bin/deno",
            "--extractor-args", "youtube:player_client=web",
            "--concurrent-fragments", "8",
            "--no-playlist",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "flac",
            "--audio-quality", "0",
            "--newline",
            "--progress-template", "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "-o", out_tpl,
            url,
        ]
        code, stdout_text, stderr_text = await run(cmd)
        if code != 0:
            raise RuntimeError(_extract_tool_error(stdout_text, stderr_text, code, "yt-dlp"))

    else:
        if is_x:
            fallback = await gallerydl_fallback(
                url=url,
                job_id=job_id,
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
                status_text="<b>Downloading with gallery-dl...</b>",
            )
            if fallback:
                return fallback

        if format_id:
            if has_audio:
                fmt = format_id
            else:
                fmt = f"{format_id}+bestaudio/best"
        else:
            fmt = "bestvideo*+bestaudio/best"

        est_size = await asyncio.to_thread(_probe_total_size_sync, url, fmt)
        update_interval = 7 if (est_size and est_size >= _SIZE_100MB) else 2

        cmd = [
            YT_DLP,
            "--cookies", COOKIES_PATH,
            "--js-runtimes", "deno:/root/.deno/bin/deno",
            "--extractor-args", "youtube:player_client=web",
            "--concurrent-fragments", "8",
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

        code, stdout_text, stderr_text = await run(cmd)
        yt_error = _extract_tool_error(stdout_text, stderr_text, code, "yt-dlp")

        if code != 0:
            if is_ig:
                picked = _pick_latest_media_file(start_ts, job_id)
                if picked:
                    return {
                        "path": picked,
                        "title": _extract_title_from_path(picked, job_id),
                    }

            print("[YTDLP] video failed → trying gallery-dl fallback")

            fallback = await gallerydl_fallback(
                url=url,
                job_id=job_id,
                bot=bot,
                chat_id=chat_id,
                status_msg_id=status_msg_id,
            )

            if fallback:
                return fallback

            if is_ig:
                picked = _pick_latest_media_file(start_ts, job_id)
                if picked:
                    return {
                        "path": picked,
                        "title": _extract_title_from_path(picked, job_id),
                    }

            raise RuntimeError(yt_error)

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
            if f.startswith(job_id + "_")
            and f.lower().endswith((".mp4", ".mp3", ".jpg", ".flac", ".jpeg", ".png", ".webp"))
        ),
        key=lambda p: (media_priority(p), -os.path.getmtime(p)),
    )

    print("[YTDLP OUTPUT FILES]", files)
    if not files:
        raise RuntimeError("yt-dlp selesai tapi file output tidak ditemukan")

    picked = files[0]
    title = title_gallerydl(picked, job_id, url)
    final_path = _strip_job_prefix(picked, job_id)

    return {
        "path": final_path,
        "title": title,
    }