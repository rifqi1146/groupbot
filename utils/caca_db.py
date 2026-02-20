import os
import time
import sqlite3
import asyncio
import logging

CACA_DB_PATH = "data/caca.sqlite3"

_MODE_CACHE: dict[int, str] = {}
log = logging.getLogger(__name__)


def _caca_db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(CACA_DB_PATH)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
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
    finally:
        con.close()


def _caca_db_load_modes() -> dict[int, str]:
    con = sqlite3.connect(CACA_DB_PATH)
    try:
        cur = con.execute("SELECT user_id, mode FROM caca_mode")
        rows = cur.fetchall()
        out = {}
        for uid, mode in rows:
            try:
                out[int(uid)] = str(mode)
            except Exception:
                pass
        return out
    finally:
        con.close()


def _caca_db_save_modes(modes: dict[int, str]):
    con = sqlite3.connect(CACA_DB_PATH)
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
    finally:
        con.close()


def _caca_db_load_groups() -> set[int]:
    con = sqlite3.connect(CACA_DB_PATH)
    try:
        cur = con.execute("SELECT chat_id FROM caca_groups")
        rows = cur.fetchall()
        return {int(r[0]) for r in rows if r and r[0] is not None}
    finally:
        con.close()


def _caca_db_save_groups(groups: set[int]):
    con = sqlite3.connect(CACA_DB_PATH)
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
        log.exception("Error reloading modes")
        _MODE_CACHE = {}


def get_mode(user_id: int) -> str:
    return _MODE_CACHE.get(int(user_id), "default")


def set_mode(user_id: int, mode: str):
    _MODE_CACHE[int(user_id)] = str(mode)
    _caca_db_save_modes(_MODE_CACHE)


def remove_mode(user_id: int):
    _MODE_CACHE.pop(int(user_id), None)
    _caca_db_save_modes(_MODE_CACHE)


def load_groups() -> set[int]:
    try:
        return _caca_db_load_groups()
    except Exception:
        log.exception("Error loading groups")
        return set()


def save_groups(groups: set[int]):
    _caca_db_save_groups(groups)
