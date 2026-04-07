import logging
from pymongo import MongoClient
from pymongo.database import Database

log = logging.getLogger(__name__)

MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB_NAME = "telegram_bot_db"

_client: MongoClient | None = None


def get_db() -> Database:
    global _client
    
    if _client is None:
        try:
            _client = MongoClient(MONGO_URI)
            
            _client.admin.command('ping')
            log.info("Successfully connected to MongoDB!")
            
        except Exception as e:
            log.error(f"Failed to connect to MongoDB: {e}")
            raise e
            
    return _client[MONGO_DB_NAME]


def close_connection():
    global _client
    if _client is not None:
        _client.close()
        _client = None
        log.info("The connection to MongoDB has been closed.")