import time
import asyncio
from pymongo import UpdateOne
from database.db import get_db

_MODE_CACHE: dict[int, str] = {}

def _caca_db_init():
    db = get_db()
    db.caca_mode.create_index("user_id", unique=True)
    db.caca_groups.create_index("chat_id", unique=True)
    db.caca_approved.create_index("user_id", unique=True)

def _db_load_modes() -> dict[int, str]:
    db = get_db()
    cursor = db.caca_mode.find({}, {"user_id": 1, "mode": 1})
    out = {}
    for doc in cursor:
        try:
            if "user_id" in doc and "mode" in doc:
                out[int(doc["user_id"])] = str(doc["mode"])
        except Exception:
            continue
    return out

def _db_upsert_mode(user_id: int, mode: str):
    db = get_db()
    now = time.time()
    db.caca_mode.update_one(
        {"user_id": int(user_id)},
        {"$set": {"mode": str(mode), "updated_at": now}},
        upsert=True
    )

def _db_load_groups() -> set[int]:
    db = get_db()
    cursor = db.caca_groups.find({}, {"chat_id": 1})
    return {int(doc["chat_id"]) for doc in cursor if "chat_id" in doc}

def _db_add_group(chat_id: int):
    db = get_db()
    now = time.time()
    db.caca_groups.update_one(
        {"chat_id": int(chat_id)},
        {"$setOnInsert": {"added_at": now}},
        upsert=True
    )

def _db_remove_group(chat_id: int):
    db = get_db()
    db.caca_groups.delete_one({"chat_id": int(chat_id)})

async def init(): 
    """Initialize index and load data into cache."""
    await asyncio.to_thread(_caca_db_init)
    await reload_modes()

async def reload_modes():
    global _MODE_CACHE
    try:
        _MODE_CACHE = await asyncio.to_thread(_db_load_modes)
    except Exception:
        _MODE_CACHE = {}

def get_mode(user_id: int) -> str:
    """Get mode from cache."""
    return _MODE_CACHE.get(int(user_id), "default")

async def set_mode(user_id: int, mode: str):
    """Set the mode on the cache and database to async."""
    _MODE_CACHE[int(user_id)] = str(mode)
    await asyncio.to_thread(_db_upsert_mode, user_id, mode)

async def load_groups() -> set[int]:
    try:
        return await asyncio.to_thread(_db_load_groups)
    except Exception:
        return set()

async def add_group(chat_id: int):
    await asyncio.to_thread(_db_add_group, chat_id)

async def remove_group(chat_id: int):
    await asyncio.to_thread(_db_remove_group, chat_id)