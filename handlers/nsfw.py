import os, io, time, html, urllib.parse, sqlite3
import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session
from utils.config import OWNER_ID
from utils.text import bold, code

from handlers.groq import _emo, _can
from utils.nsfw import _extract_prompt_from_update


NSFW_DB = "data/nsfw.sqlite3"


def _nsfw_db_init():
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect(NSFW_DB)
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS nsfw_groups (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _db():
    _nsfw_db_init()
    return sqlite3.connect(NSFW_DB)


def is_nsfw_allowed(chat_id: int, chat_type: str) -> bool:
    if chat_type == "private":
        return True

    con = _db()
    try:
        cur = con.execute(
            "SELECT 1 FROM nsfw_groups WHERE chat_id=? AND enabled=1",
            (int(chat_id),),
        )
        return cur.fetchone() is not None
    finally:
        con.close()


def set_nsfw(chat_id: int, enabled: bool):
    con = _db()
    try:
        now = time.time()
        if enabled:
            con.execute(
                """
                INSERT INTO nsfw_groups (chat_id, enabled, updated_at)
                VALUES (?,1,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  enabled=1,
                  updated_at=excluded.updated_at
                """,
                (int(chat_id), now),
            )
        else:
            con.execute(
                """
                INSERT INTO nsfw_groups (chat_id, enabled, updated_at)
                VALUES (?,0,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  enabled=0,
                  updated_at=excluded.updated_at
                """,
                (int(chat_id), now),
            )
        con.commit()
    finally:
        con.close()


def get_all_enabled():
    con = _db()
    try:
        cur = con.execute(
            "SELECT chat_id FROM nsfw_groups WHERE enabled=1"
        )
        return [int(r[0]) for r in cur.fetchall()]
    finally:
        con.close()


async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if user.id in OWNER_ID:
        return True

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        m = await context.bot.get_chat_member(chat.id, user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def nsfw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        return

    arg = context.args[0].lower() if context.args else ""

    if arg == "list":
        if user.id not in OWNER_ID:
            return

        groups = get_all_enabled()

        if not groups:
            return await update.message.reply_text(
                "📭 Tidak ada grup NSFW aktif.",
                parse_mode="HTML"
            )

        lines = ["🔞 <b>Grup NSFW Aktif</b>\n"]

        for gid in groups:
            try:
                c = await context.bot.get_chat(gid)
                title = html.escape(c.title or str(gid))
                lines.append(f"• {title}")
            except:
                lines.append(f"• <code>{gid}</code>")

        return await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML"
        )

    if not await is_admin_or_owner(update, context):
        return

    if arg == "enable":
        set_nsfw(chat.id, True)
        return await update.message.reply_text(
            "🔞 NSFW <b>AKTIF</b> di grup ini.",
            parse_mode="HTML"
        )

    if arg == "disable":
        set_nsfw(chat.id, False)
        return await update.message.reply_text(
            "🚫 NSFW <b>DIMATIKAN</b> di grup ini.",
            parse_mode="HTML"
        )

    if arg == "status":
        status = "AKTIF" if is_nsfw_allowed(chat.id, chat.type) else "NONAKTIF"
        return await update.message.reply_text(
            f"📌 Status NSFW di grup ini: <b>{status}</b>",
            parse_mode="HTML"
        )

    return await update.message.reply_text(
        "⚙️ <b>NSFW Settings</b>\n\n"
        "<code>/nsfw enable</code>\n"
        "<code>/nsfw disable</code>\n"
        "<code>/nsfw status</code>\n"
        "<code>/nsfw list</code>",
        parse_mode="HTML"
    )


async def pollinations_generate_nsfw(update, context):
    msg = update.message
    if not msg:
        return

    chat = update.effective_chat

    if not is_nsfw_allowed(chat.id, chat.type):
        return await msg.reply_text(
            "🚫 NSFW tidak tersedia di grup ini."
        )

    em = _emo()

    prompt = _extract_prompt_from_update(update, context)
    if not prompt:
        return await msg.reply_text(
            f"{em} {bold('Contoh:')} {code('/generate waifu anime')}",
            parse_mode="HTML"
        )

    uid = msg.from_user.id if msg.from_user else 0
    if uid and not _can(uid):
        return await msg.reply_text(f"{em} ⏳ Sabar dulu ya...")

    status_msg = await msg.reply_text(
        bold("🖼️ Generating image..."),
        parse_mode="HTML"
    )

    boosted = f"{prompt}, nude, hentai, adult, soft lighting, bdsm"
    encoded = urllib.parse.quote(boosted)
    url = f"https://image.pollinations.ai/prompt/{encoded}"

    try:
        session = await get_http_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
            if r.status != 200:
                err = (await r.text())[:300]
                return await status_msg.edit_text(
                    f"{em} ❌ Gagal.\n<code>{html.escape(err)}</code>",
                    parse_mode="HTML"
                )

            bio = io.BytesIO(await r.read())
            bio.name = "nsfw.png"

            await msg.reply_photo(
                photo=bio,
                caption=f"🔞 {bold('NSFW')}\n🖼️ Prompt: {code(prompt)}",
                parse_mode="HTML"
            )

            await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(
            f"{em} ❌ Error: <code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )


try:
    _nsfw_db_init()
except Exception:
    pass