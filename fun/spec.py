import urllib.parse
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.http import get_http_session

BASE = "https://www.gsmarena.com/"


async def gsmarena_search(query: str):
    session = await get_http_session()

    def build_url(q: str):
        q = urllib.parse.quote_plus(q)
        return f"{BASE}results.php3?sQuickSearch=yes&sName={q}"

    tried = []
    candidates = [query]

    if query.lower().startswith("samsung ") and "galaxy" not in query.lower():
        candidates.append(query.replace("samsung", "samsung galaxy", 1))

    if query.lower().startswith("redmi "):
        candidates.append("xiaomi " + query)

    for q in candidates:
        if q in tried:
            continue
        tried.append(q)

        async with session.get(build_url(q), allow_redirects=True) as r:
            html = await r.text()
            final_url = str(r.url)

        soup = BeautifulSoup(html, "lxml")

        if soup.find("div", id="specs-list"):
            title = soup.find("h1", class_="specs-phone-name-title")
            if title:
                return [(title.get_text(" ", strip=True), final_url)]

        results = []
        for li in soup.select("li"):
            a = li.find("a", href=True)
            strong = li.find("strong")
            if not a or not strong:
                continue

            name = strong.get_text(" ", strip=True)
            link = a["href"]
            if not link.endswith(".php"):
                continue

            results.append((name, BASE + link))

            if len(results) >= 8:
                break

        if results:
            return results

    return []


async def gsmarena_specs(url: str):
    session = await get_http_session()

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
                category = th.get_text(" ", strip=True)
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


async def spec_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if not context.args:
        return await msg.reply_text("❌ Contoh:\n/spec redmi note 9")

    query = " ".join(context.args)
    results = await gsmarena_search(query)

    if not results:
        return await msg.reply_text("❌ Device ga ketemu")

    if len(results) == 1:
        text = await gsmarena_specs(results[0][1])
        if not text:
            return await msg.reply_text("❌ Gagal ambil spesifikasi")

        for i in range(0, len(text), 3900):
            await msg.reply_text(
                text[i:i + 3900],
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        return

    context.user_data["spec_results"] = results

    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"spec:{i}")]
        for i, (name, _) in enumerate(results)
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

    results = context.user_data.get("spec_results")
    idx = int(q.data.split(":", 1)[1])

    if not results or idx >= len(results):
        return await q.message.delete()

    url = results[idx][1]
    text = await gsmarena_specs(url)

    await q.message.delete()

    if not text:
        return await q.message.chat.send_message("❌ Gagal ambil spesifikasi")

    for i in range(0, len(text), 3900):
        await q.message.chat.send_message(
            text[i:i + 3900],
            parse_mode="HTML",
            disable_web_page_preview=True
        )