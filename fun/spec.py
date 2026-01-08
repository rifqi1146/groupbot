import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.http import get_http_session

WIKI_API = "https://en.wikipedia.org/w/api.php"


async def wiki_search(query: str):
    session = await get_http_session()
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json"
    }

    headers = {
        "User-Agent": "GroupBot/1.0 (https://t.me/yourbot)"
    }

    async with session.get(WIKI_API, params=params, headers=headers) as r:
        if r.status != 200:
            return []

        try:
            data = await r.json()
        except Exception:
            return []

    results = []
    for item in data.get("query", {}).get("search", []):
        results.append(item["title"])
        if len(results) >= 5:
            break

    return results


async def wiki_specs(title: str):
    session = await get_http_session()

    params = {
        "action": "parse",
        "page": title.replace(" ", "_"),
        "prop": "wikitext",
        "format": "json"
    }

    headers = {
        "User-Agent": "GroupBot/1.0 (https://t.me/yourbot)"
    }

    async with session.get(WIKI_API, params=params, headers=headers) as r:
        if r.status != 200:
            return None

        try:
            data = await r.json()
        except Exception:
            return None

    text = data.get("parse", {}).get("wikitext", {}).get("*")
    if not text:
        return None

    infobox = re.search(r"\{\{Infobox mobile phone(.*?)\n\}\}", text, re.S)
    if not infobox:
        return None

    block = infobox.group(1)
    lines = []

    for line in block.split("\n"):
        if "=" not in line:
            continue

        k, v = line.split("=", 1)
        k = k.strip().replace("_", " ").title()
        v = re.sub(r"\[\[|\]\]", "", v).strip()

        if v:
            lines.append(f"• <b>{k}</b>: {v}")

    return "\n".join(lines)


async def spec_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if not context.args:
        return await msg.reply_text("❌ Contoh:\n/spec samsung s23 fe")

    query = " ".join(context.args)
    results = await wiki_search(query)

    if not results:
        return await msg.reply_text("❌ Device ga ketemu")

    if len(results) == 1:
        text = await wiki_specs(results[0])
        if not text:
            return await msg.reply_text("❌ Gagal ambil spesifikasi")

        return await msg.reply_text(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    context.user_data["spec_titles"] = results

    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"spec:{i}")]
        for i, title in enumerate(results)
    ]

    await msg.reply_text(
        "🔍 Pilih device:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def spec_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not q.data.startswith("spec:"):
        return

    titles = context.user_data.get("spec_titles")
    idx = int(q.data.split(":", 1)[1])

    if not titles or idx >= len(titles):
        return await q.message.delete()

    title = titles[idx]
    text = await wiki_specs(title)

    await q.message.delete()

    if not text:
        return await q.message.chat.send_message("❌ Gagal ambil spesifikasi")

    await q.message.chat.send_message(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True
    )