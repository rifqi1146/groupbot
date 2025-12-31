import html
from telegram import Update
from telegram.ext import ContextTypes

from utils.http import async_searcher


async def get_ofox(codename: str):
    base = "https://api.orangefox.download"

    devices_resp = await async_searcher(
        f"{base}/devices/",
        re_json=True
    )

    releases_resp = await async_searcher(
        f"{base}/releases/",
        re_json=True
    )

    devices = devices_resp.get("devices", [])
    releases = releases_resp.get("releases", [])

    device = None
    for d in devices:
        if d.get("codename") == codename:
            device = d
            break

    matched_releases = [
        r for r in releases if r.get("codename") == codename
    ]

    return device, matched_releases


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

        if not device:
            await msg.edit_text("❌ Device not found.")
            return

        text = (
            "🦊 <b>OrangeFox Recovery</b>\n\n"
            f"📱 <b>Device</b>: {html.escape(str(device.get('fullname', '—')))}\n"
            f"🏷 <b>Codename</b>: <code>{html.escape(codename)}</code>\n"
            f"🏭 <b>Brand</b>: {html.escape(str(device.get('brand', '—')))}\n"
            f"📆 <b>Android</b>: {html.escape(str(device.get('android', '—')))}\n"
            f"🧩 <b>Maintainer</b>: {html.escape(str(device.get('maintainer', '—')))}\n\n"
        )

        if releases:
            latest = releases[0]
            text += (
                "📦 <b>Latest Release</b>\n"
                f"• Version: <code>{html.escape(str(latest.get('version', '—')))}</code>\n"
                f"• Build: <code>{html.escape(str(latest.get('build', '—')))}</code>\n"
                f"• Date: <code>{html.escape(str(latest.get('date', '—')))}</code>\n"
                f"• Size: <code>{html.escape(str(latest.get('size', '—')))}</code>\n"
            )

            url = latest.get("url")
            if url:
                text += f"• Download: <a href=\"{html.escape(url, quote=True)}\">Click here</a>\n"
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