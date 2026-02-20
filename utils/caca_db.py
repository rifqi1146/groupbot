import time
import asyncio

from utils.db import db_session

CACA_DB_PATH = "data/caca.sqlite3"

_MODE_CACHE: dict[int, str] = {}


def _caca_db_init():
    with db_session(CACA_DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS caca_mode (
                user_id INTEGER PRIMARY KEY,
                mode TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS caca_groups (
                chat_id INTEGER PRIMARY KEY,
                added_at REAL NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS caca_approved (
                user_id INTEGER PRIMARY KEY,
                added_at REAL NOT NULL
            )
            """
        )
        con.commit()


def _caca_db_load_modes() -> dict[int, str]:
    with db_session(CACA_DB_PATH) as con:
        cur = con.execute("SELECT user_id, mode FROM caca_mode")
        rows = cur.fetchall()
        out = {}
        for uid, mode in rows:
            try:
                out[int(uid)] = str(mode)
            except Exception:
                pass
        return out


def _caca_db_save_modes(modes: dict[int, str]):
    with db_session(CACA_DB_PATH) as con:
        try:
            con.execute("BEGIN")
            keys = list(modes.keys())
            if not keys:
                con.execute("DELETE FROM caca_mode")
            else:
                placeholders = ",".join(["?"] * len(keys))
                con.execute(f"DELETE FROM caca_mode WHERE user_id NOT IN ({placeholders})", tuple(keys))
            now = time.time()
            con.executemany(
                """
                INSERT INTO caca_mode (user_id, mode, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  mode=excluded.mode,
                  updated_at=excluded.updated_at
                """,
                [(int(uid), str(modes[uid]), now) for uid in keys],
            )
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise


def _caca_db_load_groups() -> set[int]:
    with db_session(CACA_DB_PATH) as con:
        cur = con.execute("SELECT chat_id FROM caca_groups")
        rows = cur.fetchall()
        return {int(r[0]) for r in rows if r and r[0] is not None}


def _caca_db_save_groups(groups: set[int]):
    with db_session(CACA_DB_PATH) as con:
        try:
            con.execute("BEGIN")
            if not groups:
                con.execute("DELETE FROM caca_groups")
            else:
                placeholders = ",".join(["?"] * len(groups))
                con.execute(f"DELETE FROM caca_groups WHERE chat_id NOT IN ({placeholders})", tuple(groups))
            now = time.time()
            con.executemany(
                "INSERT OR IGNORE INTO caca_groups (chat_id, added_at) VALUES (?, ?)",
                [(int(gid), now) for gid in groups],
            )
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise


def _caca_db_add_group(chat_id: int):
    con = sqlite3.connect(CACA_DB_PATH)
    try:
        now = time.time()
        con.execute("INSERT OR IGNORE INTO caca_groups (chat_id, added_at) VALUES (?, ?)", (int(chat_id), now))
        con.commit()
    finally:
        con.close()


def _caca_db_remove_group(chat_id: int):
    con = sqlite3.connect(CACA_DB_PATH)
    try:
        con.execute("DELETE FROM caca_groups WHERE chat_id = ?", (int(chat_id),))
        con.commit()
    finally:
        con.close()


async def init():
    await asyncio.to_thread(_caca_db_init)
    await reload_modes()


async def reload_modes():
    global _MODE_CACHE
    try:
        _MODE_CACHE = await asyncio.to_thread(_caca_db_load_modes)
    except Exception:
        _MODE_CACHE = {}


def get_mode(user_id: int) -> str:
    return _MODE_CACHE.get(int(user_id), "default")


def set_mode(user_id: int, mode: str):
    _MODE_CACHE[int(user_id)] = str(mode)
    _caca_db_save_modes(_MODE_CACHE)


def remove_mode(user_id: int):
    _MODE_CACHE.pop(int(user_id), None)
    _caca_db_save_modes(_MODE_CACHE)


async def load_groups() -> set[int]:
    try:
        return await asyncio.to_thread(_caca_db_load_groups)
    except Exception:
        return set()


async def save_groups(groups: set[int]):
    await asyncio.to_thread(_caca_db_save_groups, groups)


async def add_group(chat_id: int):
    await asyncio.to_thread(_caca_db_add_group, chat_id)


async def remove_group(chat_id: int):
    await asyncio.to_thread(_caca_db_remove_group, chat_id)