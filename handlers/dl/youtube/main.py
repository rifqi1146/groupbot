from urllib.parse import urlparse

def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
        return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    except Exception:
        text = (url or "").lower()
        return "youtu.be" in text or "youtube.com" in text