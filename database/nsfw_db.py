import time

from database.db import get_db

def nsfw_db_init():
    db = get_db()
    db.nsfw_groups.create_index("chat_id", unique=True)


def is_nsfw_allowed(chat_id: int, chat_type: str) -> bool:
    if chat_type == "private":
        return True

    db = get_db()
    doc = db.nsfw_groups.find_one(
        {"chat_id": int(chat_id), "enabled": 1}, 
        {"_id": 1}
    )
    return doc is not None


def set_nsfw(chat_id: int, enabled: bool):
    db = get_db()
    now = time.time()
    
    db.nsfw_groups.update_one(
        {"chat_id": int(chat_id)},
        {"$set": {
            "enabled": 1 if enabled else 0,
            "updated_at": now
        }},
        upsert=True
    )


def get_all_enabled() -> list[int]:
    db = get_db()
    
    cursor = db.nsfw_groups.find({"enabled": 1}, {"chat_id": 1})
    
    return [int(doc["chat_id"]) for doc in cursor if "chat_id" in doc]