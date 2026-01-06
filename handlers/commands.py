from telegram.ext import CommandHandler

from handlers.ai import ask_cmd, ai_cmd, setmodeai_cmd, groq_query
from handlers.nsfw import enablensfw_cmd, disablensfw_cmd, nsfwlist_cmd, pollinations_generate_nsfw
from handlers.networking import whoisdomain_cmd, ip_cmd, domain_cmd
from handlers.broadcast import broadcast_cmd
from handlers.start import start_cmd
from handlers.orangefox import orangefox_cmd
from handlers.tr import tr_cmd, trlist_cmd
from handlers.restart import restart_cmd
from handlers.gsearch import gsearch_cmd
from handlers.stats import stats_cmd
from handlers.help import help_cmd
from handlers.speedtest import speedtest_cmd
from handlers.ping import ping_cmd
from handlers.weather import weather_cmd
from handlers.dl import dl_cmd
from handlers.helpowner import helpowner_cmd
from handlers.welcome import wlc_cmd
from handlers.asupan import (
    asupan_cmd,
    enable_asupan_cmd,
    disable_asupan_cmd,
    asupanlist_cmd,
    autodel_cmd,
)

def register_commands(app):
    handlers = [
        ("start", start_cmd),
        ("broadcast", broadcast_cmd),
        ("orangefox", orangefox_cmd),
        ("autodel", autodel_cmd),
        ("help", help_cmd),
        ("menu", help_cmd),
        ("ask", ask_cmd),
        ("ai", ai_cmd),
        ("setmodeai", setmodeai_cmd),
        ("groq", groq_query),
        ("weather", weather_cmd),
        ("ping", ping_cmd),
        ("speedtest", speedtest_cmd),
        ("ip", ip_cmd),
        ("whoisdomain", whoisdomain_cmd),
        ("domain", domain_cmd),
        ("dl", dl_cmd),
        ("stats", stats_cmd),
        ("tr", tr_cmd),
        ("trlist", trlist_cmd),
        ("gsearch", gsearch_cmd),
        ("enableasupan", enable_asupan_cmd),
        ("disableasupan", disable_asupan_cmd),
        ("asupanlist", asupanlist_cmd),
        ("asupan", asupan_cmd),
        ("restart", restart_cmd),
        ("nsfw", pollinations_generate_nsfw),
        ("enablensfw", enablensfw_cmd),
        ("disablensfw", disablensfw_cmd),
        ("nsfwlist", nsfwlist_cmd),
        ("helpowner", helpowner_cmd),
        ("wlc", wlc_cmd),
    ]

    for name, handler in handlers:
        app.add_handler(CommandHandler(name, handler), group=-1)
        