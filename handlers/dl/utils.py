import os
import re
import subprocess

def progress_bar(percent: float, length: int = 12) -> str:
    try:
        p = max(0.0, min(100.0, float(percent)))
    except Exception:
        p = 0.0
    filled = int(round((p / 100.0) * length))
    empty = length - filled
    bar = "▰" * filled + "▱" * empty
    return f"{bar} {p:.1f}%"

def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name[:max_len] or "video"

def detect_media_type(path: str) -> str:
    ext = os.path.splitext(path.lower())[1]
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return "photo"
    if ext in (".mp4", ".mkv", ".webm"):
        return "video"
    return "unknown"

def normalize_url(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("\u200b", "")
    text = text.split("\n")[0]
    return text

def is_invalid_video(path: str) -> bool:
    try:
        p = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration,width,height",
                "-of", "json",
                path,
            ],
            capture_output=True,
            text=True,
        )
        info = __import__("json").loads(p.stdout)
        stream = info["streams"][0]

        duration = float(stream.get("duration", 0))
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))

        return duration < 1.5 or width == 0 or height == 0
    except Exception:
        return True