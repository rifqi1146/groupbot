from telegram.ext import CallbackQueryHandler

from handlers.help import help_callback
from handlers.gsearch import gsearch_callback
from handlers.dl import dl_callback, dlask_callback
from handlers.asupan import asupan_callback
from handlers.helpowner import helpowner_callback
from fun.reminder import reminder_cancel_cb
from handlers.update import update_cb
from fun.waifu import waifu_next_cb, waifu_pref_cb
from handlers.welcome import verify_answer_callback
from handlers.music import music_callback

def register_callbacks(app):
    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(gsearch_callback, pattern=r"^gsearch:"))
    app.add_handler(CallbackQueryHandler(dl_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(dlask_callback, pattern=r"^dlask:"))
    app.add_handler(CallbackQueryHandler(asupan_callback, pattern=r"^asupan:"))
    app.add_handler(CallbackQueryHandler(helpowner_callback, pattern=r"^helpowner:"))
    app.add_handler(CallbackQueryHandler(reminder_cancel_cb, pattern=r"^reminder:"))
    app.add_handler(CallbackQueryHandler(waifu_next_cb, pattern="^waifu_next$"))
    app.add_handler(CallbackQueryHandler(verify_answer_callback, pattern="^verify_ans:"))
    app.add_handler(CallbackQueryHandler(waifu_pref_cb, pattern="^waifu_pref$"))
    app.add_handler(CallbackQueryHandler(update_cb, pattern="^update_"))
    app.add_handler(CallbackQueryHandler(music_callback, pattern="^music_download:"))
