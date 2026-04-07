from database.db import get_db

def _db_init():
    db = get_db()
    db.broadcast_users.create_index("chat_id", unique=True)
    db.broadcast_groups.create_index("chat_id", unique=True)


def _load_groups() -> list[int]:
    _db_init()
    db = get_db()
    
    cursor = db.broadcast_groups.find({"enabled": 1}, {"chat_id": 1})
    
    return [int(doc["chat_id"]) for doc in cursor if "chat_id" in doc]