import os, json, io, time, html, asyncio, urllib.parse
import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session
from utils.config import OWNER_ID
from utils.text import bold, code

from handlers.groq import _emo, _can, _extract_prompt_from_update

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
    
#nsfw
async def enablensfw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if user.id not in OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    if chat.type == "private":
        return await update.message.reply_text("ℹ️ NSFW selalu aktif di PM.")

    data = _load_nsfw()
    if chat.id not in data["groups"]:
        data["groups"].append(chat.id)
        _save_nsfw(data)

    await update.message.reply_text("🔞 NSFW diaktifkan di grup ini.")
    
async def disablensfw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if user.id not in OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    data = _load_nsfw()
    if chat.id in data["groups"]:
        data["groups"].remove(chat.id)
        _save_nsfw(data)

    await update.message.reply_text("🚫 NSFW dimatikan di grup ini.")
    
async def nsfwlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Owner only.")

    data = _load_nsfw()
    if not data["groups"]:
        return await update.message.reply_text("📭 Tidak ada grup NSFW.")

    lines = ["🔞 <b>NSFW Whitelisted Groups</b>\n"]

    for gid in data["groups"]:
        try:
            chat = await context.bot.get_chat(gid)
            title = chat.title or chat.username or "Unknown Group"
            lines.append(f"• {html.escape(title)}")
        except Exception:
            lines.append("• <i>Unknown / Bot not in group</i>")

    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="HTML")
    
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
            "🚫 NSFW tidak tersedia di grup ini.\n"
            "PM bot atau hubungi @hirohitokiyoshi untuk mengaktifkan."
        )

    em = _emo()

    prompt = _extract_prompt_from_update(update, context)
    if not prompt:
        return await msg.reply_text(
            f"{em} {bold('Contoh:')} {code('/nsfw waifu anime')}",
            parse_mode="HTML"
        )

    uid = msg.from_user.id if msg.from_user else 0
    if uid and not _can(uid):
        return await msg.reply_text(f"{em} ⏳ Sabar dulu ya {COOLDOWN}s…")

    try:
        status_msg = await msg.reply_text(
            bold("🔞 Generating image..."),
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

