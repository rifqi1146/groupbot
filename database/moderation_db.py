import time

from database.db import get_db

def init_moderation_db():
    db = get_db()
    db.moderation_groups.create_index("chat_id", unique=True)


def init_sudo_db():
    db = get_db()
    db.sudo_users.create_index("user_id", unique=True)


def init_moderation_storage():
    init_moderation_db()
    init_sudo_db()
    
    db = get_db()
    db.broadcast_user_cache.create_index("username")


def moderation_is_enabled(chat_id: int) -> bool:
    db = get_db()
    doc = db.moderation_groups.find_one({"chat_id": int(chat_id)}, {"enabled": 1})
    return bool(doc and doc.get("enabled", 0) == 1)


def moderation_set(chat_id: int, enabled: bool):
    db = get_db()
    now = float(time.time())
    
    db.moderation_groups.update_one(
        {"chat_id": int(chat_id)},
        {"$set": {
            "enabled": 1 if enabled else 0,
            "updated_at": now
        }},
        upsert=True
    )


def sudo_is(user_id: int) -> bool:
    db = get_db()
    doc = db.sudo_users.find_one({"user_id": int(user_id)}, {"_id": 1})
    return bool(doc)


def sudo_add(user_id: int):
    db = get_db()
    now = float(time.time())

    db.sudo_users.update_one(
        {"user_id": int(user_id)},
        {"$set": {"added_at": now}},
        upsert=True
    )


def sudo_remove(user_id: int):
    db = get_db()
    db.sudo_users.delete_one({"user_id": int(user_id)})


def sudo_list() -> list[int]:
    db = get_db()
    cursor = db.sudo_users.find({}, {"user_id": 1}).sort("added_at", 1)
    return [int(doc["user_id"]) for doc in cursor if "user_id" in doc]


def lookup_user_id(username: str) -> int | None:
    u = (username or "").strip().lstrip("@").lower()
    if not u:
        return None

    db = get_db()
    try:
        doc = db.broadcast_user_cache.find_one({"username": u}, {"user_id": 1})
        return int(doc["user_id"]) if doc and "user_id" in doc else None
    except Exception:
        return None