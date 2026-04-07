import time
from pymongo import UpdateOne
from database.db import get_db

from handlers.asupan import state

def _asupan_db_init():
    db = get_db()
    db.asupan_groups.create_index(
        [("source_file", 1), ("chat_id", 1)], unique=True
    )
    db.asupan_autodel.create_index(
        [("source_file", 1), ("chat_id", 1)], unique=True
    )

def _db_load_enabled(collection_name: str) -> set[int]:
    db = get_db()
    col = db[collection_name]

    if collection_name == "asupan_autodel":
        cursor = col.find({"enabled": 1}, {"chat_id": 1})
    else:
        cursor = col.find({}, {"chat_id": 1})
        
    rows = list(cursor)
    return {int(r["chat_id"]) for r in rows if "chat_id" in r}

def _db_set_enabled(collection_name: str, values: set[int]):
    db = get_db()
    col = db[collection_name]
    now = time.time()
    src = "runtime"
    values_list = list(values)

    try:
        if collection_name == "asupan_autodel":
            col.update_many({}, {"$set": {"enabled": 0, "updated_at": now}})
            if values_list:
                operations = [
                    UpdateOne(
                        {"source_file": src, "chat_id": cid},
                        {"$set": {"enabled": 1, "updated_at": now}},
                        upsert=True
                    )
                    for cid in values_list
                ]
                col.bulk_write(operations)
        
        else: # asupan_groups
            if values_list:
                operations = [
                    UpdateOne(
                        {"source_file": src, "chat_id": cid},
                        {"$set": {"added_at": now}},
                        upsert=True
                    )
                    for cid in values_list
                ]
                col.bulk_write(operations)
                
                col.delete_many({
                    "source_file": src,
                    "chat_id": {"$nin": values_list}
                })
            else:
                col.delete_many({"source_file": src})

    except Exception as e:
        print(f"[!] Error saving asupan DB: {e}")
        raise e

def load_asupan_groups():
    try:
        _asupan_db_init()
        state.ASUPAN_ENABLED_CHATS = _db_load_enabled("asupan_groups")
    except Exception:
        state.ASUPAN_ENABLED_CHATS = set()

def save_asupan_groups():
    try:
        _db_set_enabled("asupan_groups", state.ASUPAN_ENABLED_CHATS)
    except Exception:
        pass

def is_asupan_enabled(chat_id: int) -> bool:
    return chat_id in state.ASUPAN_ENABLED_CHATS

def load_autodel_groups():
    try:
        state.AUTODEL_ENABLED_CHATS = _db_load_enabled("asupan_autodel")
    except Exception:
        state.AUTODEL_ENABLED_CHATS = set()

def save_autodel_groups():
    try:
        _db_set_enabled("asupan_autodel", state.AUTODEL_ENABLED_CHATS)
    except Exception:
        pass

def is_autodel_enabled(chat_id: int) -> bool:
    return chat_id in state.AUTODEL_ENABLED_CHATS

def init_asupan_storage():
    """Called at bot start in bot.py"""
    _asupan_db_init()
    load_asupan_groups()
    load_autodel_groups()