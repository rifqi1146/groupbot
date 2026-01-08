import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.http import get_http_session
import html


WIKI_API = "https://en.wikipedia.org/w/api.php"

def normalize_infobox(text: str) -> list[str]:
    lines = []
    buf = ""

    for raw in text.split("\n"):
        raw = raw.strip()

        if not raw:
            continue

        if raw.startswith("|"):
            if buf:
                lines.append(buf)
            buf = raw
        else:
            buf += " " + raw

    if buf:
        lines.append(buf)

    return lines
    
def sanitize_telegram_html(text: str) -> str:
    text = html.escape(text)

    text = text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    text = text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    text = text.replace("&lt;u&gt;", "<u>").replace("&lt;/u&gt;", "</u>")
    text = text.replace("&lt;s&gt;", "<s>").replace("&lt;/s&gt;", "</s>")
    text = text.replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
    text = text.replace("&lt;pre&gt;", "<pre>").replace("&lt;/pre&gt;", "</pre>")

    return text

def extract_infobox(wikitext: str) -> str | None:
    start = wikitext.find("{{Infobox mobile phone")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(wikitext)):
        if wikitext[i:i+2] == "{{":
            depth += 1
        elif wikitext[i:i+2] == "}}":
            depth -= 1
            if depth == 0:
                return wikitext[start:i+2]

    return None


def clean_wikitext(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")

    text = re.sub(r"'''+", "", text)

    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)

    text = re.sub(r"\{\{Start Date And Age\|[^|}]*\|(\d{4})\|(\d{2})\|(\d{2})\}\}",
                  r"\3-\2-\1", text, flags=re.I)

    text = re.sub(r"\{\{Val\|(\d+)\|[^}]+\}\}", r"\1", text, flags=re.I)

    text = re.sub(
        r"\{\{ubl\|([^}]+)\}\}",
        lambda m: ", ".join(x.strip() for x in m.group(1).split("|")),
        text,
        flags=re.I
    )

    text = re.sub(r"\{\{convert\|([^}]+)\}\}", r"\1", text, flags=re.I)

    text = re.sub(r"\{\{[^}]+\}\}", "", text)

    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


async def wiki_search(query: str):
    session = await get_http_session()
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json"
    }

    headers = {
        "User-Agent": "GroupBot/1.0"
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
        if len(results) >= 6:
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
        "User-Agent": "GroupBot/1.0"
    }

    async with session.get(WIKI_API, params=params, headers=headers) as r:
        if r.status != 200:
            return None
        try:
            data = await r.json()
        except Exception:
            return None

    wikitext = data.get("parse", {}).get("wikitext", {}).get("*")
    if not wikitext:
        return None

    infobox = extract_infobox(wikitext)
    if not infobox:
        return None

    raw_lines = normalize_infobox(infobox)
    lines = []
    
    for raw in raw_lines:
        if "=" not in raw:
            continue
    
        key, val = raw.split("=", 1)
        key = key.replace("|", "").strip().title()
        val = clean_wikitext(val)
    
        if not val:
            continue
    
        lines.append(f"<b>{key}</b>\n{val}")

    if not lines:
        return None

    return "\n\n".join(lines)


async def spec_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if not context.args:
        return await msg.reply_text("❌ Contoh:\n/spec samsung s24")

    query = " ".join(context.args)
    results = await wiki_search(query)

    if not results:
        return await msg.reply_text("❌ Device ga ketemu")

    if len(results) == 1:
        text = await wiki_specs(results[0])
        if not text:
            return await msg.reply_text("❌ Spesifikasi belum tersedia")

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
        return await q.message.chat.send_message("❌ Spesifikasi belum tersedia")

    await q.message.chat.send_message(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True
    )