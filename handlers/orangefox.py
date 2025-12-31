import html
from telegram import Update
from telegram.ext import ContextTypes

from utils.http import async_searcher


async def get_ofox(codename: str):
    base = "https://api.orangefox.download/v3/"
    releases = await async_searcher(
        f"{base}releases?codename={codename}", re_json=True
    )
    device = await async_searcher(
        f"{base}devices/get?codename={codename}", re_json=True
    )
    return device, releases


async def orangefox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "<code>/orangefox &lt;codename&gt;</code>\n"
            "Example:\n"
            "<code>/orangefox sweet</code>",
            parse_mode="HTML",
        )
        return

    codename = context.args[0].lower()
    msg = await update.message.reply_text("🦊 Fetching OrangeFox data...")

    try:
        device, releases = await get_ofox(codename)

        if not device or "data" not in device:
            await msg.edit_text("❌ Device not found.")
            return

        dev = device["data"]
        rels = releases.get("data") or []

        text = (
            "🦊 <b>OrangeFox Recovery</b>\n\n"
            f"📱 <b>Device</b>: {html.escape(str(dev.get('fullname', '—')))}\n"
            f"🏷 <b>Codename</b>: <code>{html.escape(codename)}</code>\n"
            f"🏭 <b>Brand</b>: {html.escape(str(dev.get('brand', '—')))}\n"
            f"📆 <b>Android</b>: {html.escape(str(dev.get('android', '—')))}\n"
            f"🧩 <b>Maintainer</b>: {html.escape(str(dev.get('maintainer', '—')))}\n\n"
        )

        if rels:
            latest = rels[0]
            url = latest.get("url")

            text += (
                "📦 <b>Latest Release</b>\n"
                f"• Version: <code>{html.escape(str(latest.get('version', '—')))}</code>\n"
                f"• Build: <code>{html.escape(str(latest.get('build', '—')))}</code>\n"
                f"• Date: <code>{html.escape(str(latest.get('date', '—')))}</code>\n"
                f"• Size: <code>{html.escape(str(latest.get('size', '—')))}</code>\n"
            )

            if url:
                safe_url = html.escape(url, quote=True)
                text += f"• Download: <a href=\"{safe_url}\">Click here</a>\n"
        else:
            text += "⚠️ No releases found."

        if len(text) > 4000:
            text = text[:3990] + "..."

        await msg.edit_text(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    except Exception as e:
        await msg.edit_text(
            f"❌ Error:\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )
    