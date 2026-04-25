import io
import os
import re
import asyncio
import aiohttp
from collections import defaultdict, deque
from telegram import Update
from telegram.ext import ContextTypes

QUOTE_API_URI = os.getenv("QUOTE_API_URI")
QUOTE_MESSAGE_CACHE = defaultdict(lambda: deque(maxlen=500))

def _cache_key(message):
    return int(getattr(message, "chat_id", 0) or 0), getattr(message, "message_thread_id", None)

async def quote_cache_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    text = getattr(msg, "text", None) or getattr(msg, "caption", None) or ""
    if not text.strip() or text.strip().startswith("/"):
        return
    QUOTE_MESSAGE_CACHE[_cache_key(msg)].append(msg)

def _entity_type_value(entity_type):
    if hasattr(entity_type, "value"):
        return entity_type.value
    return str(entity_type).replace("MessageEntityType.", "").lower()

def _entities_to_quote(entities):
    out = []
    for ent in entities or []:
        item = {"offset": int(ent.offset), "length": int(ent.length), "type": _entity_type_value(ent.type)}
        if getattr(ent, "url", None):
            item["url"] = ent.url
        if getattr(ent, "language", None):
            item["language"] = ent.language
        if getattr(ent, "custom_emoji_id", None):
            item["custom_emoji_id"] = ent.custom_emoji_id
        out.append(item)
    return out

def _pick_color(arg: str | None) -> str:
    color_map = {
        "black": "//#292232", "dark": "//#292232", "purple": "//#292232", "white": "#ffffff",
        "gray": "#3a3f44", "grey": "#3a3f44", "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3",
        "silver": "#c0c0c0", "red": "#ff0000", "darkred": "#8b0000", "maroon": "#800000",
        "crimson": "#dc143c", "tomato": "#ff6347", "coral": "#ff7f50", "salmon": "#fa8072",
        "orangered": "#ff4500", "pink": "#ea80ff", "hotpink": "#ff69b4", "deeppink": "#ff1493",
        "lightpink": "#ffb6c1", "rose": "#ff007f", "fuchsia": "#ff00ff", "magenta": "#ff00ff",
        "blue": "#0000ff", "darkblue": "#00008b", "navy": "#000080", "royalblue": "#4169e1",
        "dodgerblue": "#1e90ff", "deepskyblue": "#00bfff", "skyblue": "#87ceeb",
        "lightskyblue": "#87cefa", "steelblue": "#4682b4", "cyan": "#00ffff", "aqua": "#00ffff",
        "teal": "#008080", "turquoise": "#40e0d0", "green": "#2fbf71", "darkgreen": "#006400",
        "lime": "#00ff00", "limegreen": "#32cd32", "lightgreen": "#90ee90", "forestgreen": "#228b22",
        "seagreen": "#2e8b57", "springgreen": "#00ff7f", "olive": "#808000", "yellow": "#ffff00",
        "gold": "#ffd700", "goldenrod": "#daa520", "orange": "#ffa500", "darkorange": "#ff8c00",
        "amber": "#ffbf00", "khaki": "#f0e68c", "brown": "#8b4513", "saddlebrown": "#8b4513",
        "chocolate": "#d2691e", "peru": "#cd853f", "tan": "#d2b48c", "beige": "#f5f5dc",
        "indigo": "#4b0082", "violet": "#8a2be2", "plum": "#dda0dd", "lavender": "#e6e6fa",
        "transparent": "rgba(0,0,0,0)", "random": "random",
    }
    arg = (arg or "").strip().lower()
    if not arg:
        return "//#292232"
    if arg in color_map:
        return color_map[arg]
    if arg.startswith("#") and len(arg) in (4, 7):
        return arg
    return "//#292232"

def _get_sender_obj(message):
    return getattr(message, "from_user", None) or getattr(message, "sender_chat", None)

def _build_from_payload(sender):
    if not sender:
        return {"id": 0, "name": "User", "first_name": "User", "last_name": "", "username": None}
    if hasattr(sender, "title"):
        title = getattr(sender, "title", None) or "User"
        return {"id": int(getattr(sender, "id", 0) or 0), "name": title, "first_name": title, "last_name": "", "username": getattr(sender, "username", None)}
    first = getattr(sender, "first_name", None) or ""
    last = getattr(sender, "last_name", None) or ""
    username = getattr(sender, "username", None)
    name = f"{first} {last}".strip() or (f"@{username}" if username else "User")
    return {"id": int(getattr(sender, "id", 0) or 0), "name": name, "first_name": first or name, "last_name": last, "username": username}

def _get_message_text_and_entities(message):
    text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    entities = message.entities if getattr(message, "text", None) else message.caption_entities
    return text, entities

def _build_reply_payload(message):
    reply = getattr(message, "reply_to_message", None)
    if not reply:
        return {}
    reply_sender = _get_sender_obj(reply)
    reply_text, reply_entities = _get_message_text_and_entities(reply)
    if not reply_text:
        return {}
    if len(reply_text) > 200:
        reply_text = reply_text[:200].rstrip() + "..."
    if reply_sender and hasattr(reply_sender, "title"):
        reply_name = getattr(reply_sender, "title", None) or "User"
        reply_chat_id = int(getattr(reply_sender, "id", 0) or 0)
    else:
        first = (getattr(reply_sender, "first_name", "") or "").strip()
        last = (getattr(reply_sender, "last_name", "") or "").strip()
        username = (getattr(reply_sender, "username", "") or "").strip()
        reply_name = f"{first} {last}".strip() or (f"@{username}" if username else "User")
        reply_chat_id = int(getattr(reply_sender, "id", 0) or 0)
    return {"name": reply_name, "chatId": reply_chat_id, "text": reply_text, "entities": _entities_to_quote(reply_entities)}

def _collect_quote_messages(command_message, start_message, count: int):
    count = max(1, min(int(count or 1), 10))
    cached = list(QUOTE_MESSAGE_CACHE.get(_cache_key(command_message)) or [])
    start_id = int(getattr(start_message, "message_id", 0) or 0)
    picked = [start_message]
    seen = {start_id}
    for item in cached:
        item_id = int(getattr(item, "message_id", 0) or 0)
        if item_id <= start_id or item_id in seen:
            continue
        picked.append(item)
        seen.add(item_id)
        if len(picked) >= count:
            break
    return picked[:count]

def _parse_args(args: list[str], command_text: str = ""):
    count = 1
    include_reply = False
    color_arg = None
    m = re.match(r"^/(?:q|quote)(\d{1,2})?(?:@\w+)?(?:\s|$)", command_text or "", flags=re.I)
    if m and m.group(1):
        count = max(1, min(int(m.group(1)), 10))
    for raw in args or []:
        arg = (raw or "").strip().lower()
        if not arg:
            continue
        if arg.isdigit():
            count = max(1, min(int(arg), 10))
            continue
        m = re.match(r"^(?:q|quote)(\d{1,2})$", arg, flags=re.I)
        if m:
            count = max(1, min(int(m.group(1)), 10))
            continue
        if arg in ("r", "reply"):
            include_reply = True
            continue
        color_arg = arg
    return count, include_reply, color_arg

async def _generate_quote_sticker(session, bot_token: str, payload: dict):
    async with session.post(f"{QUOTE_API_URI.rstrip('/')}/generate.webp?botToken={bot_token}", json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        if resp.status != 200:
            err = await resp.text()
            raise RuntimeError(f"{resp.status} {err[:300]}")
        return await resp.read()

async def q_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    if not QUOTE_API_URI:
        return await msg.reply_text("QUOTE_API_URI is not configured.")
    target = msg.reply_to_message
    if not target:
        return await msg.reply_text("Reply to a message to create a sticker.")
    command_text = msg.text or msg.caption or ""
    count, include_reply, color_arg = _parse_args(context.args or [], command_text)
    background_color = _pick_color(color_arg)
    messages = []
    for _ in range(8):
        messages = _collect_quote_messages(msg, target, count)
        if len(messages) >= count:
            break
        await asyncio.sleep(0.15)
    if not messages:
        return await msg.reply_text("Message not found.")
    valid_messages = []
    for item in messages:
        text, entities = _get_message_text_and_entities(item)
        if text:
            valid_messages.append((item, text, entities))
    if not valid_messages:
        return await msg.reply_text("The selected message has no text.")
    wait = await msg.reply_text(f"Creating {len(valid_messages)} sticker(s)...")
    kwargs = {}
    if getattr(msg, "message_thread_id", None):
        kwargs["message_thread_id"] = msg.message_thread_id
    try:
        async with aiohttp.ClientSession() as session:
            for idx, (item, text, entities) in enumerate(valid_messages, start=1):
                sender = _get_sender_obj(item)
                from_payload = _build_from_payload(sender)
                payload = {
                    "type": "quote",
                    "format": "webp",
                    "backgroundColor": background_color,
                    "width": 512,
                    "height": 768,
                    "scale": 2,
                    "emojiBrand": "apple",
                    "messages": [{
                        "chatId": int(from_payload["id"] or 0),
                        "avatar": True,
                        "from": from_payload,
                        "text": text,
                        "entities": _entities_to_quote(entities),
                        "replyMessage": _build_reply_payload(item) if include_reply else {},
                    }],
                }
                image_bytes = await _generate_quote_sticker(session, context.bot.token, payload)
                sticker = io.BytesIO(image_bytes)
                sticker.name = f"quote_{idx}.webp"
                await context.bot.send_sticker(chat_id=msg.chat_id, sticker=sticker, reply_to_message_id=target.message_id, **kwargs)
        await wait.delete()
    except Exception as e:
        await wait.edit_text(f"Failed to create sticker: {e}")