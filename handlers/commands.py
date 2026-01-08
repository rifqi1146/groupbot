from telegram.ext import CommandHandler

from handlers.ai import ask_cmd, ai_cmd, setmodeai_cmd, groq_query
from handlers.nsfw import enablensfw_cmd, disablensfw_cmd, nsfwlist_cmd, pollinations_generate_nsfw
from handlers.networking import whoisdomain_cmd, ip_cmd, domain_cmd
from handlers.broadcast import broadcast_cmd
from handlers.start import start_cmd
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
from fun.ship import ship_cmd
from fun.reminder import reminder_cmd
from fun.spec import spec_cmd

from handlers.asupan import (
    asupan_cmd,
    enable_asupan_cmd,
    disable_asupan_cmd,
    asupanlist_cmd,
    autodel_cmd,
)

COMMAND_HANDLERS = [
    ("start", start_cmd, True),
    ("ship", ship_cmd, True),
    ("spec", spec_cmd, False),
    ("reminder", reminder_cmd, False),
    ("broadcast", broadcast_cmd, False),
    ("autodel", autodel_cmd, True),
    ("help", help_cmd, True),
    ("menu", help_cmd, True),
    ("ping", ping_cmd, True),
    ("ip", ip_cmd, True),
    ("whoisdomain", whoisdomain_cmd, True),
    ("domain", domain_cmd, True),
    ("stats", stats_cmd, False),
    ("tr", tr_cmd, True),
    ("trlist", trlist_cmd, True),
    ("helpowner", helpowner_cmd, True),
    ("wlc", wlc_cmd, True),
    ("ask", ask_cmd, False),
    ("ai", ai_cmd, False),
    ("setmodeai", setmodeai_cmd, True),
    ("groq", groq_query, False),
    ("weather", weather_cmd, False),
    ("speedtest", speedtest_cmd, False),
    ("gsearch", gsearch_cmd, False),
    ("dl", dl_cmd, False),
    ("asupan", asupan_cmd, False),
    ("asupanlist", asupanlist_cmd, True),
    ("enableasupan", enable_asupan_cmd, True),
    ("disableasupan", disable_asupan_cmd, True),
    ("nsfw", pollinations_generate_nsfw, False),
    ("enablensfw", enablensfw_cmd, True),
    ("disablensfw", disablensfw_cmd, True),
    ("nsfwlist", nsfwlist_cmd, True),
    ("restart", restart_cmd, False),
]

def register_commands(app):
    for name, handler, blocking in COMMAND_HANDLERS:
        app.add_handler(
            CommandHandler(name, handler, block=blocking),
            group=-1
        )