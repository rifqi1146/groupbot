import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.http import get_http_session

WIKI_API = "https://en.wikipedia.org/w/api.php"


def extract_infobox(wikitext: str) -> str | None:
    start = wikitext.find("{{Infobox mobile phone")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(wikitext)):
        if wikitext[i:i + 2] == "{{":
            depth += 1
        elif wikitext[i:i + 2] == "}}":
            depth -= 1
            if depth == 0:
                return wikitext[start:i + 2]

    return None


def normalize_key(key: str) -> str | None:
    key = key.strip().lower()

    aliases = {
        "network": "networks",
        "networks": "networks",

        "released": "released",
        "available": "released",

        "display": "display",

        "soc": "soc",
        "chipset": "soc",

        "cpu": "cpu",
        "gpu": "gpu",

        "ram": "memory",
        "memory": "memory",

        "storage": "storage",

        "battery": "battery",
        "charging": "charging",

        "rear_camera": "rear_camera",
        "main_camera": "rear_camera",
        "camera": "rear_camera",

        "front_camera": "front_camera",
        "selfie_camera": "front_camera",

        "os": "os",
    }

    return aliases.get(key)


def clean_wikitext(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)

    text = re.sub(r"\{\{convert\|([^}]+)\}\}", r"\1", text)

    text = re.sub(
        r"\{\{ubl\|([^}]+)\}\}",
        lambda m: ", ".join(x.strip() for x in m.group(1).split("|")),
        text
    )

    text = re.sub(r"\{\{[^|}]+\}\}", "", text)

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

    LABELS = {
        "networks": "Network",
        "released": "Release",
        "display": "Display",
        "soc": "Chipset",
        "cpu": "CPU",
        "gpu": "GPU",
        "memory": "RAM",
        "storage": "Storage",
        "battery": "Battery",
        "charging": "Charging",
        "rear_camera": "Rear Camera",
        "front_camera": "Front Camera",
        "os": "OS",
    }

    collected = {}

    for raw in infobox.split("\n"):
        if "=" not in raw:
            continue

        raw_key, val = raw.split("=", 1)
        key = normalize_key(raw_key)
        if not key:
            continue

        val = clean_wikitext(val)
        if not val:
            continue

        if key not in collected:
            collected[key] = val

    if not collected:
        return "ℹ️ Data terbatas."

    lines = []
    for key, label in LABELS.items():
        if key in collected:
            lines.append(f"• <b>{label}</b>: {collected[key]}")

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
        return await q.message.chat.send_message("❌ Spesifikasi belum tersedia")

    await q.message.chat.send_message(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True
    )