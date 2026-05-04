from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID
from handlers.dl.service import get_upload_engine,get_upload_engine_name,set_upload_engine

_ENGINE_LABELS={"0":"Telethon","1":"PyroFork"}

def _status_text()->str:
    engine=get_upload_engine()
    name=_ENGINE_LABELS.get(engine,get_upload_engine_name().title())
    return (
        "<b>Upload Engine</b>\n\n"
        f"Current: <b>{name}</b>\n\n"
        "<code>/uploadengine telethon</code>\n"
        "<code>/uploadengine pyrofork</code>"
    )

async def uploadengine_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message
    user=update.effective_user
    if not msg or not user:
        return
    if user.id not in OWNER_ID:
        return
    args=context.args or []
    if not args:
        return await msg.reply_text(_status_text(),parse_mode="HTML")
    action=str(args[0] or "").strip().lower()
    if action in ("status","info"):
        return await msg.reply_text(_status_text(),parse_mode="HTML")
    if action in ("telethon","mtproto","0"):
        set_upload_engine("telethon")
        return await msg.reply_text("<b>Upload engine changed to Telethon</b>",parse_mode="HTML")
    if action in ("pyrofork","pyrogram","pyro","1"):
        set_upload_engine("pyrofork")
        return await msg.reply_text("<b>Upload engine changed to PyroFork</b>",parse_mode="HTML")
    return await msg.reply_text(
        "<b>Usage</b>\n\n"
        "<code>/uploadengine</code>\n"
        "<code>/uploadengine telethon</code>\n"
        "<code>/uploadengine pyrofork</code>",
        parse_mode="HTML",
    )