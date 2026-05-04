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
from handlers.moderation.helpers import (
    mention_html,display_name,display_name_from_token,
    resolve_target_user_id,resolve_target_user_obj_for_display,
    resolve_user_obj_for_display_by_id,reply_in_topic
)

log=logging.getLogger(__name__)

BLACKLIST_TEXT="<b>You have been blacklisted.</b>\n\nYou cannot use this bot."
GROUP_BLACKLIST_TEXT=(
    "<b>Bot Disabled in This Group</b>\n\n"
    "To prevent spam, this bot has been disabled in this group.\n"
    "Please contact {owners} to reactivate it."
)
_CMD_RE=re.compile(r"^/([A-Za-z0-9_]{1,32})(?:@([A-Za-z0-9_]{5,32}))?(?:\s|$)")
_USER_RE=re.compile(r"^@?[A-Za-z0-9_]{5,32}$")
_GROUP_LINK_RE=re.compile(r"^(?:https?://)?t\.me/(?:c/)?([^/?#\s]+)",re.I)
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

def _clean_username_token(raw:str|None)->str:
    token=(raw or "").strip()
    if not token:
        return ""
    m=_GROUP_LINK_RE.match(token)
    if m:
        token=m.group(1)
    return token.strip().lstrip("@")

def _looks_like_user_token(raw:str|None)->bool:
    token=(raw or "").strip()
    if not token:
        return False
    if token.isdigit():
        return True
    return bool(_USER_RE.fullmatch(token))

def _looks_like_group_token(raw:str|None)->bool:
    token=(raw or "").strip()
    if not token:
        return False
    if re.fullmatch(r"-?\d+",token):
        return True
    if token.startswith("@"):
        return True
    return bool(_GROUP_LINK_RE.match(token))

def _fallback_user_name(token:str|None)->str:
    raw=(token or "").strip()
    if not raw:
        return "User"
    if raw.startswith("@"):
        return raw
    if _USER_RE.fullmatch(raw):
        return f"@{raw}"
    return display_name_from_token(raw) or "User"

async def _resolve_user_id(update:Update,context:ContextTypes.DEFAULT_TYPE,target_token:str|None):
    target_id=await resolve_target_user_id(update,context,target_token)
    if target_id:
        return int(target_id)
    username=_clean_username_token(target_token)
    if not username or not _USER_RE.fullmatch(username):
        return None
    try:
        obj=await context.bot.get_chat(f"@{username}")
        obj_id=getattr(obj,"id",None)
        if obj_id and int(obj_id)>0:
            return int(obj_id)
    except Exception as e:
        log.debug("Failed to resolve user username via get_chat | username=%s err=%r",username,e)
    return None

async def _resolve_user_display(update:Update,context:ContextTypes.DEFAULT_TYPE,target_id:int,target_token:str|None=None):
    obj=await resolve_target_user_obj_for_display(update,context,target_token)
    if not obj:
        obj=await resolve_user_obj_for_display_by_id(update,context,int(target_id))
    name=display_name(obj) or _fallback_user_name(target_token)
    return mention_html(int(target_id),name)

async def _resolve_user_label(update:Update,context:ContextTypes.DEFAULT_TYPE,user_id:int):
    obj=await resolve_user_obj_for_display_by_id(update,context,int(user_id))
    name=display_name(obj) or str(user_id)
    return mention_html(int(user_id),name)

async def _parse_user_target(update:Update,context:ContextTypes.DEFAULT_TYPE,args:list[str],start_idx:int=1):
    msg=update.effective_message
    token=None
    next_idx=start_idx
    has_reply=bool(msg and msg.reply_to_message and msg.reply_to_message.from_user)
    if len(args)>start_idx and (_looks_like_user_token(args[start_idx]) or not has_reply):
        token=str(args[start_idx]).strip()
        next_idx=start_idx+1
    target_id=await _resolve_user_id(update,context,token)
    if not target_id:
        return None,next_idx,None
    who=await _resolve_user_display(update,context,int(target_id),token)
    return int(target_id),next_idx,who

async def _resolve_group_id(bot,token:str|None):
    raw=(token or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"-?\d+",raw):
        return int(raw)
    username=_clean_username_token(raw)
    if not username:
        return None
    try:
        chat=await bot.get_chat(f"@{username}")
        chat_id=getattr(chat,"id",None)
        return int(chat_id) if chat_id is not None else None
    except Exception as e:
        log.debug("Failed to resolve group username | token=%s err=%r",raw,e)
        return None

def _current_group_id(msg):
    chat=getattr(msg,"chat",None)
    if chat and chat.type in ("group","supergroup"):
        return int(chat.id)
    return None

async def _parse_group_target(msg,bot,args:list[str],start_idx:int=2):
    if len(args)>start_idx and _looks_like_group_token(args[start_idx]):
        group_id=await _resolve_group_id(bot,args[start_idx])
        return group_id,start_idx+1
    return _current_group_id(msg),start_idx

async def _resolve_group_title(bot,group_id:int,fallback:str=""):
    try:
        chat=await bot.get_chat(group_id)
        return (getattr(chat,"title",None) or getattr(chat,"username",None) or fallback or str(group_id)).strip()
    except Exception as e:
        log.warning("Failed to resolve group title | group_id=%s error=%s",group_id,e)
        return fallback or str(group_id)

async def _group_label(bot,group_id:int,fallback:str=""):
    title=(fallback or "").strip()
    if not title or title==str(group_id):
        title=await _resolve_group_title(bot,group_id,title)
    return html.escape(title or str(group_id))

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
            await reply_in_topic(msg,await _group_blacklist_text(context),parse_mode="HTML",disable_web_page_preview=True,reply_to_message_id=msg.message_id)
        raise ApplicationHandlerStop
    if not is_blacklisted(user.id):
        return
    if is_bot_cmd:
        await reply_in_topic(msg,BLACKLIST_TEXT,parse_mode="HTML",reply_to_message_id=msg.message_id)
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
        "<code>/blacklist add &lt;user_id|@username&gt; [reason]</code>\n"
        "<code>/blacklist remove &lt;user_id|@username&gt;</code>\n"
        "<code>/blacklist status &lt;user_id|@username&gt;</code>\n"
        "<code>/blacklist list</code>\n\n"
        "<b>Group</b>\n"
        "<code>/blacklist group add [group_id|@username] [reason]</code>\n"
        "<code>/blacklist group remove [group_id|@username]</code>\n"
        "<code>/blacklist group status [group_id|@username]</code>\n"
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
        return await reply_in_topic(msg,_help_text(),parse_mode="HTML")
    action=str(args[0]).lower().strip()
    if action in ("group","chat"):
        if len(args)<2:
            return await reply_in_topic(msg,_help_text(),parse_mode="HTML")
        sub=str(args[1]).lower().strip()
        if sub in ("add","ban","disable"):
            group_id,next_idx=await _parse_group_target(msg,bot,args,2)
            if not group_id:
                return await reply_in_topic(msg,"<b>Usage:</b> <code>/blacklist group add [group_id|@username] [reason]</code>",parse_mode="HTML")
            reason=" ".join(args[next_idx:]).strip()
            fallback=(getattr(msg.chat,"title",None) or "") if getattr(msg,"chat",None) and msg.chat.id==group_id else ""
            title=await _resolve_group_title(bot,group_id,fallback)
            add_group(group_id,title=title,reason=reason,added_by=user.id)
            text=f"<b>Group blacklisted</b>\n\n<b>Group:</b> {html.escape(title)}\n<b>Group ID:</b> <code>{group_id}</code>"
            if reason:
                text+=f"\n<b>Reason:</b> <code>{html.escape(reason)}</code>"
            return await reply_in_topic(msg,text,parse_mode="HTML")
        if sub in ("remove","del","delete","unban","enable"):
            group_id,_=await _parse_group_target(msg,bot,args,2)
            if not group_id:
                return await reply_in_topic(msg,"<b>Usage:</b> <code>/blacklist group remove [group_id|@username]</code>",parse_mode="HTML")
            row=get_group(group_id)
            title=await _group_label(bot,group_id,(row or {}).get("title") or "")
            removed=remove_group(group_id)
            return await reply_in_topic(
                msg,
                f"<b>{'Group removed from blacklist' if removed else 'Group is not blacklisted'}</b>\n\n<b>Group:</b> {title}\n<b>Group ID:</b> <code>{group_id}</code>",
                parse_mode="HTML",
            )
        if sub in ("status","check"):
            group_id,_=await _parse_group_target(msg,bot,args,2)
            if not group_id:
                return await reply_in_topic(msg,"<b>Usage:</b> <code>/blacklist group status [group_id|@username]</code>",parse_mode="HTML")
            row=get_group(group_id)
            if not row:
                title=await _group_label(bot,group_id,"")
                return await reply_in_topic(msg,f"<b>Group is not blacklisted</b>\n\n<b>Group:</b> {title}\n<b>Group ID:</b> <code>{group_id}</code>",parse_mode="HTML")
            title=await _group_label(bot,group_id,row.get("title") or "")
            reason=html.escape(row.get("reason") or "-")
            return await reply_in_topic(msg,f"<b>Group is blacklisted</b>\n\n<b>Group:</b> {title}\n<b>Group ID:</b> <code>{group_id}</code>\n<b>Reason:</b> <code>{reason}</code>",parse_mode="HTML")
        if sub in ("list","ls"):
            rows=list_groups(50)
            if not rows:
                return await reply_in_topic(msg,"<b>Group blacklist is empty.</b>",parse_mode="HTML")
            lines=["<b>Blacklisted Groups</b>",""]
            for i,row in enumerate(rows,1):
                group_id=int(row["group_id"])
                title=await _group_label(bot,group_id,row.get("title") or "")
                reason=html.escape(row.get("reason") or "-")
                lines.append(f"{i}. <b>{title}</b>")
                lines.append(f"   ID: <code>{group_id}</code>")
                lines.append(f"   Reason: <code>{reason}</code>")
            return await reply_in_topic(msg,"\n".join(lines)[:3900],parse_mode="HTML",disable_web_page_preview=True)
        return await reply_in_topic(msg,_help_text(),parse_mode="HTML")
    if action in ("add","ban"):
        target_id,next_idx,who=await _parse_user_target(update,context,args,1)
        if not target_id:
            return await reply_in_topic(msg,"<b>Usage:</b> <code>/blacklist add &lt;user_id|@username&gt; [reason]</code>",parse_mode="HTML")
        if _is_owner(target_id):
            return await reply_in_topic(msg,"<b>Cannot blacklist owner.</b>",parse_mode="HTML")
        reason=" ".join(args[next_idx:]).strip()
        add_user(target_id,reason=reason,added_by=user.id)
        text=f"<b>User blacklisted</b>\n\n<b>User:</b> {who}\n<b>User ID:</b> <code>{target_id}</code>"
        if reason:
            text+=f"\n<b>Reason:</b> <code>{html.escape(reason)}</code>"
        return await reply_in_topic(msg,text,parse_mode="HTML",disable_web_page_preview=True)
    if action in ("remove","del","delete","unban"):
        target_id,_,who=await _parse_user_target(update,context,args,1)
        if not target_id:
            return await reply_in_topic(msg,"<b>Usage:</b> <code>/blacklist remove &lt;user_id|@username&gt;</code>",parse_mode="HTML")
        removed=remove_user(target_id)
        return await reply_in_topic(msg,f"<b>{'User removed from blacklist' if removed else 'User is not blacklisted'}</b>\n\n<b>User:</b> {who}\n<b>User ID:</b> <code>{target_id}</code>",parse_mode="HTML",disable_web_page_preview=True)
    if action in ("status","check"):
        target_id,_,who=await _parse_user_target(update,context,args,1)
        if not target_id:
            return await reply_in_topic(msg,"<b>Usage:</b> <code>/blacklist status &lt;user_id|@username&gt;</code>",parse_mode="HTML")
        row=get_user(target_id)
        if not row:
            return await reply_in_topic(msg,f"<b>User is not blacklisted</b>\n\n<b>User:</b> {who}\n<b>User ID:</b> <code>{target_id}</code>",parse_mode="HTML",disable_web_page_preview=True)
        reason=html.escape(row.get("reason") or "-")
        return await reply_in_topic(msg,f"<b>User is blacklisted</b>\n\n<b>User:</b> {who}\n<b>User ID:</b> <code>{target_id}</code>\n<b>Reason:</b> <code>{reason}</code>",parse_mode="HTML",disable_web_page_preview=True)
    if action in ("list","ls"):
        rows=list_users(50)
        if not rows:
            return await reply_in_topic(msg,"<b>Blacklist is empty.</b>",parse_mode="HTML")
        lines=["<b>Blacklisted Users</b>",""]
        for i,row in enumerate(rows,1):
            user_id=int(row["user_id"])
            who=await _resolve_user_label(update,context,user_id)
            reason=html.escape(row.get("reason") or "-")
            lines.append(f"{i}. <b>{who}</b>")
            lines.append(f"   ID: <code>{user_id}</code>")
            lines.append(f"   Reason: <code>{reason}</code>")
        return await reply_in_topic(msg,"\n".join(lines)[:3900],parse_mode="HTML",disable_web_page_preview=True)
    return await reply_in_topic(msg,_help_text(),parse_mode="HTML")