from telegram.ext import CallbackQueryHandler

from handlers.help import help_callback
from handlers.gsearch import gsearch_callback
from handlers.dl import dl_callback, dlask_callback
from handlers.asupan import asupan_callback
from handlers.helpowner import helpowner_callback
from fun.reminder import reminder_cancel_cb

def register_callbacks(app):
    app.add_handler(CallbackQueryHandler(help_callback, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(gsearch_callback, pattern=r"^gsearch:"))
    app.add_handler(CallbackQueryHandler(dl_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(dlask_callback, pattern=r"^dlask:"))
    app.add_handler(CallbackQueryHandler(asupan_callback, pattern=r"^asupan:"))
    app.add_handler(CallbackQueryHandler(helpowner_callback, pattern=r"^helpowner:"))
    app.add_handler(CallbackQueryHandler(reminder_cancel_cb, pattern=r"^reminder:"))
