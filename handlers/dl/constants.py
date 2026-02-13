import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(BASE_DIR, "..", "..", "data", "cookies.txt")

TMP_DIR = "downloads"
AUTO_DL_DB = "data/auto_dl.sqlite3"

MAX_TG_SIZE = 1900 * 1024 * 1024

DL_FORMATS = {
    "video": {"label": "🎥 Video"},
    "mp3": {"label": "🎵 MP3"},
}

PREMIUM_ONLY_DOMAINS = {
    "pornhub.com",
    "xnxx.com",
    "redtube.com",
}

AUTO_DOWNLOAD_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
    "tiktok.com",
    "vt.tiktok.com",
    "vm.tiktok.com",
    "instagram.com",
    "instagr.am",
    "facebook.com",
    "fb.watch",
    "fb.com",
    "m.facebook.com",
    "twitter.com",
    "x.com",
    "reddit.com",
    "redd.it",
}