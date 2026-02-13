import os
import time
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "data", "cookies.txt"))
COOKIES_DIR = os.path.dirname(COOKIES_PATH)

_MAX_FILE_SIZE = 512 * 1024
_EST_EXPIRE_SECONDS = 3 * 24 * 60 * 60


def _is_owner(user_id: int) -> bool:
    try:
        return int(user_id) in set(OWNER_ID)
    except Exception:
        return False


def _looks_like_netscape_cookies(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "HTTP Cookie File" in t:
        return True
    lines = [ln for ln in t.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return False
    cols = lines[0].split("\t")
    return len(cols) >= 6


async def cookies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user = update.effective_user
    if not user or not _is_owner(user.id):
        return

    doc = None
    if msg.document:
        doc = msg.document
    elif msg.reply_to_message and msg.reply_to_message.document:
        doc = msg.reply_to_message.document

    if not doc:
        return await msg.reply_text(
            "📎 <b>Kirim file cookies sebagai document</b>.\n\n"
            "Cara pakai:\n"
            "• Kirim <code>cookies.txt</code> lalu ketik <code>/cookies</code>\n"
            "• Atau reply pesan dengan <code>/cookies</code>",
            parse_mode="HTML",
        )

    if doc.file_size and doc.file_size > _MAX_FILE_SIZE:
        return await msg.reply_text("❌ <b>File terlalu besar.</b> Maks 512KB.", parse_mode="HTML")

    os.makedirs(COOKIES_DIR, exist_ok=True)
    tmp_path = COOKIES_PATH + ".uploading"

    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=tmp_path)

        with open(tmp_path, "rb") as f:
            raw = f.read()

        if not raw:
            raise RuntimeError("File kosong")

        text = raw.decode("utf-8", errors="ignore")

        if not _looks_like_netscape_cookies(text):
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return await msg.reply_text(
                "❌ <b>Format cookies tidak dikenali.</b>\n"
                "Pastikan format <b>Netscape cookies.txt</b>.",
                parse_mode="HTML",
            )

        os.replace(tmp_path, COOKIES_PATH)

        now = time.time()
        updated_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        exp_ts = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(now + _EST_EXPIRE_SECONDS),
        )

        return await msg.reply_text(
            "✅ <b>Cookies berhasil diupdate.</b>\n"
            f"🕒 Updated: <code>{updated_ts}</code>\n"
            f"⌛ Est. expired: <code>{exp_ts}</code>",
            parse_mode="HTML",
        )

    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return await msg.reply_text(
            f"❌ <b>Gagal update cookies:</b> <code>{e}</code>",
            parse_mode="HTML",
        )