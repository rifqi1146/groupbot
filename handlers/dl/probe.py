import shutil
import subprocess
import asyncio
import json

from .constants import COOKIES_PATH, MAX_TG_SIZE


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
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        return []

    cmd = [
        YT_DLP,
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
    bestaudio_size = _pick_bestaudio_size(formats)

    by_h: dict[int, dict] = {}

    for f in formats:
        h = f.get("height")
        if not h:
            continue

        try:
            h = int(h)
        except Exception:
            continue

        if h < 144 or h > 1080:
            continue

        vcodec = str(f.get("vcodec") or "")
        if vcodec == "none":
            continue

        fid = str(f.get("format_id") or "")
        if not fid:
            continue

        acodec = str(f.get("acodec") or "")
        ext = str(f.get("ext") or "")

        filesize = f.get("filesize") or f.get("filesize_approx") or 0
        try:
            filesize = int(filesize) if filesize else 0
        except Exception:
            filesize = 0

        has_audio = acodec != "none"
        total_size = 0
        if filesize:
            total_size = filesize if has_audio else (filesize + (bestaudio_size or 0))

        pick = {
            "height": h,
            "format_id": fid,
            "ext": ext,
            "has_audio": has_audio,
            "filesize": filesize,
            "total_size": total_size,
        }

        cur = by_h.get(h)
        if not cur:
            by_h[h] = pick
            continue

        cur_total = int(cur.get("total_size") or 0)
        if pick["total_size"] and (not cur_total or pick["total_size"] < cur_total):
            by_h[h] = pick
            continue

        cur_size = int(cur.get("filesize") or 0)
        if pick["filesize"] and (not cur_size or pick["filesize"] < cur_size):
            by_h[h] = pick

    out = list(by_h.values())
    out = [x for x in out if not x.get("total_size") or int(x["total_size"]) <= MAX_TG_SIZE]
    out.sort(key=lambda x: int(x.get("height") or 0), reverse=True)
    return out


async def get_resolutions(url: str) -> list[dict]:
    return await asyncio.to_thread(_probe_resolutions_sync, url)
    