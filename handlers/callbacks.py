from telegram.ext import CallbackQueryHandler

from handlers.help import help_callback
from handlers.gsearch import gsearch_callback
from handlers.dl.handlers import dl_callback, dlask_callback, dlres_callback
from handlers.asupan import asupan_callback
from handlers.helpowner import helpowner_callback
from fun.reminder import reminder_cancel_cb
from handlers.update import update_cb
from fun.waifu import waifu_next_cb, waifu_pref_cb
from handlers.welcome import verify_answer_callback
from handlers.music import music_callback
from fun.quiz import quiz_callback


def register_callbacks(app):
    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(gsearch_callback, pattern=r"^gsearch:"))
    app.add_handler(CallbackQueryHandler(dlask_callback, pattern=r"^dlask:"))
    app.add_handler(CallbackQueryHandler(dlres_callback, pattern=r"^dlres:"))
    app.add_handler(CallbackQueryHandler(dl_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(asupan_callback, pattern=r"^asupan:"))
    app.add_handler(CallbackQueryHandler(helpowner_callback, pattern=r"^helpowner:"))
    app.add_handler(CallbackQueryHandler(reminder_cancel_cb, pattern=r"^reminder:"))
    app.add_handler(CallbackQueryHandler(waifu_next_cb, pattern=r"^waifu_next$"))
    app.add_handler(CallbackQueryHandler(verify_answer_callback, pattern=r"^verify_ans:"))
    app.add_handler(CallbackQueryHandler(waifu_pref_cb, pattern=r"^waifu_pref$"))
    app.add_handler(CallbackQueryHandler(update_cb, pattern=r"^update_"))
    app.add_handler(CallbackQueryHandler(music_callback, pattern=r"^music_download:"))
    app.add_handler(CallbackQueryHandler(quiz_callback, pattern=r"^quizans:"))
    