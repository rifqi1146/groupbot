from telegram.ext import MessageHandler, filters

from handlers.logger import log_commands
from handlers.collector import collect_chat
from handlers.delete import reply_del_handler
from handlers.dl import auto_dl_detect
from handlers.bot_dollar import dollar_router
from handlers.welcome import welcome_handler
from utils.user_collector import user_collector
from handlers.zhipu import zhipu_cmd
from handlers.groqllama import meta_query
from fun.quiz import quiz_answer

def register_messages(app):
    app.add_handler(
        MessageHandler(filters.ALL, collect_chat),
        group=0,
    )

    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_handler),
        group=1,
    )

    app.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY, reply_del_handler),
        group=2,
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, dollar_router),
        group=3,
    )

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_dl_detect),
        group=4,
    )

    app.add_handler(
        MessageHandler(filters.ALL, log_commands),
        group=99,
    )
    
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, user_collector),
        group=1
    )
    
    app.add_handler(
        MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, zhipu_cmd),
        group=1
    )
    
    app.add_handler(
        MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, meta_query),
        group=-1
    )
    
    app.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, quiz_answer),
        group=100
    )