from telegram.ext import CommandHandler

from handlers.nsfw import nsfw_cmd
from handlers.networking import whoisdomain_cmd, ip_cmd, domain_cmd, net_cmd
from handlers.broadcast import broadcast_cmd
from handlers.start import start_cmd
from handlers.translate import tr_cmd, trlist_cmd
from handlers.restart import restart_cmd
from handlers.gsearch import gsearch_cmd
from handlers.stats import stats_cmd
from handlers.help import help_cmd
from handlers.speedtest import speedtest_cmd
from handlers.ping import ping_cmd
from handlers.weather import weather_cmd
from handlers.dl.router import dl_cmd, autodl_cmd
from handlers.helpowner import helpowner_cmd
from handlers.welcome import wlc_cmd, start_verify_pm
from handlers.ship import ship_cmd
from handlers.reminder import reminder_cmd
from handlers.gemini import ai_cmd
from handlers.groq import groq_query
from handlers.quiz import quiz_cmd
from handlers.premium import premium_cmd
from handlers.waifu import waifu_cmd
from handlers.update import update_cmd
from handlers.groups import groups_cmd
from handlers.music import music_cmd
from handlers.kurs import kurs_cmd
from handlers.cookies import cookies_cmd
from handlers.donate import donate_cmd
from handlers.quotly import q_cmd
from handlers.kang import kang_cmd
from handlers.setting import setting_cmd
from handlers.backup import backup_cmd, restore_cmd, autobackup_cmd
from handlers.manga import manga_cmd
from handlers.anime import anime_cmd
from handlers.upscale import upscale_cmd
from handlers.resi import resi_cmd
from handlers.fasttelethon import fasttelethon_cmd
from handlers.reload import reload_cmd
from handlers.nobg import nobg_cmd
from handlers.blacklist import blacklist_cmd
from handlers.getsticker import getsticker_cmd

from handlers.caca import (
    meta_query,
    cacaa_cmd,
    mode_cmd,
)

from handlers.moderation import (
    moderation_cmd, 
    ban_cmd, 
    unban_cmd, 
    tag_cmd, 
    untag_cmd,
    mute_cmd, 
    unmute_cmd,
    kick_cmd,
    addsudo_cmd,
    rmsudo_cmd,
    sudolist_cmd,
    promote_cmd,
    demote_cmd,
)
    
from handlers.asupan import (
    asupan_cmd,
    asupann_cmd,
    autodel_cmd,
)

COMMAND_HANDLERS = [
    ("start", start_cmd, True),
    ("upscale", upscale_cmd, False),
    ("nobg", nobg_cmd, False),
    ("getsticker", getsticker_cmd, False),
    ("tag", tag_cmd, False),
    ("untag", untag_cmd, False),
    ("blacklist", blacklist_cmd, False),
    ("reload", reload_cmd, False),
    ("settings", setting_cmd, False),
    ("fasttelethon", fasttelethon_cmd, False),
    ("anime", anime_cmd, False),
    ("promote", promote_cmd, False),
    ("resi", resi_cmd, False),
    ("demote", demote_cmd, False),
    ("backup", backup_cmd, True),
    ("autobackup", autobackup_cmd, True),
    ("restore", restore_cmd, True),
    ("q", q_cmd, False),
    ("kang", kang_cmd, False),
    ("cookies", cookies_cmd, False),
    ("moderation", moderation_cmd, False),
    ("mute", mute_cmd, False),
    ("unmute", unmute_cmd, False),
    ("ban", ban_cmd, False),
    ("unban", unban_cmd, False),
    ("kick", kick_cmd, False),
    ("addsudo", addsudo_cmd, False),
    ("rmsudo", rmsudo_cmd, False),
    ("sudolist", sudolist_cmd, False),
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
    ("ask", ai_cmd, False),
    ("groq", groq_query, False),
    ("weather", weather_cmd, False),
    ("speedtest", speedtest_cmd, False),
    ("gsearch", gsearch_cmd, False),
    ("dl", dl_cmd, False),
    ("asupan", asupan_cmd, False),
    ("asupann", asupann_cmd, False),
    ("nsfw", nsfw_cmd, False),
    ("restart", restart_cmd, False),
    ("manga", manga_cmd, False),
]

def register_commands(app):
    for name, handler, blocking in COMMAND_HANDLERS:
        app.add_handler(
            CommandHandler(name, handler, block=blocking),
            group=-1
        )
        