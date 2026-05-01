import html
from telegram import Update
from telegram.ext import ContextTypes,ApplicationHandlerStop
from utils.config import OWNER_ID
from database.blacklist_db import is_blacklisted,add_user,remove_user,get_user,list_users
import re
from telegram.ext import ContextTypes,ApplicationHandlerStop

BLACKLIST_TEXT="<b>You have been blacklisted.</b>\n\nYou cannot use this bot."

_CMD_RE=re.compile(r"^/([A-Za-z0-9_]{1,32})(?:@([A-Za-z0-9_]{5,32}))?(?:\s|$)")

def _extract_command(text:str):
    m=_CMD_RE.match(text or "")
    if not m:
        return None,None
    return m.group(1).lower(),(m.group(2) or "").lower()

def _registered_commands(context):
    cmds=set()
    for handlers in context.application.handlers.values():
        for h in handlers:
            commands=getattr(h,"commands",None)
            if commands:
                cmds.update(str(c).lower() for c in commands)
    return cmds

async def _is_for_this_bot(context,mention:str)->bool:
    if not mention:
        return True
    me=await context.bot.get_me()
    return mention==str(me.username or "").lower()
    
def _is_owner(user_id:int)->bool:
    return int(user_id) in OWNER_ID

def _parse_user_id(msg,args,start_idx=1):
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id,start_idx
    if len(args)>start_idx:
        raw=str(args[start_idx]).strip()
        if raw.isdigit():
            return int(raw),start_idx+1
    return None,start_idx

async def blacklist_message_gate(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message
    user=update.effective_user
    if not msg or not user or _is_owner(user.id):
        return
    if not is_blacklisted(user.id):
        return
    cmd,mention=_extract_command(msg.text or "")
    if cmd and await _is_for_this_bot(context,mention) and cmd in _registered_commands(context):
        await msg.reply_text(BLACKLIST_TEXT,parse_mode="HTML",reply_to_message_id=msg.message_id)
    raise ApplicationHandlerStop

async def blacklist_callback_gate(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    user=update.effective_user
    if not query or not user or _is_owner(user.id):
        return
    if is_blacklisted(user.id):
        await query.answer("You have been blacklisted.",show_alert=True)
        raise ApplicationHandlerStop

def _help_text():
    return (
        "<b>Blacklist Management</b>\n\n"
        "<code>/blacklist add &lt;user_id&gt; [reason]</code>\n"
        "<code>/blacklist remove &lt;user_id&gt;</code>\n"
        "<code>/blacklist status &lt;user_id&gt;</code>\n"
        "<code>/blacklist list</code>\n\n"
        "You can also reply to a user message:\n"
        "<code>/blacklist add spam</code>\n"
        "<code>/blacklist remove</code>"
    )

async def blacklist_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message
    user=update.effective_user
    if not msg or not user or not _is_owner(user.id):
        return
    args=context.args or []
    if not args:
        return await msg.reply_text(_help_text(),parse_mode="HTML")
    action=str(args[0]).lower().strip()
    if action in ("add","ban"):
        target_id,next_idx=_parse_user_id(msg,args,1)
        if not target_id:
            return await msg.reply_text("<b>Usage:</b> <code>/blacklist add &lt;user_id&gt; [reason]</code>",parse_mode="HTML")
        if _is_owner(target_id):
            return await msg.reply_text("<b>Cannot blacklist owner.</b>",parse_mode="HTML")
        reason=" ".join(args[next_idx:]).strip()
        if msg.reply_to_message and not reason:
            reason=" ".join(args[1:]).strip()
        add_user(target_id,reason=reason,added_by=user.id)
        text=f"<b>User blacklisted</b>\n\nUser ID: <code>{target_id}</code>"
        if reason:
            text+=f"\nReason: <code>{html.escape(reason)}</code>"
        return await msg.reply_text(text,parse_mode="HTML")
    if action in ("remove","del","delete","unban"):
        target_id,_=_parse_user_id(msg,args,1)
        if not target_id:
            return await msg.reply_text("<b>Usage:</b> <code>/blacklist remove &lt;user_id&gt;</code>",parse_mode="HTML")
        removed=remove_user(target_id)
        return await msg.reply_text(f"<b>{'User removed from blacklist' if removed else 'User is not blacklisted'}</b>\n\nUser ID: <code>{target_id}</code>",parse_mode="HTML")
    if action in ("status","check"):
        target_id,_=_parse_user_id(msg,args,1)
        if not target_id:
            return await msg.reply_text("<b>Usage:</b> <code>/blacklist status &lt;user_id&gt;</code>",parse_mode="HTML")
        row=get_user(target_id)
        if not row:
            return await msg.reply_text(f"<b>User is not blacklisted</b>\n\nUser ID: <code>{target_id}</code>",parse_mode="HTML")
        reason=html.escape(row.get("reason") or "-")
        return await msg.reply_text(f"<b>User is blacklisted</b>\n\nUser ID: <code>{target_id}</code>\nReason: <code>{reason}</code>",parse_mode="HTML")
    if action in ("list","ls"):
        rows=list_users(50)
        if not rows:
            return await msg.reply_text("<b>Blacklist is empty.</b>",parse_mode="HTML")
        text="<b>Blacklisted Users</b>\n\n"
        for i,row in enumerate(rows,1):
            reason=html.escape(row.get("reason") or "-")
            text+=f"{i}. <code>{row['user_id']}</code> — {reason}\n"
        return await msg.reply_text(text[:3900],parse_mode="HTML")
    return await msg.reply_text(_help_text(),parse_mode="HTML")