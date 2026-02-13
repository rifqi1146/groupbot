import shutil
import subprocess
import asyncio
from .constants import COOKIES_PATH

def _probe_resolutions_sync(url: str) -> list[dict]:
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        return []

    cmd = [
        YT_DLP,
        "--cookies", COOKIES_PATH,
        "--no-playlist",
        "-J",
        url,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return []

    try:
        info = __import__("json").loads(p.stdout)
    except Exception:
        return []

    formats = info.get("formats") or []
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

        pick = {
            "height": h,
            "format_id": fid,
            "ext": ext,
            "has_audio": acodec != "none",
            "filesize": filesize,
        }

        cur = by_h.get(h)
        if not cur:
            by_h[h] = pick
            continue

        cur_size = int(cur.get("filesize") or 0)
        if pick["filesize"] and (not cur_size or pick["filesize"] < cur_size):
            by_h[h] = pick

    out = list(by_h.values())
    out.sort(key=lambda x: int(x.get("height") or 0), reverse=True)
    return out

async def get_resolutions(url: str) -> list[dict]:
    return await asyncio.to_thread(_probe_resolutions_sync, url)