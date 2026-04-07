import time

from database.db import get_db

def init_premium_db():
    db = get_db()
    db.premium_users.create_index("user_id", unique=True)


def premium_add(user_id: int):
    db = get_db()
    
    db.premium_users.update_one(
        {"user_id": int(user_id)},
        {"$set": {"added_at": float(time.time())}},
        upsert=True
    )


def premium_del(user_id: int):
    db = get_db()
    db.premium_users.delete_one({"user_id": int(user_id)})


def premium_list() -> list[int]:
    db = get_db()
    
    cursor = db.premium_users.find({}, {"user_id": 1}).sort("added_at", -1)
    return [int(doc["user_id"]) for doc in cursor if "user_id" in doc]


def premium_load_set() -> set[int]:
    db = get_db()

    cursor = db.premium_users.find({}, {"user_id": 1})
    return {int(doc["user_id"]) for doc in cursor if "user_id" in doc}


def is_premium(user_id: int, cache: set[int] | None = None) -> bool:
    uid = int(user_id)

    if cache is not None:
        return uid in cache

    db = get_db()
    doc = db.premium_users.find_one({"user_id": uid}, {"_id": 1})
    return doc is not None