import os,sqlite3,time,logging
from contextlib import closing

log=logging.getLogger(__name__)
DB_PATH=os.getenv("BLACKLIST_DB_PATH","data/blacklist.sqlite3")
_CACHE=None

def _db():
    os.makedirs(os.path.dirname(DB_PATH) or ".",exist_ok=True)
    con=sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def init():
    global _CACHE
    with closing(_db()) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS blacklisted_users (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                added_by INTEGER,
                added_at INTEGER
            )
        """)
        con.commit()
        rows=con.execute("SELECT user_id FROM blacklisted_users").fetchall()
    _CACHE={int(r[0]) for r in rows}
    log.info("Loaded blacklisted users: %s",len(_CACHE))

def _ensure():
    if _CACHE is None:
        init()

def is_blacklisted(user_id:int)->bool:
    _ensure()
    return int(user_id) in _CACHE

def add_user(user_id:int,reason:str|None=None,added_by:int|None=None):
    global _CACHE
    _ensure()
    user_id=int(user_id)
    reason=(reason or "").strip()
    added_by=int(added_by or 0)
    added_at=int(time.time())
    with closing(_db()) as con:
        con.execute(
            "INSERT OR REPLACE INTO blacklisted_users(user_id,reason,added_by,added_at) VALUES(?,?,?,?)",
            (user_id,reason,added_by,added_at)
        )
        con.commit()
    _CACHE.add(user_id)

def remove_user(user_id:int)->bool:
    global _CACHE
    _ensure()
    user_id=int(user_id)
    with closing(_db()) as con:
        cur=con.execute("DELETE FROM blacklisted_users WHERE user_id=?",(user_id,))
        con.commit()
    _CACHE.discard(user_id)
    return cur.rowcount>0

def get_user(user_id:int):
    _ensure()
    with closing(_db()) as con:
        row=con.execute("SELECT user_id,reason,added_by,added_at FROM blacklisted_users WHERE user_id=?",(int(user_id),)).fetchone()
    if not row:
        return None
    return {"user_id":int(row[0]),"reason":row[1] or "","added_by":int(row[2] or 0),"added_at":int(row[3] or 0)}

def list_users(limit:int=50):
    _ensure()
    with closing(_db()) as con:
        rows=con.execute("SELECT user_id,reason,added_by,added_at FROM blacklisted_users ORDER BY added_at DESC LIMIT ?",(int(limit),)).fetchall()
    return [{"user_id":int(r[0]),"reason":r[1] or "","added_by":int(r[2] or 0),"added_at":int(r[3] or 0)} for r in rows]