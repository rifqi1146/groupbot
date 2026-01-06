from telegram.ext import MessageHandler, filters

from handlers.logger import log_commands
from handlers.collector import collect_chat
from handlers.delete import reply_del_handler
from handlers.dl import auto_dl_detect
from bot_dollar import dollar_router

def register_messages(app):
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_dl_detect),
        group=1,
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, dollar_router),
        group=1,
    )

    app.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY, reply_del_handler),
        group=-1,
    )

    app.add_handler(
        MessageHandler(filters.ALL, collect_chat),
        group=0,
    )

    app.add_handler(
        MessageHandler(filters.ALL, log_commands),
        group=99,
    )