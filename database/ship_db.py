import time

from database.db import get_db

def _ship_db_init():
    db = get_db()
    db.users.create_index([("chat_id", 1), ("user_id", 1)], unique=True)  
    db.ship_state.create_index("chat_id", unique=True)


def add_user(chat_id: int, user):
    if not user or user.is_bot:
        return

    db = get_db()
    now = time.time()
    
    db.users.update_one(
        {"chat_id": int(chat_id), "user_id": int(user.id)},
        {"$set": {
            "name": str(user.first_name or ""),
            "updated_at": float(now)
        }},
        upsert=True
    )

def get_ship_last_time(chat_id: int) -> int:
    db = get_db()
    
    doc = db.ship_state.find_one(
        {"chat_id": int(chat_id)}, 
        {"last_time": 1}
    )
    
    return int(doc["last_time"]) if doc and "last_time" in doc else 0


def set_ship_last_time(chat_id: int, last_time: int):
    db = get_db()
    now_ts = time.time()

    db.ship_state.update_one(
        {"chat_id": int(chat_id)},
        {"$set": {
            "last_time": int(last_time),
            "updated_at": float(now_ts)
        }},
        upsert=True
    )


def get_users_pool(chat_id: int) -> list[dict]:
    db = get_db()

    cursor = db.users.find(
        {"chat_id": int(chat_id)}, 
        {"user_id": 1, "name": 1}
    )
    
    return [
        {"id": int(doc["user_id"]), "name": str(doc.get("name", ""))} 
        for doc in cursor if "user_id" in doc
    ]