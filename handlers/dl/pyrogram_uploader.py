import os
import time
import asyncio
import logging
from utils.config import BOT_TOKEN
from telegram.error import RetryAfter
from .utils import progress_bar

log=logging.getLogger(__name__)
try:
    from pyrogram import Client,enums,errors
except Exception as e:
    Client=None
    enums=None
    errors=None
    log.warning("Pyrofork import failed | err=%r",e)

_CLIENT=None
_CLIENT_LOCK=asyncio.Lock()
_PROGRESS_LOCKS={}
_ENABLED=os.getenv("PYROGRAM_UPLOAD","1").lower() not in ("0","false","off","no")
_SESSION_NAME=os.getenv("PYROGRAM_SESSION","pyrogram_bot")
_WORKDIR=os.getenv("PYROGRAM_WORKDIR","data")
_NO_UPDATES=os.getenv("PYROGRAM_NO_UPDATES","0").lower() in ("1","true","on","yes")
_PROGRESS_MIN_BYTES=int(os.getenv("PYROGRAM_PROGRESS_MIN_BYTES",str(5*1024*1024)))
_PROGRESS_SMALL_LIMIT=int(os.getenv("PYROGRAM_PROGRESS_SMALL_LIMIT",str(100*1024*1024)))
_PROGRESS_SMALL_INTERVAL=float(os.getenv("PYROGRAM_PROGRESS_SMALL_INTERVAL","3.0"))
_PROGRESS_LARGE_INTERVAL=float(os.getenv("PYROGRAM_PROGRESS_LARGE_INTERVAL","10.0"))
_PROGRESS_STEP=float(os.getenv("PYROGRAM_PROGRESS_STEP","5"))

def _format_size(num:int|float)->str:
    value=float(num or 0)
    for unit in ("B","KB","MB","GB"):
        if value<1024 or unit=="GB":
            return f"{int(value)} {unit}" if unit=="B" else f"{value:.1f} {unit}"
        value/=1024
    return f"{value:.1f} GB"

def _format_eta(seconds:int|float)->str:
    seconds=int(max(float(seconds or 0),0))
    if seconds<=0:
        return "-"
    h,rem=divmod(seconds,3600)
    m,s=divmod(rem,60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

def _progress_interval(file_size:int)->float:
    return _PROGRESS_SMALL_INTERVAL if file_size<_PROGRESS_SMALL_LIMIT else _PROGRESS_LARGE_INTERVAL

def _get_progress_lock(key):
    lock=_PROGRESS_LOCKS.get(key)
    if lock is None:
        lock=asyncio.Lock()
        _PROGRESS_LOCKS[key]=lock
    return lock

def _drop_progress_lock(key):
    lock=_PROGRESS_LOCKS.get(key)
    if lock and not lock.locked():
        _PROGRESS_LOCKS.pop(key,None)

def _is_reply_not_found_error(exc:Exception)->bool:
    text=(str(exc) or "").lower()
    keys=("replied message not found","message to be replied not found","reply message not found","reply_to_message_id")
    return any(k in text for k in keys)

def _flood_wait_seconds(exc:Exception)->int:
    if errors and isinstance(exc,getattr(errors,"FloodWait",())):
        return max(int(getattr(exc,"value",1)),1)
    return 0

async def _edit_caption_via_bot_api(bot,chat_id,message_id,caption):
    if not bot or not chat_id or not message_id or not caption:
        log.warning("Pyrofork caption edit skipped | chat_id=%s message_id=%s caption=%s",chat_id,message_id,bool(caption))
        return
    for attempt in range(2):
        try:
            await bot.edit_message_caption(chat_id=chat_id,message_id=message_id,caption=caption,parse_mode="HTML")
            log.info("Pyrofork caption edited via Bot API | chat_id=%s message_id=%s",chat_id,message_id)
            return
        except RetryAfter as e:
            wait=max(int(getattr(e,"retry_after",1)),1)
            log.warning("Pyrofork caption edit RetryAfter | chat_id=%s wait=%s attempt=%s",chat_id,wait,attempt+1)
            await asyncio.sleep(wait+1)
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return
            log.warning("Failed to edit Pyrofork caption via Bot API | chat_id=%s message_id=%s attempt=%s err=%r",chat_id,message_id,attempt+1,e)
            return

async def _disconnect_client(client,label:str):
    try:
        if client and client.is_connected:
            await client.stop()
            log.info("Pyrofork uploader disconnected | reason=%s",label)
    except Exception as e:
        log.warning("Pyrofork uploader disconnect failed | reason=%s err=%r",label,e)

async def _get_client():
    global _CLIENT
    if not _ENABLED:
        raise RuntimeError("Pyrofork upload disabled")
    if Client is None:
        raise RuntimeError("Pyrofork is not installed")
    api_id=os.getenv("TG_API_ID") or os.getenv("API_ID")
    api_hash=os.getenv("TG_API_HASH") or os.getenv("API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("TG_API_ID/TG_API_HASH is not configured")
    async with _CLIENT_LOCK:
        if _CLIENT and _CLIENT.is_connected:
            return _CLIENT
        if _CLIENT:
            await _disconnect_client(_CLIENT,"reconnect")
            _CLIENT=None
        os.makedirs(_WORKDIR,exist_ok=True)
        parse_mode=enums.ParseMode.HTML if enums else "html"
        _CLIENT=Client(
            _SESSION_NAME,
            api_id=int(api_id),
            api_hash=api_hash,
            bot_token=BOT_TOKEN,
            workdir=_WORKDIR,
            no_updates=_NO_UPDATES,
            parse_mode=parse_mode,
        )
        await _CLIENT.start()
        log.info("Pyrofork uploader ready | session=%s workdir=%s no_updates=%s",_SESSION_NAME,_WORKDIR,_NO_UPDATES)
        return _CLIENT

async def _resolve_pyrogram_chat_id(bot,client,chat_id):
    try:
        await client.resolve_peer(chat_id)
        return chat_id
    except Exception as e:
        log.warning("Pyrofork resolve_peer by id failed | chat_id=%s err=%r",chat_id,e)
    try:
        chat=await client.get_chat(chat_id)
        cid=getattr(chat,"id",None)
        if cid is not None:
            await client.resolve_peer(cid)
            log.info("Pyrofork peer resolved by get_chat | chat_id=%s resolved=%s",chat_id,cid)
            return cid
    except Exception as e:
        log.warning("Pyrofork get_chat resolve failed | chat_id=%s err=%r",chat_id,e)
    try:
        tg_chat=await bot.get_chat(chat_id)
        username=(getattr(tg_chat,"username",None) or "").strip()
        if username:
            target=f"@{username}"
            await client.resolve_peer(target)
            log.info("Pyrofork peer resolved by username | chat_id=%s username=%s",chat_id,target)
            return target
    except Exception as e:
        log.warning("Pyrofork username resolve failed | chat_id=%s err=%r",chat_id,e)
    try:
        async for dialog in client.get_dialogs(limit=500):
            dchat=getattr(dialog,"chat",None)
            did=getattr(dchat,"id",None)
            if did is not None and int(did)==int(chat_id):
                await client.resolve_peer(did)
                log.info("Pyrofork peer resolved from dialogs | chat_id=%s",chat_id)
                return did
    except Exception as e:
        log.warning("Pyrofork dialogs resolve failed | chat_id=%s err=%r",chat_id,e)
    raise RuntimeError(f"Pyrofork peer not resolved: {chat_id}")

async def warmup_pyrogram_uploader(app=None):
    if not _ENABLED:
        log.info("Pyrofork uploader warmup skipped | disabled")
        return
    try:
        await _get_client()
        log.info("Pyrofork uploader warmup done")
    except Exception as e:
        log.warning("Pyrofork uploader warmup failed | err=%r",e)

async def shutdown_pyrogram_uploader(app=None):
    global _CLIENT
    await _disconnect_client(_CLIENT,"shutdown")
    _CLIENT=None

async def _safe_edit_upload(bot,chat_id,message_id,current,total,started,label="Pyrofork uploading video"):
    key=(int(chat_id),int(message_id))
    lock=_get_progress_lock(key)
    async with lock:
        try:
            current=max(int(current or 0),0)
            total=max(int(total or 0),0)
            percent=(current/total*100) if total else 0
            elapsed=max(time.monotonic()-started,0.001)
            speed=current/elapsed
            remaining=max(total-current,0)
            eta=(remaining/speed) if speed>0 and total else 0
            text=(
                f"<b>{label}...</b>\n\n"
                f"<code>{progress_bar(percent)}</code>\n"
                f"<code>{_format_size(current)}/{_format_size(total)}</code>\n"
                f"<code>Speed: {_format_size(speed)}/s</code>\n"
                f"<code>ETA: {_format_eta(eta)}</code>"
            )
            await bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,parse_mode="HTML")
            log.info("Pyrofork upload progress | chat_id=%s %.1f%% %s/%s speed=%s/s eta=%s",chat_id,percent,_format_size(current),_format_size(total),_format_size(speed),_format_eta(eta))
        except RetryAfter as e:
            wait=max(int(getattr(e,"retry_after",1)),1)
            log.warning("Pyrofork progress RetryAfter | chat_id=%s wait=%s",chat_id,wait)
            await asyncio.sleep(wait+1)
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                log.warning("Pyrofork upload progress edit failed | chat_id=%s err=%r",chat_id,e)

def _make_progress_callback(bot,chat_id,status_msg_id,file_size,started,show_progress,interval,label):
    state={"last_ts":0.0,"last_pct":-1.0,"task":None}
    loop=asyncio.get_running_loop()
    def progress_callback(current,total):
        if not show_progress or not total:
            return
        if file_size and total<file_size*0.8:
            return
        now=time.monotonic()
        pct=(current/total*100) if total else 0
        if pct<100 and now-state["last_ts"]<interval:
            return
        if pct<100 and state["last_pct"]>=0 and pct-state["last_pct"]<_PROGRESS_STEP:
            return
        def schedule():
            if state["task"] and not state["task"].done():
                return
            state["last_ts"]=now
            state["last_pct"]=pct
            state["task"]=loop.create_task(_safe_edit_upload(bot,chat_id,status_msg_id,current,total,started,label=label))
        loop.call_soon_threadsafe(schedule)
    return progress_callback,state

async def _wait_last_progress_task(state:dict):
    task=state.get("task")
    if task:
        await asyncio.gather(task,return_exceptions=True)

async def _send_video(client,kwargs):
    try:
        return await client.send_video(**kwargs)
    except TypeError as e:
        text=str(e)
        if "message_thread_id" in text and "message_thread_id" in kwargs:
            kwargs.pop("message_thread_id",None)
            return await client.send_video(**kwargs)
        if "thumb" in text and "thumb" in kwargs:
            kwargs["thumbnail"]=kwargs.pop("thumb")
            return await client.send_video(**kwargs)
        raise
    except Exception as e:
        wait=_flood_wait_seconds(e)
        if wait>0:
            log.warning("Pyrofork send_video FloodWait | wait=%s",wait)
            await asyncio.sleep(wait+1)
            return await client.send_video(**kwargs)
        raise

async def try_send_video_via_pyrogram(bot,chat_id,status_msg_id,file_path,caption,reply_to=None,message_thread_id=None,duration=None,width=None,height=None,thumb_path=None):
    if not _ENABLED:
        return False
    if not file_path or not os.path.exists(file_path):
        return False
    key=(int(chat_id),int(status_msg_id))
    file_size=os.path.getsize(file_path)
    show_progress=file_size>=_PROGRESS_MIN_BYTES
    interval=_progress_interval(file_size)
    started=time.monotonic()
    state={"task":None}
    try:
        client=await _get_client()
        target_chat_id=await _resolve_pyrogram_chat_id(bot,client,chat_id)
        progress_callback,state=_make_progress_callback(bot,chat_id,status_msg_id,file_size,started,show_progress,interval,"Pyrofork uploading video")
        kwargs={
            "chat_id":chat_id,
            "video":file_path,
            "caption":caption,
            "supports_streaming":True,
            "disable_notification":True,
            "reply_to_message_id":reply_to,
            "progress":progress_callback,
        }
        if message_thread_id:
            kwargs["message_thread_id"]=message_thread_id
        if duration:
            kwargs["duration"]=int(duration)
        if width:
            kwargs["width"]=int(width)
        if height:
            kwargs["height"]=int(height)
        if thumb_path and os.path.exists(thumb_path):
            kwargs["thumb"]=thumb_path
        log.info(
            "Pyrofork upload start | chat_id=%s target=%s file=%s size=%s progress=%s interval=%.1fs",
            chat_id,
            target_chat_id,
            os.path.basename(file_path),
            _format_size(file_size),
            show_progress,
            interval,
        )
        try:
            sent=await _send_video(client,kwargs)
        except Exception as e:
            if reply_to and _is_reply_not_found_error(e):
                kwargs.pop("reply_to_message_id",None)
                sent=await _send_video(client,kwargs)
            else:
                raise
        await _wait_last_progress_task(state)
        elapsed=time.monotonic()-started
        speed=file_size/max(elapsed,0.001)
        log.info("Pyrofork send done | chat_id=%s file=%s size=%s elapsed=%.2fs avg_speed=%s/s",chat_id,os.path.basename(file_path),_format_size(file_size),elapsed,_format_size(speed))
        return True
    except Exception as e:
        log.warning("Pyrofork upload failed, fallback to PTB | chat_id=%s file=%s err=%r",chat_id,os.path.basename(file_path),e)
        return False
    finally:
        await _wait_last_progress_task(state)
        _drop_progress_lock(key)