import os
import time
import uuid
import html
import aiohttp

from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from telegram.ext import ContextTypes

from utils.http import get_http_session

#google search 
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
GSEARCH_CACHE = {}
MAX_GSEARCH_CACHE = 50         
GSEARCH_CACHE_TTL = 300      

#gsearch request
async def google_search(query: str, page: int = 0, limit: int = 5):
    try:
        start = page * limit + 1
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_CSE_ID,
            "q": query,
            "num": limit,
            "start": start,
        }

        session = await get_http_session()
        async with session.get(url, params=params, timeout=20) as resp:
            if resp.status != 200:
                return False, await resp.text()
            data = await resp.json()

        results = []
        for it in data.get("items", []):
            results.append({
                "title": it.get("title", ""),
                "snippet": it.get("snippet", ""),
                "link": it.get("link", ""),
            })

        return True, results

    except Exception as e:
        return False, str(e)

#inline keyboard
def gsearch_keyboard(search_id: str, page: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"gsearch:{search_id}:{page-1}"),
            InlineKeyboardButton(f"📄 {page+1}", callback_data="noop"),
            InlineKeyboardButton("Next ➡️", callback_data=f"gsearch:{search_id}:{page+1}"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data=f"gsearch:close:{search_id}")
        ]
    ])

#gsearch cmd
async def gsearch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "🔍 <b>Google Search</b>\n\n"
            "<code>/gsearch python asyncio</code>",
            parse_mode="HTML"
        )

    query = " ".join(context.args)
    search_id = uuid.uuid4().hex[:8]

    if len(GSEARCH_CACHE) >= MAX_GSEARCH_CACHE:
        GSEARCH_CACHE.pop(next(iter(GSEARCH_CACHE)))

    GSEARCH_CACHE[search_id] = {
        "query": query,
        "page": 0,
        "user": update.effective_user.id,
        "ts": time.time(),
    }

    msg = await update.message.reply_text("🔍 Lagi nyari di Google...")

    ok, res = await google_search(query, 0)
    if not ok:
        return await msg.edit_text(f"❌ Error\n<code>{res}</code>", parse_mode="HTML")

    if not res:
        return await msg.edit_text("❌ Ga nemu hasil.")

    text = f"🔍 <b>Google Search:</b> <i>{html.escape(query)}</i>\n\n"
    for i, r in enumerate(res, start=1):
        text += (
            f"<b>{i}. {html.escape(r['title'])}</b>\n"
            f"{html.escape(r['snippet'])}\n"
            f"{r['link']}\n\n"
        )

    await msg.edit_text(
        text[:4096],
        parse_mode="HTML",
        reply_markup=gsearch_keyboard(search_id, 0),
        disable_web_page_preview=False
    )

#callback
async def gsearch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "noop":
        return

    _, a, b = q.data.split(":", 2)

    if a == "close":
        GSEARCH_CACHE.pop(b, None)
        return await q.message.delete()

    search_id = a
    page = int(b)

    data = GSEARCH_CACHE.get(search_id)
    if not data:
        return await q.message.edit_text("❌ Data search expired.")

    if time.time() - data["ts"] > GSEARCH_CACHE_TTL:
        GSEARCH_CACHE.pop(search_id, None)
        return await q.message.edit_text("❌ Search expired.")

    if q.from_user.id != data["user"]:
        return await q.answer("Ini bukan search lu dongo", show_alert=True)

    if page < 0:
        return

    query = data["query"]
    ok, res = await google_search(query, page)
    if not ok or not res:
        return await q.message.edit_text("❌ Gada hasil lagi.")

    data["page"] = page
    data["ts"] = time.time()

    text = f"🔍 <b>Google Search:</b> <i>{html.escape(query)}</i>\n\n"
    for i, r in enumerate(res, start=1 + page * 5):
        text += (
            f"<b>{i}. {html.escape(r['title'])}</b>\n"
            f"{html.escape(r['snippet'])}\n"
            f"{r['link']}\n\n"
        )

    await q.message.edit_text(
        text[:4096],
        parse_mode="HTML",
        reply_markup=gsearch_keyboard(search_id, page),
        disable_web_page_preview=False
    )
                   
