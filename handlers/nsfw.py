import os, json, io, time, html, asyncio, urllib.parse
import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session
from utils.config import OWNER_ID
from utils.text import bold, code

from handlers.groq import _emo, _can 
from utils.nsfw import _extract_prompt_from_update

#nsfw
NSFW_FILE = "data/nsfw_groups.json"
os.makedirs("data", exist_ok=True)

def _load_nsfw():
    if not os.path.exists(NSFW_FILE):
        return {"groups": []}
    with open(NSFW_FILE, "r") as f:
        return json.load(f)

def _save_nsfw(data):
    with open(NSFW_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_nsfw_allowed(chat_id: int, chat_type: str) -> bool:
    if chat_type == "private":
        return True
    data = _load_nsfw()
    return chat_id in data["groups"]
    
async def is_admin_or_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if user.id in OWNER_ID:
        return True

    if chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False
        
#nsfw
async def nsfw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        return

    data = _load_nsfw()
    arg = context.args[0].lower() if context.args else ""

    if arg == "list":
        if user.id not in OWNER_ID:
            return

        if not data["groups"]:
            return await update.message.reply_text(
                "📭 Tidak ada grup NSFW aktif.",
                parse_mode="HTML"
            )

        lines = ["🔞 <b>Grup NSFW Aktif</b>\n"]
        for gid in data["groups"]:
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
        if chat.id not in data["groups"]:
            data["groups"].append(chat.id)
            _save_nsfw(data)

        return await update.message.reply_text(
            "🔞 NSFW <b>AKTIF</b> di grup ini.",
            parse_mode="HTML"
        )

    if arg == "disable":
        if chat.id in data["groups"]:
            data["groups"].remove(chat.id)
            _save_nsfw(data)

        return await update.message.reply_text(
            "🚫 NSFW <b>DIMATIKAN</b> di grup ini.",
            parse_mode="HTML"
        )

    if arg == "status":
        status = "AKTIF" if chat.id in data["groups"] else "NONAKTIF"
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
    """
    Usage: /nsfw <prompt>
    """
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
        return await msg.reply_text(f"{em} ⏳ Sabar dulu ya {COOLDOWN}s…")

    try:
        status_msg = await msg.reply_text(
            bold("🖼️ Generating image..."),
            parse_mode="HTML"
        )
    except Exception:
        status_msg = None

    boosted = (
        f"{prompt}, nude, hentai, adult, "
        "soft lighting, bdsm"
    )
    encoded = urllib.parse.quote(boosted)
    url = f"https://image.pollinations.ai/prompt/{encoded}"

    try:
        session = await get_http_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                err = (await resp.text())[:300]
                return await status_msg.edit_text(
                    f"{em} ❌ Gagal generate.\n<code>{html.escape(err)}</code>",
                    parse_mode="HTML"
                )

            bio = io.BytesIO(await resp.read())
            bio.name = "nsfw.png"

            await msg.reply_photo(
                photo=bio,
                caption=f"🔞 {bold('NSFW')}\n🖼️ Prompt: {code(prompt)}",
                parse_mode="HTML"
            )

            if status_msg:
                await status_msg.delete()

    except Exception as e:
        if status_msg:
            await status_msg.edit_text(
                f"{em} ❌ Error: <code>{html.escape(str(e))}</code>",
                parse_mode="HTML"
            )

