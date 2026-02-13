from utils.premium import (
    init_premium_db,
    premium_add,
    premium_del,
    premium_list,
    premium_load_set,
    is_premium,
)

_PREMIUM_USERS = set()


def init():
    global _PREMIUM_USERS
    init_premium_db()
    _PREMIUM_USERS = premium_load_set()


def add(uid: int):
    premium_add(int(uid))
    _PREMIUM_USERS.add(int(uid))


def remove(uid: int):
    premium_del(int(uid))
    _PREMIUM_USERS.discard(int(uid))


def list_users():
    return premium_list()


def check(uid: int) -> bool:
    return is_premium(int(uid), _PREMIUM_USERS)


def cache_set():
    return set(_PREMIUM_USERS)