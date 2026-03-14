import time
from database.db import db_session
from .constants import ASUPAN_DB_PATH
from . import state


def _asupan_db_init():
    with db_session(ASUPAN_DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS asupan_groups (
                source_file TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                added_at REAL NOT NULL,
                PRIMARY KEY (source_file, chat_id)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS asupan_autodel (
                source_file TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                enabled INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (source_file, chat_id)
            )
            """
        )
        con.commit()


def _db_load_enabled(table: str) -> set[int]:
    with db_session(ASUPAN_DB_PATH) as con:
        if table == "asupan_autodel":
            cur = con.execute("SELECT chat_id FROM asupan_autodel WHERE enabled=1")
            rows = cur.fetchall()
            if rows:
                return {int(r[0]) for r in rows if r and r[0] is not None}

            cur = con.execute("SELECT chat_id FROM asupan_autodel")
            rows = cur.fetchall()
            return {int(r[0]) for r in rows if r and r[0] is not None}

        cur = con.execute("SELECT chat_id FROM asupan_groups")
        rows = cur.fetchall()
        return {int(r[0]) for r in rows if r and r[0] is not None}


def _db_set_enabled(table: str, values: set[int]):
    with db_session(ASUPAN_DB_PATH) as con:
        try:
            con.execute("BEGIN")
            now = time.time()
            src = "runtime"

            if table == "asupan_autodel":
                con.execute("UPDATE asupan_autodel SET enabled=0, updated_at=?", (now,))
                if values:
                    con.executemany(
                        """
                        INSERT INTO asupan_autodel (source_file, chat_id, enabled, updated_at)
                        VALUES (?, ?, 1, ?)
                        ON CONFLICT(source_file, chat_id) DO UPDATE SET
                          enabled=1,
                          updated_at=excluded.updated_at
                        """,
                        [(src, int(cid), now) for cid in values],
                    )
            else:
                if values:
                    con.executemany(
                        """
                        INSERT INTO asupan_groups (source_file, chat_id, added_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(source_file, chat_id) DO UPDATE SET
                          added_at=excluded.added_at
                        """,
                        [(src, int(cid), now) for cid in values],
                    )

                con.execute(
                    "DELETE FROM asupan_groups WHERE source_file=? AND chat_id NOT IN (%s)"
                    % (",".join("?" * len(values)) if values else "-1"),
                    (src, *[int(cid) for cid in values]) if values else (src,),
                )

            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise


def load_asupan_groups():
    try:
        _asupan_db_init()
        state.ASUPAN_ENABLED_CHATS = _db_load_enabled("asupan_groups")
    except Exception:
        state.ASUPAN_ENABLED_CHATS = set()


def save_asupan_groups():
    try:
        _asupan_db_init()
        _db_set_enabled("asupan_groups", state.ASUPAN_ENABLED_CHATS)
    except Exception:
        pass


def is_asupan_enabled(chat_id: int) -> bool:
    return chat_id in state.ASUPAN_ENABLED_CHATS


def load_autodel_groups():
    try:
        _asupan_db_init()
        state.AUTODEL_ENABLED_CHATS = _db_load_enabled("asupan_autodel")
    except Exception:
        state.AUTODEL_ENABLED_CHATS = set()


def save_autodel_groups():
    try:
        _asupan_db_init()
        _db_set_enabled("asupan_autodel", state.AUTODEL_ENABLED_CHATS)
    except Exception:
        pass


def is_autodel_enabled(chat_id: int) -> bool:
    return chat_id in state.AUTODEL_ENABLED_CHATS


def init_asupan_storage():
    try:
        _asupan_db_init()
    except Exception:
        pass

    try:
        load_asupan_groups()
    except Exception:
        pass

    try:
        load_autodel_groups()
    except Exception:
        pass