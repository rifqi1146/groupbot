import time
from pymongo import UpdateOne

from database.db import get_db

def init_welcome_db():
    db = get_db()
    db.welcome_chats.create_index("chat_id", unique=True)
    db.verified_users.create_index([("chat_id", 1), ("user_id", 1)], unique=True)
    db.pending_welcome.create_index([("chat_id", 1), ("user_id", 1)], unique=True)


def load_welcome_chats() -> set[int]:
    db = get_db()
    cursor = db.welcome_chats.find({"enabled": 1}, {"chat_id": 1})
    return {int(doc["chat_id"]) for doc in cursor if "chat_id" in doc}


def save_welcome_chats(enabled_chats: set[int]):
    db = get_db()
    now = time.time()
    
    db.welcome_chats.update_many({}, {"$set": {"enabled": 0, "updated_at": now}})
    
    if enabled_chats:
        operations = [
            UpdateOne(
                {"chat_id": int(cid)},
                {"$set": {"enabled": 1, "updated_at": now}},
                upsert=True
            )
            for cid in enabled_chats
        ]
        db.welcome_chats.bulk_write(operations)


def load_verified() -> dict[int, set[int]]:
    db = get_db()
    cursor = db.verified_users.find({}, {"chat_id": 1, "user_id": 1})
    
    out = {}
    for doc in cursor:
        if "chat_id" in doc and "user_id" in doc:
            out.setdefault(int(doc["chat_id"]), set()).add(int(doc["user_id"]))
            
    return out


def save_verified_user(chat_id: int, user_id: int):
    db = get_db()
    now = time.time()
    db.verified_users.update_one(
        {"chat_id": int(chat_id), "user_id": int(user_id)},
        {"$set": {"verified_at": now}},
        upsert=True
    )


def save_pending_welcome(chat_id: int, user_id: int, message_id: int):
    db = get_db()
    now = time.time()
    db.pending_welcome.update_one(
        {"chat_id": int(chat_id), "user_id": int(user_id)},
        {"$set": {
            "message_id": int(message_id), 
            "created_at": now
        }},
        upsert=True
    )


def pop_pending_welcome(chat_id: int, user_id: int) -> int | None:
    db = get_db()

    doc = db.pending_welcome.find_one_and_delete(
        {"chat_id": int(chat_id), "user_id": int(user_id)}
    )
    
    if not doc or "message_id" not in doc:
        return None
        
    return int(doc["message_id"])