import time
import re
from pymongo import UpdateOne

from utils.config import OWNER_ID
from database.premium import is_premium
from database.db import get_db


def _auto_dl_db_init():
    db = get_db()
    db.auto_dl_groups.create_index("chat_id", unique=True)


def load_auto_dl() -> set[int]:
    db = get_db()
    _auto_dl_db_init()
    cursor = db.auto_dl_groups.find({"enabled": 1}, {"chat_id": 1})
    return {int(doc["chat_id"]) for doc in cursor if "chat_id" in doc}


def save_auto_dl(groups: set[int]):
    db = get_db()
    _auto_dl_db_init()
    now = time.time()
    
    try:
        db.auto_dl_groups.update_many({}, {"$set": {"enabled": 0, "updated_at": float(now)}})

        if groups:
            operations = [
                UpdateOne(
                    {"chat_id": int(cid)},
                    {"$set": {"enabled": 1, "updated_at": float(now)}},
                    upsert=True
                )
                for cid in groups
            ]
            db.auto_dl_groups.bulk_write(operations)
            
    except Exception as e:
        raise e

def extract_domain(url: str) -> str:
    u = (url or "").strip().lower()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    m = re.search(r"https?://([^/]+)", u)
    if not m:
        return ""
    host = m.group(1)
    host = host.split(":", 1)[0]
    return host

def is_premium_required(url: str, premium_domains: set[str]) -> bool:
    host = extract_domain(url)
    if not host:
        return False
    for d in premium_domains:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    return False

def is_premium_user(user_id: int) -> bool:
    uid = int(user_id)
    if uid in OWNER_ID:
        return True
    return is_premium(uid)