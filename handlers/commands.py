from telegram.ext import CommandHandler

from handlers.nsfw import nsfw_cmd
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
from handlers.dl.handlers import dl_cmd, autodl_cmd
from handlers.helpowner import helpowner_cmd
from handlers.welcome import wlc_cmd, start_verify_pm
from fun.ship import ship_cmd
from fun.reminder import reminder_cmd
from handlers.gemini import ai_cmd
from handlers.groq import groq_query
from handlers.openrouter import ask_cmd
from fun.quiz import quiz_cmd
from handlers.caca import meta_query
from handlers.caca_group import cacaa_cmd
from handlers.caca_mode import mode_cmd
from handlers.premium import premium_cmd
from fun.waifu import waifu_cmd
from handlers.update import update_cmd
from handlers.groups import groups_cmd
from handlers.music import music_cmd
from handlers.kurs import kurs_cmd
from handlers.net import net_cmd
from handlers.cookies import cookies_cmd
from handlers.donate import donate_cmd

from handlers.asupan import (
    asupan_cmd,
    asupann_cmd,
    autodel_cmd,
)

COMMAND_HANDLERS = [
    ("start", start_cmd, True),
    ("cookies", cookies_cmd, False),
    ("net", net_cmd, False),
    ("donate", donate_cmd, False),
    ("start", start_verify_pm, False),
    ("kurs", kurs_cmd, False),
    ("music", music_cmd, False),
    ("autodl", autodl_cmd, False),
    ("groups", groups_cmd, False),
    ("waifu", waifu_cmd, False),
    ("caca", meta_query, False),
    ("cacaa", cacaa_cmd, False),
    ("mode", mode_cmd, False),
    ("premium", premium_cmd, False),
    ("quiz", quiz_cmd, False),
    ("ship", ship_cmd, True),
    ("update", update_cmd, False),
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
    ("groq", groq_query, False),
    ("weather", weather_cmd, False),
    ("speedtest", speedtest_cmd, False),
    ("gsearch", gsearch_cmd, False),
    ("dl", dl_cmd, False),
    ("asupan", asupan_cmd, False),
    ("asupann", asupann_cmd, False),
    ("nsfw", nsfw_cmd, False),
    ("restart", restart_cmd, False),
]

def register_commands(app):
    for name, handler, blocking in COMMAND_HANDLERS:
        app.add_handler(
            CommandHandler(name, handler, block=blocking),
            group=-1
        )
        