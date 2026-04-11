import shutil
import subprocess
import asyncio
import json

from .constants import COOKIES_PATH, MAX_TG_SIZE
from .youtube_api import is_youtube_url, sonzai_get_resolutions


def _pick_bestaudio_size(formats: list[dict]) -> int:
    best = None
    best_abr = -1.0

    for f in formats:
        vcodec = str(f.get("vcodec") or "")
        acodec = str(f.get("acodec") or "")

        if vcodec != "none":
            continue
        if acodec == "none":
            continue

        abr = f.get("abr")
        try:
            abr = float(abr) if abr is not None else 0.0
        except Exception:
            abr = 0.0

        if abr >= best_abr:
            best_abr = abr
            best = f

    if not best:
        return 0

    size = best.get("filesize") or best.get("filesize_approx") or 0
    try:
        return int(size) if size else 0
    except Exception:
        return 0


def _probe_resolutions_sync(url: str) -> list[dict]:
    yt_dlp_bin = shutil.which("yt-dlp")
    if not yt_dlp_bin:
        return []

    cmd = [
        yt_dlp_bin,
        "--cookies",
        COOKIES_PATH,
        "--no-playlist",
        "-J",
        url,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return []

    try:
        info = json.loads(p.stdout)
    except Exception:
        return []

    formats = info.get("formats") or []
    if not isinstance(formats, list):
        return []

    bestaudio_size = _pick_bestaudio_size(formats)

    grouped: dict[int, list[dict]] = {}

    for f in formats:
        if str(f.get("vcodec") or "") == "none":
            continue

        height = f.get("height")
        format_id = f.get("format_id")
        if not height or not format_id:
            continue

        try:
            height = int(height)
        except Exception:
            continue

        filesize = f.get("filesize") or f.get("filesize_approx") or 0
        try:
            filesize = int(filesize) if filesize else 0
        except Exception:
            filesize = 0

        acodec = str(f.get("acodec") or "")
        has_audio = acodec != "none"
        total_size = filesize if has_audio else (filesize + bestaudio_size if filesize else 0)

        if total_size and total_size > MAX_TG_SIZE:
            continue

        item = {
            "height": height,
            "format_id": str(format_id),
            "ext": str(f.get("ext") or ""),
            "has_audio": has_audio,
            "filesize": filesize,
            "total_size": total_size,
        }
        grouped.setdefault(height, []).append(item)

    def _score(item: dict):
        ext = (item.get("ext") or "").lower()
        return (
            1 if item.get("has_audio") else 0,
            1 if ext == "mp4" else 0,
            int(item.get("total_size") or 0),
            int(item.get("filesize") or 0),
        )

    out = []
    for height, items in grouped.items():
        best = max(items, key=_score)
        out.append(best)

    out.sort(key=lambda x: x["height"], reverse=True)
    return out


async def get_resolutions(url: str, engine: str | None = None) -> list[dict]:
    if not is_youtube_url(url):
        return await asyncio.to_thread(_probe_resolutions_sync, url)

    chosen = (engine or "").strip().lower()

    if chosen == "sonzai":
        try:
            return await sonzai_get_resolutions(url)
        except Exception:
            return []

    if chosen == "ytdlp":
        return await asyncio.to_thread(_probe_resolutions_sync, url)

    try:
        res = await asyncio.to_thread(_probe_resolutions_sync, url)
        if res:
            return res
    except Exception:
        pass

    try:
        return await sonzai_get_resolutions(url)
    except Exception:
        return []
        