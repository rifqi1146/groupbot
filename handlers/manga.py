import logging
import aiohttp
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

MANGADEX_API = "https://api.mangadex.org"
UPLOADS_URL = "https://uploads.mangadex.org"

async def fetch_json(url, params=None):
    headers = {"User-Agent": "MangaBot/2.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                return await response.json()
            return None

async def fetch_image_bytes(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://mangadex.org/"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.read()
                return None
    except Exception as e:
        log.error(f"Error fetch gambar: {e}")
        return None

async def get_chapter_context(chapter_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Mengambil Info Chapter (Judul, Bahasa) dan Prev/Next Chapter"""
    cache_key = f"ctx_{chapter_id}"
    if cache_key in context.user_data:
        return context.user_data[cache_key]

    ch_data = await fetch_json(f"{MANGADEX_API}/chapter/{chapter_id}?includes[]=manga")
    if not ch_data: return None, None, "Unknown", "??", "??"

    manga = next((rel for rel in ch_data["data"]["relationships"] if rel["type"] == "manga"), None)
    title = manga["attributes"]["title"].get("en", manga["attributes"]["title"].get("ja-ro", "Judul Tidak Diketahui")) if manga else "Unknown"
    ch_num = ch_data["data"]["attributes"]["chapter"] or "Oneshot"
    lang = ch_data["data"]["attributes"]["translatedLanguage"].upper()

    manga_id = manga["id"] if manga else None
    prev_id, next_id = None, None

    if manga_id:
        feed_data = await fetch_json(
            f"{MANGADEX_API}/manga/{manga_id}/feed",
            params={"translatedLanguage[]": [lang.lower()], "limit": 500, "order[chapter]": "asc"}
        )
        if feed_data and feed_data.get("data"):
            chapters = feed_data["data"]
            for i, ch in enumerate(chapters):
                if ch["id"] == chapter_id:
                    if i > 0: prev_id = chapters[i-1]["id"]
                    if i < len(chapters) - 1: next_id = chapters[i+1]["id"]
                    break

    res = (prev_id, next_id, title, ch_num, lang)
    context.user_data[cache_key] = res
    return res

def get_nav_keyboard(chapter_id: str, current_idx: int, total_pages: int, prev_ch: str = None, next_ch: str = None):
    page_nav = []
    if current_idx > 0:
        page_nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"nav_{chapter_id}_{current_idx - 1}"))
    page_nav.append(InlineKeyboardButton(f"📄 {current_idx + 1}/{total_pages}", callback_data="ignore"))
    if current_idx < total_pages - 1:
        page_nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"nav_{chapter_id}_{current_idx + 1}"))

    chapter_nav = []
    if prev_ch: chapter_nav.append(InlineKeyboardButton("⏪ Ch Prev", callback_data=f"switchch_{prev_ch}"))
    chapter_nav.append(InlineKeyboardButton("❌ Tutup", callback_data="close_manga"))
    if next_ch: chapter_nav.append(InlineKeyboardButton("Ch Next ⏩", callback_data=f"switchch_{next_ch}"))

    return InlineKeyboardMarkup([page_nav, chapter_nav])

async def build_search_list(query: str, offset: int, context: ContextTypes.DEFAULT_TYPE):
    """Membangun UI Pagination Search (Max 5 hasil per halaman)"""
    search_url = f"{MANGADEX_API}/manga"
    params = {"title": query, "limit": 5, "offset": offset, "contentRating[]": ["safe", "suggestive", "erotica", "pornographic"]}
    data = await fetch_json(search_url, params)
    
    if not data or not data.get("data"): return None, None
    
    keyboard = []
    for manga in data["data"]:
        title = manga["attributes"]["title"].get("en", manga["attributes"]["title"].get("ja-ro", "Unknown"))
        context.user_data["last_manga_query"] = query 
        keyboard.append([InlineKeyboardButton(f"📖 {title}", callback_data=f"detailmanga_{manga['id']}_0")])

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"msearch_{offset - 5}"))
    if data["total"] > offset + 5:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"msearch_{offset + 5}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    return f"🔍 Hasil pencarian: **{query}** ({(offset//5)+1})", InlineKeyboardMarkup(keyboard)

async def manga_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /manga <judul>"""
    if not context.args:
        await update.message.reply_text("⚠️ Gunakan:\n`/manga <judul>`", parse_mode="Markdown")
        return

    full_query = " ".join(context.args)

    msg = await update.message.reply_text(f"🔍 Mencari `{full_query}`...", parse_mode="Markdown")
    text, markup = await build_search_list(full_query, 0, context)
    
    if text:
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await msg.edit_text("❌ Manga tidak ditemukan.")

async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "ignore":
        await query.answer()
        return
    elif data == "close_manga":
        await query.answer("Pembaca ditutup.")
        await query.message.delete()
        return

    elif data.startswith("msearch_"):
        offset = int(data.split("_")[1])
        q = context.user_data.get("last_manga_query", "")
        if not q: return await query.answer("❌ Sesi pencarian habis.", show_alert=True)
        
        text, markup = await build_search_list(q, offset, context)
        if text:
            if query.message.photo:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id, text=text, parse_mode="Markdown", reply_markup=markup
                )
            else:
                await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        return

    elif data.startswith("detailmanga_"):
        parts = data.split("_")
        manga_id = parts[1]
        offset = int(parts[2]) if len(parts) > 2 else 0

        await query.answer("Memuat daftar chapter...")

        m_data = await fetch_json(f"{MANGADEX_API}/manga/{manga_id}?includes[]=cover_art")
        if not m_data: return await query.answer("❌ Error server.")
        
        manga = m_data["data"]
        title = manga["attributes"]["title"].get("en", manga["attributes"]["title"].get("ja-ro", "Unknown"))
        desc = manga["attributes"]["description"].get("en", "Tidak ada deskripsi.")[:250] + "..."
        
        cover_file = next((rel["attributes"]["fileName"] for rel in manga["relationships"] if rel["type"] == "cover_art"), None)
        cover_url = f"{UPLOADS_URL}/covers/{manga_id}/{cover_file}" if cover_file else None

        feed = await fetch_json(f"{MANGADEX_API}/manga/{manga_id}/feed", {
            "translatedLanguage[]": ["en", "id"], 
            "limit": 10, 
            "offset": offset,
            "order[chapter]": "desc"
        })
        
        keyboard = []
        if feed and feed.get("data"):
            for ch in feed["data"]:
                ch_num = ch["attributes"]["chapter"] or "Oneshot"
                lang = ch["attributes"]["translatedLanguage"].upper()
                keyboard.append([InlineKeyboardButton(f"📖 Ch.{ch_num} [{lang}]", callback_data=f"readmanga_{ch['id']}")])

        nav_buttons = []
        if offset > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Newer", callback_data=f"detailmanga_{manga_id}_{offset - 10}"))
        if feed and feed.get("total", 0) > offset + 10:
            nav_buttons.append(InlineKeyboardButton("Older ➡️", callback_data=f"detailmanga_{manga_id}_{offset + 10}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton("🔙 Kembali ke Pencarian", callback_data="msearch_0")])
        
        caption = f"📚 **{title}**\n\n📝 {desc}"
        
        if query.message.photo:
            await query.edit_message_caption(caption=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            if cover_url:
                await query.message.delete()
                await context.bot.send_photo(query.message.chat_id, photo=cover_url, caption=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await query.edit_message_text(caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif data.startswith("readmanga_") or data.startswith("switchch_"):
        await query.answer("Mengunduh halaman... ⏳")
        chapter_id = data.split("_")[1]
        
        server_data = await fetch_json(f"{MANGADEX_API}/at-home/server/{chapter_id}")
        if not server_data or not server_data["chapter"]["data"]:
            return await context.bot.send_message(query.message.chat_id, "❌ Gagal memuat chapter / Halaman Kosong.")

        prev_ch, next_ch, m_title, m_ch, m_lang = await get_chapter_context(chapter_id, context)

        base_url = server_data["baseUrl"]
        chapter_hash = server_data["chapter"]["hash"]
        urls = [f"{base_url}/data/{chapter_hash}/{p}" for p in server_data["chapter"]["data"]]
        context.user_data[f"manga_{chapter_id}"] = urls

        keyboard = get_nav_keyboard(chapter_id, 0, len(urls), prev_ch, next_ch)
        caption_text = f"📖 <b>{m_title}</b> | Ch:{m_ch} | 🌐 {m_lang}"

        img_bytes = await fetch_image_bytes(urls[0])
        if not img_bytes: return await context.bot.send_message(query.message.chat_id, "❌ Error mendownload gambar.")

        media = InputMediaPhoto(media=img_bytes, caption=caption_text, parse_mode="HTML")
        
        if data.startswith("switchch_") or hasattr(query, 'edit_message_media'):
            try:
                await query.edit_message_media(media=media, reply_markup=keyboard)
            except Exception:
                await query.message.delete()
                await context.bot.send_photo(query.message.chat_id, photo=img_bytes, caption=caption_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await context.bot.send_photo(query.message.chat_id, photo=img_bytes, caption=caption_text, parse_mode="HTML", reply_markup=keyboard)

    elif data.startswith("nav_"):
        parts = data.split("_")
        chapter_id = parts[1]
        page_idx = int(parts[2])

        urls = context.user_data.get(f"manga_{chapter_id}")
        if not urls: return await query.answer("❌ Sesi hilang.", show_alert=True)

        prev_ch, next_ch, m_title, m_ch, m_lang = context.user_data.get(f"ctx_{chapter_id}", (None, None, "Unknown", "?", "?"))

        await query.answer() 
        img_bytes = await fetch_image_bytes(urls[page_idx])
        
        if img_bytes:
            keyboard = get_nav_keyboard(chapter_id, page_idx, len(urls), prev_ch, next_ch)
            caption_text = f"📖 <b>{m_title}</b> | Ch:{m_ch} | 🌐 {m_lang}"
            await query.edit_message_media(
                media=InputMediaPhoto(media=img_bytes, caption=caption_text, parse_mode="HTML"),
                reply_markup=keyboard
            )