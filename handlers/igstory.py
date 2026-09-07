import os
import html
import inspect
from io import BytesIO
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import ContextTypes
from handlers.join import require_join_or_block
from utils.http import get_http_session

NEOXR_IGSTORY_API = os.getenv("NEOXR_IGSTORY_API", "https://api.neoxr.eu/api/igs").strip()

async def _shared_http_session():
    session = get_http_session()
    if inspect.isawaitable(session):
        session = await session
    return session

async def _fetch_ig_stories(username: str) -> list[dict]:
    api_key = os.getenv("NEOXR_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("NEOXR_API_KEY is not set in the environment.")
    
    session = await _shared_http_session()
    params = {"username": username, "apikey": api_key}
    
    async with session.get(NEOXR_IGSTORY_API, params=params) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"API error {resp.status}: {text[:500]}")
        try:
            data = await resp.json(content_type=None)
        except Exception:
            raise RuntimeError(f"Invalid API JSON: {text[:500]}")
            
    if not data.get("status"):
        raise RuntimeError(data.get("message") or "No active stories found or account is private.")
    
    result = data.get("data")
    if not isinstance(result, list) or not result:
        raise RuntimeError("No stories available for this user.")
    return result

async def _download_media_to_buffer(url: str) -> BytesIO:
    session = await _shared_http_session()
    async with session.get(url) as resp:
        if resp.status != 200:
            raise RuntimeError("Failed to download media from CDN.")
        media_bytes = await resp.read()
        buffer = BytesIO(media_bytes)
        return buffer

async def igstory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join_or_block(update, context):
        return        
    msg = update.effective_message
    raw_query = " ".join(context.args).strip()    
    if not raw_query:
        return await msg.reply_text(
            "🔍 <b>Instagram Story Downloader</b>\n\n"
            "Usage format:\n"
            "<code>/igstory &lt;username&gt;</code>\n\n"
            "<i>Example: <code>/igstory hosico_cat</code></i>",
            parse_mode="HTML",
        )        
    username = raw_query.lstrip("@").split("/")[-1].split("?")[0].strip()
    status = await msg.reply_text(
        "<b>Fetching Instagram stories...</b>",
        reply_to_message_id=msg.message_id,
        parse_mode="HTML",
    )    
    try:
        stories = await _fetch_ig_stories(username)
        await status.edit_text(
            f"<b>Downloading {len(stories)} stories...</b>\n<i>(This may take a moment)</i>", 
            parse_mode="HTML"
        )
        chunk_size = 10
        for i in range(0, len(stories), chunk_size):
            chunk_items = stories[i:i+chunk_size]
            media_group = []
            open_buffers = []            
            for idx, item in enumerate(chunk_items):
                url = item.get("url")
                media_type = item.get("type", "jpg").lower()                
                if not url:
                    continue                    
                buffer = await _download_media_to_buffer(url)
                buffer.name = f"story_{i+idx}.{'mp4' if media_type == 'mp4' else 'jpg'}"
                open_buffers.append(buffer)
                caption = f"📱 <b>Story @{html.escape(username)}</b>" if i == 0 and idx == 0 else ""                
                if media_type == "mp4":
                    media_group.append(InputMediaVideo(media=buffer, caption=caption, parse_mode="HTML"))
                else:
                    media_group.append(InputMediaPhoto(media=buffer, caption=caption, parse_mode="HTML"))            
            if media_group:
                if len(media_group) == 1:
                    item = media_group[0]
                    if isinstance(item, InputMediaVideo):
                        await msg.reply_video(video=item.media, caption=item.caption, parse_mode="HTML")
                    else:
                        await msg.reply_photo(photo=item.media, caption=item.caption, parse_mode="HTML")
                else:
                    await msg.reply_media_group(media=media_group)                    
            for b in open_buffers:
                b.close()                
        await status.delete()

    except Exception as e:
        await status.edit_text(
            f"❌ <b>Failed to fetch stories</b>\n\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )
