import html
import logging
import re
from telegram import Update
from telegram.ext import ContextTypes,ApplicationHandlerStop
from utils.config import OWNER_ID
from database.blacklist_db import (
    is_blacklisted,add_user,remove_user,get_user,list_users,
    is_group_blacklisted,add_group,remove_group,get_group,list_groups
)

log=logging.getLogger(__name__)

BLACKLIST_TEXT="<b>You have been blacklisted.</b>\n\nYou cannot use this bot."
GROUP_BLACKLIST_TEXT=(
    "<b>Bot Disabled in This Group</b>\n\n"
    "To prevent spam, this bot has been disabled in this group.\n"
    "Please contact {owners} to reactivate it."
)

_CMD_RE=re.compile(r"^/([A-Za-z0-9_]{1,32})(?:@([A-Za-z0-9_]{5,32}))?(?:\s|$)")
_OWNER_MENTION_CACHE={}

def _owner_ids():
    if isinstance(OWNER_ID,(list,tuple,set)):
        return {int(x) for x in OWNER_ID}
    return {int(OWNER_ID)}

def _is_owner(user_id:int)->bool:
    return int(user_id) in _owner_ids()

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

async def _owner_mention(context,owner_id:int):
    if owner_id in _OWNER_MENTION_CACHE:
        return _OWNER_MENTION_CACHE[owner_id]
    try:
        chat=await context.bot.get_chat(owner_id)
        name=html.escape(getattr(chat,"full_name",None) or getattr(chat,"first_name",None) or getattr(chat,"username",None) or str(owner_id))
        username=(getattr(chat,"username",None) or "").strip()
        mention=f'<a href="https://t.me/{html.escape(username,quote=True)}">{name}</a>' if username else f'<a href="tg://user?id={owner_id}">{name}</a>'
    except Exception as e:
        log.warning("Failed to resolve owner mention | owner_id=%s error=%s",owner_id,e)
        mention=f'<a href="tg://user?id={owner_id}">owner</a>'
    _OWNER_MENTION_CACHE[owner_id]=mention
    return mention

async def _owner_mentions(context):
    mentions=[]
    for owner_id in sorted(_owner_ids()):
        mentions.append(await _owner_mention(context,owner_id))
    return ", ".join(mentions) or "the owner"

async def _group_blacklist_text(context):
    owners=await _owner_mentions(context)
    return GROUP_BLACKLIST_TEXT.format(owners=owners)

def _parse_user_id(msg,args,start_idx=1):
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id,start_idx
    if len(args)>start_idx:
        raw=str(args[start_idx]).strip()
        if raw.isdigit():
            return int(raw),start_idx+1
    return None,start_idx

def _parse_group_id(msg,args,start_idx=2):
    if len(args)>start_idx:
        raw=str(args[start_idx]).strip()
        if re.fullmatch(r"-?\d+",raw):
            return int(raw),start_idx+1
    chat=getattr(msg,"chat",None)
    if chat and chat.type in ("group","supergroup"):
        return chat.id,start_idx
    return None,start_idx

async def _resolve_group_title(bot,group_id:int,fallback:str=""):
    try:
        chat=await bot.get_chat(group_id)
        return (getattr(chat,"title",None) or fallback or str(group_id)).strip()
    except Exception as e:
        log.warning("Failed to resolve group title | group_id=%s error=%s",group_id,e)
        return fallback or str(group_id)

async def blacklist_message_gate(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message
    user=update.effective_user
    chat=update.effective_chat
    if not msg or not user or _is_owner(user.id):
        return
    text=msg.text or msg.caption or ""
    cmd,mention=_extract_command(text)
    is_bot_cmd=cmd and await _is_for_this_bot(context,mention) and cmd in _registered_commands(context)
    if chat and chat.type in ("group","supergroup") and is_group_blacklisted(chat.id):
        if is_bot_cmd:
            await msg.reply_text(await _group_blacklist_text(context),parse_mode="HTML",disable_web_page_preview=True,reply_to_message_id=msg.message_id)
        raise ApplicationHandlerStop
    if not is_blacklisted(user.id):
        return
    if is_bot_cmd:
        await msg.reply_text(BLACKLIST_TEXT,parse_mode="HTML",reply_to_message_id=msg.message_id)
    raise ApplicationHandlerStop

async def blacklist_callback_gate(update:Update,context:ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    user=update.effective_user
    chat=update.effective_chat
    if not query or not user or _is_owner(user.id):
        return
    if chat and chat.type in ("group","supergroup") and is_group_blacklisted(chat.id):
        await query.answer("Bot is disabled in this group. Please contact the owner to reactivate it.",show_alert=True)
        raise ApplicationHandlerStop
    if is_blacklisted(user.id):
        await query.answer("You have been blacklisted.",show_alert=True)
        raise ApplicationHandlerStop

def _help_text():
    return (
        "<b>Blacklist Management</b>\n\n"
        "<b>User</b>\n"
        "<code>/blacklist add &lt;user_id&gt; [reason]</code>\n"
        "<code>/blacklist remove &lt;user_id&gt;</code>\n"
        "<code>/blacklist status &lt;user_id&gt;</code>\n"
        "<code>/blacklist list</code>\n\n"
        "<b>Group</b>\n"
        "<code>/blacklist group add [group_id] [reason]</code>\n"
        "<code>/blacklist group remove [group_id]</code>\n"
        "<code>/blacklist group status [group_id]</code>\n"
        "<code>/blacklist group list</code>\n\n"
        "In a group, you can omit <code>group_id</code> to target the current group."
    )

async def blacklist_cmd(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message
    user=update.effective_user
    bot=context.bot
    if not msg or not user or not _is_owner(user.id):
        return
    args=context.args or []
    if not args:
        return await msg.reply_text(_help_text(),parse_mode="HTML")
    action=str(args[0]).lower().strip()
    if action in ("group","chat"):
        if len(args)<2:
            return await msg.reply_text(_help_text(),parse_mode="HTML")
        sub=str(args[1]).lower().strip()
        if sub in ("add","ban","disable"):
            group_id,next_idx=_parse_group_id(msg,args,2)
            if not group_id:
                return await msg.reply_text("<b>Usage:</b> <code>/blacklist group add [group_id] [reason]</code>",parse_mode="HTML")
            reason=" ".join(args[next_idx:]).strip()
            fallback=(getattr(msg.chat,"title",None) or "") if getattr(msg,"chat",None) and msg.chat.id==group_id else ""
            title=await _resolve_group_title(bot,group_id,fallback)
            add_group(group_id,title=title,reason=reason,added_by=user.id)
            text=f"<b>Group blacklisted</b>\n\nGroup: <code>{html.escape(title)}</code>\nGroup ID: <code>{group_id}</code>"
            if reason:
                text+=f"\nReason: <code>{html.escape(reason)}</code>"
            return await msg.reply_text(text,parse_mode="HTML")
        if sub in ("remove","del","delete","unban","enable"):
            group_id,_=_parse_group_id(msg,args,2)
            if not group_id:
                return await msg.reply_text("<b>Usage:</b> <code>/blacklist group remove [group_id]</code>",parse_mode="HTML")
            removed=remove_group(group_id)
            return await msg.reply_text(f"<b>{'Group removed from blacklist' if removed else 'Group is not blacklisted'}</b>\n\nGroup ID: <code>{group_id}</code>",parse_mode="HTML")
        if sub in ("status","check"):
            group_id,_=_parse_group_id(msg,args,2)
            if not group_id:
                return await msg.reply_text("<b>Usage:</b> <code>/blacklist group status [group_id]</code>",parse_mode="HTML")
            row=get_group(group_id)
            if not row:
                return await msg.reply_text(f"<b>Group is not blacklisted</b>\n\nGroup ID: <code>{group_id}</code>",parse_mode="HTML")
            title=html.escape(row.get("title") or "-")
            reason=html.escape(row.get("reason") or "-")
            return await msg.reply_text(f"<b>Group is blacklisted</b>\n\nGroup: <code>{title}</code>\nGroup ID: <code>{group_id}</code>\nReason: <code>{reason}</code>",parse_mode="HTML")
        if sub in ("list","ls"):
            rows=list_groups(50)
            if not rows:
                return await msg.reply_text("<b>Group blacklist is empty.</b>",parse_mode="HTML")
            text="<b>Blacklisted Groups</b>\n\n"
            for i,row in enumerate(rows,1):
                title=html.escape(row.get("title") or "-")
                reason=html.escape(row.get("reason") or "-")
                text+=f"{i}. <code>{row['group_id']}</code> — <b>{title}</b>\n   Reason: <code>{reason}</code>\n"
            return await msg.reply_text(text[:3900],parse_mode="HTML")
        return await msg.reply_text(_help_text(),parse_mode="HTML")
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