import aiohttp
from telegram import Update
from telegram.ext import ContextTypes
from utils.http import get_http_session


async def kurs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    args = context.args

    if args and args[0].lower() == "list":
        try:
            session = await get_http_session()
            async with session.get(
                "https://api.frankfurter.app/currencies",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 200:
                    return await msg.reply_text("❌ Gagal ambil daftar mata uang.")

                data = await r.json()

            lines = ["💱 <b>Daftar Mata Uang</b>\n"]
            for code, name in sorted(data.items()):
                lines.append(f"• <b>{code}</b> — {name}")

            lines.append("\n🌐 Sumber: <b>Frankfurter API (European Central Bank)</b>")

            return await msg.reply_text(
                "\n".join(lines),
                parse_mode="HTML"
            )

        except Exception as e:
            return await msg.reply_text(f"❌ Error: {e}")

    if len(args) < 2:
        return await msg.reply_text(
            "💱 <b>Kurs Mata Uang</b>\n\n"
            "Format:\n"
            "<code>/kurs [jumlah] FROM TO</code>\n\n"
            "Contoh:\n"
            "<code>/kurs USD IDR</code>\n"
            "<code>/kurs 10 USD IDR</code>\n"
            "<code>/kurs list</code>",
            parse_mode="HTML"
        )

    try:
        if len(args) == 2:
            amount = 1.0
            from_cur = args[0].upper()
            to_cur = args[1].upper()
        else:
            amount = float(args[0])
            from_cur = args[1].upper()
            to_cur = args[2].upper()
    except Exception:
        return await msg.reply_text("❌ Format salah.")

    url = "https://api.frankfurter.app/latest"
    params = {
        "from": from_cur,
        "to": to_cur,
        "amount": amount
    }

    try:
        session = await get_http_session()
        async with session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            if r.status != 200:
                return await msg.reply_text("❌ Gagal ambil data kurs.")

            data = await r.json()

        rate = data["rates"].get(to_cur)
        date = data.get("date")

        if rate is None:
            return await msg.reply_text("❌ Mata uang tidak valid.")

        await msg.reply_text(
            "💱 <b>Kurs Mata Uang</b>\n\n"
            f"{amount:g} <b>{from_cur}</b> ≈ <b>{rate:,.2f} {to_cur}</b>\n\n"
            f"📅 Tanggal: <code>{date}</code>\n"
            "🌐 Sumber: <b>European Central Bank</b>",
            parse_mode="HTML"
        )

    except Exception as e:
        await msg.reply_text(f"❌ Error: {e}")