from pymongo import MongoClient
from utils.config import MONGO_URI, MONGO_DB_NAME

_client = None
_db = None

def mongo_enabled():
    return bool(MONGO_URI)

def get_db():
    global _client, _db

    if not mongo_enabled():
        raise RuntimeError("MongoDB not enabled")

    if _db is None:
        _client = MongoClient(MONGO_URI)
        _db = _client[MONGO_DB_NAME]

    return _db