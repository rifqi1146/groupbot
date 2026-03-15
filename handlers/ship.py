import os
import random
import sqlite3
import time

from telegram import Update
from telegram.ext import ContextTypes

SHIP_DB = "data/ship.sqlite3"
SHIP_COOLDOWN = 60 * 60 * 24  # 24 jam

SHIP_MESSAGES = [
    "🥰 Kalian keliatan nyaman satu sama lain",
    "💗 Vibes-nya lembut dan saling ngerti",
    "🌸 Cocoknya tuh keliatan natural",
    "💞 Kayak saling nenangin tanpa sadar",
    "✨ Bareng-bareng keliatan lebih hidup",
    "🫶 Ada rasa aman di situ",
    "🌷 Kalo ngobrol pasti nyambung",
    "💫 Energinya bikin hangat",
    "🤍 Sederhana tapi kerasa",
    "🌼 Keliatan saling support",
]

SHIP_ENDING = [
    "Semoga selalu akur ya 🤍",
    "Lucu kalo beneran 🥹",
    "Doain yang terbaik ✨",
    "Siapa tau ini pertanda 🌸",
    "Pelan-pelan aja 💗",
    "Enjoy the moment 🫶",
]


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


def tag(u):
    return f'<a href="tg://user?id={u["id"]}">{u["name"]}</a>'


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


async def _is_chat_member(bot, chat_id: int, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status not in ("left", "kicked")
    except Exception:
        return False
        
        
def format_remaining(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


async def ship_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return

    now = int(time.time())
    last_time = get_ship_last_time(chat.id)

    if now - last_time < SHIP_COOLDOWN:
        remain = SHIP_COOLDOWN - (now - last_time)
        return await msg.reply_text(
            f"⏳ <b>Ship masih cooldown</b>\n\n"
            f"Pasangan berikutnya bisa dipilih dalam:\n"
            f"<code>{format_remaining(remain)}</code>",
            parse_mode="HTML",
        )

    add_user(chat.id, msg.from_user)

    users = []

    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        if await _is_chat_member(context.bot, chat.id, u.id):
            add_user(chat.id, u)
            users.append({"id": u.id, "name": str(u.first_name or "Unknown")})

    for ent in msg.entities or []:
        if ent.type == "text_mention" and ent.user:
            u = ent.user
            if await _is_chat_member(context.bot, chat.id, u.id):
                add_user(chat.id, u)
                users.append({"id": u.id, "name": str(u.first_name or "Unknown")})

    pool = get_users_pool(chat.id)

    if len(users) < 2:
        pool_ids = [p for p in pool if p.get("id") is not None]
        if len(pool_ids) < 2:
            return await msg.reply_text("❌ Belum cukup orang buat di-ship.")

        picked = None
        for _ in range(12):
            a, b = random.sample(pool_ids, 2)
            ok_a = await _is_chat_member(context.bot, chat.id, int(a["id"]))
            ok_b = await _is_chat_member(context.bot, chat.id, int(b["id"]))
            if ok_a and ok_b:
                picked = (a, b)
                break

        if not picked:
            return await msg.reply_text("❌ Belum menemukan 2 member aktif untuk di-ship.")

        users = [picked[0], picked[1]]

    u1, u2 = users[:2]

    percent = random.randint(50, 100)
    msg_text = random.choice(SHIP_MESSAGES)
    ending = random.choice(SHIP_ENDING)

    text = (
        f"💖 <b>SHIP RESULT</b>\n\n"
        f"👤 {tag(u1)}\n"
        f"👤 {tag(u2)}\n\n"
        f"❤️ <b>Love Meter:</b> <code>{percent}%</code>\n\n"
        f"{msg_text}\n"
        f"<i>{ending}</i>"
    )

    await msg.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    set_ship_last_time(chat.id, now)


try:
    _ship_db_init()
except Exception:
    pass