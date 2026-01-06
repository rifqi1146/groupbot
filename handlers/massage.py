import shlex
from telegram.ext import MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

from handlers.dl import auto_dl_detect
from handlers.logger import log_commands
from handlers.delete import reply_del_handler
from handlers.collector import collect_chat
from handlers.welcome import welcome_handler
from handlers.asupan import asupan_callback
from handlers.start import start_cmd
from handlers.help import help_cmd
from handlers.helpowner import helpowner_cmd
from handlers.ping import ping_cmd
from handlers.restart import restart_cmd
from handlers.ai import ask_cmd, ai_cmd, groq_query, setmodeai_cmd
from handlers.weather import weather_cmd
from handlers.speedtest import speedtest_cmd
from handlers.networking import ip_cmd, domain_cmd, whoisdomain_cmd
from handlers.stats import stats_cmd
from handlers.tr import tr_cmd
from handlers.gsearch import gsearch_cmd
from handlers.asupan import asupan_cmd, asupanlist_cmd, enable_asupan_cmd, disable_asupan_cmd
from handlers.nsfw import pollinations_generate_nsfw, enablensfw_cmd, disablensfw_cmd, nsfwlist_cmd
from handlers.welcome import wlc_cmd

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
    txt = msg.text.strip()

    if not txt.startswith("$"):
        return

    try:
        parts = shlex.split(txt[1:])
    except Exception:
        parts = txt[1:].split()

    if not parts:
        return

    cmd = parts[0].lower()
    context.args = parts[1:]

    handler = _DOLLAR_CMD_MAP.get(cmd)
    if handler:
        await handler(update, context)


def register_messages(app):
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_handler), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_dl_detect), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dollar_router), group=1)
    app.add_handler(MessageHandler(filters.TEXT & filters.REPLY, reply_del_handler), group=-1)
    app.add_handler(MessageHandler(filters.ALL, collect_chat), group=0)
    app.add_handler(MessageHandler(filters.ALL, log_commands), group=99)
    