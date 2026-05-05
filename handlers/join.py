import time
import logging
from telegram import InlineKeyboardMarkup,InlineKeyboardButton,Update
from telegram.ext import ContextTypes
from utils.config import SUPPORT_CHANNEL_ID,SUPPORT_CHANNEL_LINK

log=logging.getLogger(__name__)
_JOIN_CACHE={}
_JOIN_CACHE_TTL=300

async def is_joined_support_channel(user_id:int,context:ContextTypes.DEFAULT_TYPE)->bool:
    if not SUPPORT_CHANNEL_ID:
        return True
    now=time.monotonic()
    key=int(user_id)
    cached=_JOIN_CACHE.get(key)
    if cached and now-cached["ts"]<_JOIN_CACHE_TTL:
        return True
    try:
        member=await context.bot.get_chat_member(SUPPORT_CHANNEL_ID,user_id)
        joined=member.status in ("member","administrator","creator")
        if joined:
            _JOIN_CACHE[key]={"ts":now}
            return True
        _JOIN_CACHE.pop(key,None)
        return False
    except Exception as e:
        _JOIN_CACHE.pop(key,None)
        log.warning("[JOIN CHECK ERROR] user_id=%s err=%r",user_id,e)
        return False

def join_required_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Support Channel",url=SUPPORT_CHANNEL_LINK)]
    ])

async def require_join_or_block(update:Update,context:ContextTypes.DEFAULT_TYPE)->bool:
    if update.callback_query:
        user=update.callback_query.from_user
        reply_target=update.callback_query.message
    elif update.message:
        user=update.message.from_user
        reply_target=update.message
    else:
        return False
    if not user:
        return False
    joined=await is_joined_support_channel(user.id,context)
    if joined:
        return True
    if not SUPPORT_CHANNEL_LINK:
        log.warning("SUPPORT_CHANNEL_ID is set but SUPPORT_CHANNEL_LINK is missing. Allowing access.")
        return True
    text="<b>To use the feature</b>\nyou must join the support channel first."
    try:
        if update.callback_query:
            await update.callback_query.answer("Please join the support channel first",show_alert=True)
        await reply_target.reply_text(text,reply_markup=join_required_keyboard(),parse_mode="HTML")
    except Exception as e:
        log.warning("[JOIN BLOCK ERROR] user_id=%s err=%r",user.id,e)
    return False