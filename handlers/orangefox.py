import html
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from utils.http import async_searcher  # sesuaikan path kalau beda


async def get_ofox(codename: str):
    base = "https://api.orangefox.download/v3/"
    releases = await async_searcher(
        base + f"releases?codename={codename}", re_json=True
    )
    device = await async_searcher(
        base + f"devices/get?codename={codename}", re_json=True
    )
    return device, releases


async def orangefox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "❌ Usage: <code>/orangefox &lt;codename&gt;</code><br>"
            "Example: <code>/orangefox sweet</code>",
            parse_mode="HTML"
        )

    codename = context.args[0].lower()
    msg = await update.message.reply_text("🦊 Fetching OrangeFox data...")

    try:
        device, releases = await get_ofox(codename)

        if not device or "error" in device:
            return await msg.edit_text("❌ Device not found.")

        dev = device.get("data", {})
        rels = releases.get("data", [])

        text = (
            "🦊 <b>OrangeFox Recovery</b><br><br>"
            f"📱 <b>Device</b> : {html.escape(str(dev.get('fullname', '—')))}<br>"
            f"🏷 <b>Codename</b> : <code>{html.escape(codename)}</code><br>"
            f"🏭 <b>Brand</b> : {html.escape(str(dev.get('brand', '—')))}<br>"
            f"📆 <b>Android</b> : {html.escape(str(dev.get('android', '—')))}<br>"
            f"🧩 <b>Maintainer</b> : {html.escape(str(dev.get('maintainer', '—')))}<br><br>"
        )

        if rels:
            latest = rels[0]
            text += (
                "📦 <b>Latest Release</b><br>"
                f"• Version : <code>{html.escape(str(latest.get('version', '—')))}</code><br>"
                f"• Build : <code>{html.escape(str(latest.get('build', '—')))}</code><br>"
                f"• Date : <code>{html.escape(str(latest.get('date', '—')))}</code><br>"
                f"• Size : <code>{html.escape(str(latest.get('size', '—')))}</code><br>"
                f"• Link : {html.escape(str(latest.get('url', '—')))}<br>"
            )
        else:
            text += "⚠️ No releases found."

        await msg.edit_text(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    except Exception as e:
        await msg.edit_text(
            f"❌ Error: <code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )

    