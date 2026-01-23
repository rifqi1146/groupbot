import html
import socket
import aiohttp
import whois

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session

#whois
def _fmt_date(d):
    if isinstance(d, list):
        return str(d[0]) if d else "Not available"
    return str(d) if d else "Not available"


async def whoisdomain_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "<b>📋 WHOIS Domain</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/whoisdomain google.com</code>",
            parse_mode="HTML"
        )

    domain = (
        context.args[0]
        .replace("http://", "")
        .replace("https://", "")
        .split("/")[0]
    )

    msg = await update.message.reply_text(
        f"🔄 <b>Fetching WHOIS for {html.escape(domain)}...</b>",
        parse_mode="HTML"
    )

    try:
        w = whois.whois(domain)

        ns = w.name_servers
        if isinstance(ns, list):
            ns_text = "\n".join(f"• {html.escape(n)}" for n in ns[:8])
        else:
            ns_text = html.escape(str(ns)) if ns else "Not available"

        result = (
            "<b>📋 WHOIS Information</b>\n\n"
            f"<b>Domain:</b> <code>{html.escape(domain)}</code>\n"
            f"<b>Registrar:</b> {html.escape(str(w.registrar or 'N/A'))}\n"
            f"<b>WHOIS Server:</b> {html.escape(str(w.whois_server or 'N/A'))}\n\n"

            "<b>📅 Important Dates</b>\n"
            f"<b>Created:</b> {_fmt_date(w.creation_date)}\n"
            f"<b>Updated:</b> {_fmt_date(w.updated_date)}\n"
            f"<b>Expires:</b> {_fmt_date(w.expiration_date)}\n\n"

            "<b>👤 Registrant</b>\n"
            f"<b>Name:</b> {html.escape(str(w.name or 'N/A'))}\n"
            f"<b>Organization:</b> {html.escape(str(w.org or 'N/A'))}\n"
            f"<b>Email:</b> {html.escape(str(w.emails[0] if isinstance(w.emails, list) else w.emails or 'N/A'))}\n\n"

            "<b>🔧 Technical</b>\n"
            f"<b>Status:</b> {html.escape(str(w.status or 'N/A'))}\n"
            f"<b>DNSSEC:</b> {html.escape(str(w.dnssec or 'N/A'))}\n\n"

            "<b>🌐 Name Servers</b>\n"
            f"{ns_text}\n\n"

            "<b>🏢 Registrar Info</b>\n"
            f"<b>IANA ID:</b> {html.escape(str(w.registrar_iana_id or 'N/A'))}\n"
            f"<b>URL:</b> {html.escape(str(w.registrar_url or 'N/A'))}"
        )

        if len(result) > 4096:
            await msg.edit_text(result[:4096], parse_mode="HTML")
            await update.message.reply_text(result[4096:], parse_mode="HTML")
        else:
            await msg.edit_text(result, parse_mode="HTML")

    except Exception as e:
        await msg.edit_text(
            f"❌ WHOIS failed: <code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
        
#cmd ip
async def ip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "<b>🌍 IP Info</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/ip 8.8.8.8</code>",
            parse_mode="HTML"
        )

    ip = context.args[0]
    msg = await update.message.reply_text(
        f"🔄 <b>Analyzing IP {html.escape(ip)}...</b>",
        parse_mode="HTML"
    )

    try:
        url = (
            f"http://ip-api.com/json/{ip}"
            "?fields=status,message,continent,continentCode,country,countryCode,"
            "region,regionName,city,zip,lat,lon,timezone,offset,isp,org,as,"
            "reverse,mobile,proxy,hosting,query"
        )

        session = await get_http_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return await msg.edit_text("❌ Failed to fetch IP information")

            data = await resp.json()

        if data.get("status") != "success":
            return await msg.edit_text(
                f"❌ Failed: <code>{html.escape(data.get('message', 'Unknown error'))}</code>",
                parse_mode="HTML"
            )

        text = (
            "<b>🌍 IP Address Information</b>\n\n"
            f"<b>IP:</b> <code>{data.get('query')}</code>\n"
            f"<b>ISP:</b> {html.escape(data.get('isp','N/A'))}\n"
            f"<b>Organization:</b> {html.escape(data.get('org','N/A'))}\n"
            f"<b>AS:</b> {html.escape(data.get('as','N/A'))}\n\n"

            "<b>📍 Location</b>\n"
            f"<b>Country:</b> {html.escape(data.get('country','N/A'))} ({data.get('countryCode','')})\n"
            f"<b>Region:</b> {html.escape(data.get('regionName','N/A'))}\n"
            f"<b>City:</b> {html.escape(data.get('city','N/A'))}\n"
            f"<b>ZIP:</b> {html.escape(data.get('zip','N/A'))}\n"
            f"<b>Coords:</b> {data.get('lat','N/A')}, {data.get('lon','N/A')}\n\n"

            "<b>🕐 Timezone</b>\n"
            f"<b>TZ:</b> {html.escape(data.get('timezone','N/A'))}\n"
            f"<b>UTC Offset:</b> {data.get('offset','N/A')}\n\n"

            "<b>🔍 Flags</b>\n"
            f"<b>Reverse DNS:</b> {html.escape(data.get('reverse','N/A'))}\n"
            f"<b>Mobile:</b> {'Yes' if data.get('mobile') else 'No'}\n"
            f"<b>Proxy:</b> {'Yes' if data.get('proxy') else 'No'}\n"
            f"<b>Hosting:</b> {'Yes' if data.get('hosting') else 'No'}"
        )

        await msg.edit_text(text, parse_mode="HTML")

    except Exception as e:
        await msg.edit_text(
            f"❌ Error: <code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
        

async def domain_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /domain example.com
    """
    msg = update.effective_message

    if not context.args:
        return await msg.reply_text(
            "<b>Usage:</b> /domain &lt;domain&gt;\n"
            "<b>Example:</b> /domain google.com",
            parse_mode="HTML"
        )

    domain = context.args[0]
    domain = domain.replace("http://", "").replace("https://", "").split("/")[0]

    loading = await msg.reply_text(
        f"🔄 <b>Analyzing domain:</b> <code>{html.escape(domain)}</code>",
        parse_mode="HTML"
    )

    info = {}

    try:
        info["ip"] = socket.gethostbyname(domain)
    except Exception:
        info["ip"] = "Not found"

    try:
        w = whois.whois(domain)
        info["registrar"] = w.registrar or "Not available"
        info["created"] = str(w.creation_date) if w.creation_date else "Not available"
        info["expires"] = str(w.expiration_date) if w.expiration_date else "Not available"
        info["nameservers"] = w.name_servers or []
    except Exception:
        info["registrar"] = "Not available"
        info["created"] = "Not available"
        info["expires"] = "Not available"
        info["nameservers"] = []

    try:
        session = await get_http_session()
        async with session.get(
            f"http://{domain}",
            timeout=aiohttp.ClientTimeout(total=10),
            allow_redirects=True
        ) as r:
            info["http_status"] = r.status
            info["server"] = r.headers.get("server", "Not available")
    except Exception:
        info["http_status"] = "Not available"
        info["server"] = "Not available"

    if info["nameservers"]:
        ns_text = "\n".join(
            f"• {html.escape(ns)}" for ns in info["nameservers"][:5]
        )
    else:
        ns_text = "Not available"

    text = (
        "<b>🌐 Domain Information</b>\n\n"
        f"<b>Domain:</b> <code>{html.escape(domain)}</code>\n"
        f"<b>IP Address:</b> <code>{info['ip']}</code>\n"
        f"<b>HTTP Status:</b> <code>{info['http_status']}</code>\n"
        f"<b>Server:</b> <code>{html.escape(info['server'])}</code>\n\n"
        "<b>📋 Registration Details</b>\n"
        f"<b>Registrar:</b> {html.escape(info['registrar'])}\n"
        f"<b>Created:</b> {html.escape(info['created'])}\n"
        f"<b>Expires:</b> {html.escape(info['expires'])}\n\n"
        "<b>🔧 Name Servers</b>\n"
        f"{ns_text}"
    )

    await loading.edit_text(text, parse_mode="HTML")
    
## Credit Moon Userbot
## https://github.com/The-MoonTg-project/Moon-Userbot