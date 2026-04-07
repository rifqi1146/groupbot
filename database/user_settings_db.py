import time

from database.db import get_db

DEFAULT_SETTINGS = {
    "force_autodl": 0,
    "autodl_format": "ask",
    "youtube_resolution": 0,
    "music_format": "flac",
}


def init_user_settings_db():
    db = get_db()
    db.user_settings.create_index("user_id", unique=True)


def get_user_settings(user_id: int) -> dict:
    db = get_db()
    
    doc = db.user_settings.find_one({"user_id": int(user_id)})
    
    if not doc:
        return dict(DEFAULT_SETTINGS)

    return {
        "force_autodl": doc.get("force_autodl", DEFAULT_SETTINGS["force_autodl"]),
        "autodl_format": doc.get("autodl_format", DEFAULT_SETTINGS["autodl_format"]),
        "youtube_resolution": doc.get("youtube_resolution", DEFAULT_SETTINGS["youtube_resolution"]),
        "music_format": doc.get("music_format", DEFAULT_SETTINGS["music_format"]),
    }


def _update_setting(user_id: int, field_name: str, value):
    db = get_db()
    now = float(time.time())
    
    set_on_insert = {k: v for k, v in DEFAULT_SETTINGS.items() if k != field_name}
    
    db.user_settings.update_one(
        {"user_id": int(user_id)},
        {
            "$set": {field_name: value, "updated_at": now},
            "$setOnInsert": set_on_insert
        },
        upsert=True
    )


def set_force_autodl(user_id: int, enabled: bool):
    val = 1 if enabled else 0
    _update_setting(user_id, "force_autodl", val)


def set_autodl_format(user_id: int, value: str):
    val = str(value or "ask").lower().strip()
    if val not in ("ask", "video", "mp3"):
        val = "ask"
    
    _update_setting(user_id, "autodl_format", val)


def set_youtube_resolution(user_id: int, value: int):
    try:
        val = int(value)
    except Exception:
        val = 0

    if val not in (0, 360, 480, 720, 1080):
        val = 0

    _update_setting(user_id, "youtube_resolution", val)


def set_music_format(user_id: int, value: str):
    val = str(value or "flac").lower().strip()
    if val not in ("flac", "mp3"):
        val = "flac"

    _update_setting(user_id, "music_format", val)