import os
import time
import sqlite3

SHIP_DB = "data/ship.sqlite3"

def _ship_db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(SHIP_DB)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ship_state (
                chat_id INTEGER PRIMARY KEY,
                last_time INTEGER NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _db():
    _ship_db_init()
    return sqlite3.connect(SHIP_DB)

def add_user(chat_id: int, user):
    if not user or user.is_bot:
        return

    con = _db()
    try:
        now = time.time()
        con.execute(
            """
            INSERT INTO users (chat_id, user_id, name, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
              name=excluded.name,
              updated_at=excluded.updated_at
            """,
            (int(chat_id), int(user.id), str(user.first_name or ""), float(now)),
        )
        con.commit()
    finally:
        con.close()


def _ship_state_has_updated_at(con) -> bool:
    try:
        cur = con.execute("PRAGMA table_info(ship_state)")
        cols = {row[1] for row in cur.fetchall() if row and len(row) > 1}
        return "updated_at" in cols
    except Exception:
        return False


def get_ship_last_time(chat_id: int) -> int:
    con = _db()
    try:
        cur = con.execute(
            "SELECT last_time FROM ship_state WHERE chat_id=?",
            (int(chat_id),),
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    finally:
        con.close()


def set_ship_last_time(chat_id: int, last_time: int):
    con = _db()
    try:
        now_ts = time.time()
        has_updated_at = _ship_state_has_updated_at(con)

        if has_updated_at:
            con.execute(
                """
                INSERT INTO ship_state (chat_id, last_time, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  last_time=excluded.last_time,
                  updated_at=excluded.updated_at
                """,
                (int(chat_id), int(last_time), float(now_ts)),
            )
        else:
            con.execute(
                """
                INSERT INTO ship_state (chat_id, last_time)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  last_time=excluded.last_time
                """,
                (int(chat_id), int(last_time)),
            )

        con.commit()
    finally:
        con.close()


def get_users_pool(chat_id: int) -> list[dict]:
    con = _db()
    try:
        cur = con.execute(
            "SELECT user_id, name FROM users WHERE chat_id=?",
            (int(chat_id),),
        )
        rows = cur.fetchall()
        return [{"id": int(uid), "name": str(name)} for (uid, name) in rows if uid is not None]
    finally:
        con.close()
        