import shlex
import logging
from telegram import Update
from telegram.ext import ContextTypes

from handlers.start import start_cmd
from handlers.help import help_cmd
from handlers.helpowner import helpowner_cmd
from handlers.ping import ping_cmd
from handlers.restart import restart_cmd
from handlers.ai import ask_cmd, ai_cmd, setmodeai_cmd, groq_query
from handlers.weather import weather_cmd
from handlers.speedtest import speedtest_cmd
from handlers.networking import ip_cmd, domain_cmd, whoisdomain_cmd
from handlers.stats import stats_cmd
from handlers.tr import tr_cmd
from handlers.gsearch import gsearch_cmd
from handlers.dl import dl_cmd
from handlers.asupan import asupan_cmd, asupanlist_cmd, enable_asupan_cmd, disable_asupan_cmd
from handlers.nsfw import pollinations_generate_nsfw, enablensfw_cmd, disablensfw_cmd, nsfwlist_cmd
from handlers.welcome import wlc_cmd

log = logging.getLogger(__name__)

_DOLLAR_CMD_MAP = {
    "start": start_cmd,
    "help": help_cmd,
    "menu": help_cmd,
    "helpowner": helpowner_cmd,
    "ping": ping_cmd,
    "restart": restart_cmd,
    "ask": ask_cmd,
    "ai": ai_cmd,
    "groq": groq_query,
    "setmodeai": setmodeai_cmd,
    "weather": weather_cmd,
    "speedtest": speedtest_cmd,
    "ip": ip_cmd,
    "stats": stats_cmd,
    "tr": tr_cmd,
    "gsearch": gsearch_cmd,
    "dl": dl_cmd,
    "domain": domain_cmd,
    "whoisdomain": whoisdomain_cmd,
    "asupan": asupan_cmd,
    "asupanlist": asupanlist_cmd,
    "enableasupan": enable_asupan_cmd,
    "disableasupan": disable_asupan_cmd,
    "nsfw": pollinations_generate_nsfw,
    "enablensfw": enablensfw_cmd,
    "disablensfw": disablensfw_cmd,
    "nsfwlist": nsfwlist_cmd,
    "wlc": wlc_cmd,
}

async def dollar_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    txt = msg.text.strip()
    if not txt.startswith("$"):
        return

    try:
        parts = shlex.split(txt[1:].strip())
    except Exception:
        parts = txt[1:].strip().split()

    if not parts:
        return

    cmd = parts[0].lower()
    context.args = parts[1:]

    handler = _DOLLAR_CMD_MAP.get(cmd)
    if not handler:
        return

    try:
        await handler(update, context)
    except Exception:
        log.exception("Dollar command failed")