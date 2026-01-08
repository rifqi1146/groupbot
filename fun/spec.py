import urllib.parse
from bs4 import BeautifulSoup
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import ContextTypes
from utils.http import get_http_session

BASE = "https://www.gsmarena.com/"

# ================= SEARCH =================

async def gsmarena_search(query: str):
    session = get_http_session()

    q = urllib.parse.quote_plus(query)
    url = f"{BASE}results.php3?sQuickSearch=yes&sName={q}"

    async with session.get(url) as r:
        html = await r.text()

    soup = BeautifulSoup(html, "lxml")
    results = []

    for li in soup.select("div.makers li"):
        a = li.find("a")
        if not a:
            continue

        name = a.get_text(" ", strip=True)
        link = BASE + a["href"]

        results.append((name, link))

        if len(results) >= 8:
            break

    return results


# ================= SPECS =================

async def gsmarena_specs(url: str):
    session = get_http_session()

    async with session.get(url) as r:
        html = await r.text()

    soup = BeautifulSoup(html, "lxml")
    specs_root = soup.find("div", id="specs-list")
    if not specs_root:
        return None

    data = []

    for table in specs_root.find_all("table"):
        category = None
        for row in table.find_all("tr"):
            th = row.find("th")
            if th:
                category = th.get_text(strip=True)
                data.append(f"\n<b>📌 {category}</b>")
                continue

            ttl = row.find("td", class_="ttl")
            nfo = row.find("td", class_="nfo")
            if not ttl or not nfo:
                continue

            key = ttl.get_text(" ", strip=True)
            val = nfo.get_text(" ", strip=True)
            data.append(f"• <b>{key}</b>: {val}")

    return "\n".join(data)


# ================= COMMAND =================

async def spec_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if not context.args:
        return await msg.reply_text("❌ Contoh:\n/spec redmi note 9")

    query = " ".join(context.args)
    results = await gsmarena_search(query)

    if not results:
        return await msg.reply_text("❌ Device ga ketemu")

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"spec|{url}")]
        for name, url in results
    ]

    await msg.reply_text(
        "🔍 Pilih device:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ================= CALLBACK =================

async def spec_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not q.data.startswith("spec|"):
        return

    url = q.data.split("|", 1)[1]
    text = await gsmarena_specs(url)

    if not text:
        return await q.message.edit_text("❌ Gagal ambil spesifikasi")

    # split telegram limit
    for i in range(0, len(text), 3900):
        await q.message.reply_text(
            text[i:i+3900],
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        