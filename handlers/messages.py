from telegram.ext import MessageHandler, filters

from utils.logger import log_commands
from handlers.collector import collect_chat
from handlers.delete import reply_del_handler
from handlers.dl import auto_dl_detect
from handlers.bot_dollar import dollar_router
from handlers.welcome import welcome_handler
from utils.user_collector import user_collector
from handlers.caca import meta_query, _META_ACTIVE_USERS
from handlers.groq import groq_query, _GROQ_ACTIVE_USERS
from fun.quiz import quiz_answer
from handlers.gemini import ai_cmd, _AI_ACTIVE_USERS
from handlers.openrouter import ask_cmd, _ASK_ACTIVE_USERS

async def ai_reply_router(update, context):
    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    user_id = msg.from_user.id
    reply_mid = msg.reply_to_message.message_id

    if reply_mid in _ASK_ACTIVE_MESSAGES:
        return await ask_cmd(update, context)

    if _GROQ_ACTIVE_USERS.get(user_id) == reply_mid:
        return await groq_query(update, context)

    if _META_ACTIVE_USERS.get(user_id) == reply_mid:
        return await meta_query(update, context)
    
    if _AI_ACTIVE_USERS.get(user_id) == reply_mid:
        return await ai_cmd(update, context)

    if reply_mid in _META_ACTIVE_USERS.values():
        return await msg.reply_text(
            "😒 Lu siapa?\n"
            "Gue belum ngobrol sama lu.\n"
            "Ketik /caca dulu.",
            parse_mode="HTML"
        )

    if reply_mid in _GROQ_ACTIVE_USERS.values():
        return await msg.reply_text(
            "😒 Lu siapa?\n"
            "Gue belum ngobrol sama lu.\n"
            "Ketik /groq dulu.",
            parse_mode="HTML"
        )

    if reply_mid in _ASK_ACTIVE_USERS.values():
        return await msg.reply_text(
            "😒 Lu siapa?\n"
            "Gue belum ngobrol sama lu.\n"
            "Ketik /ask dulu.",
            parse_mode="HTML"
        )
    
    if reply_mid in _AI_ACTIVE_USERS.values():
        return await msg.reply_text(
            "😒 Lu siapa?\n"
            "Gue belum ngobrol sama lu.\n"
            "Ketik /ai dulu.",
            parse_mode="HTML"
        )
    
    return
    
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
        MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, ai_reply_router),
        group=-1
    )
    
    app.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, quiz_answer),
        group=100
    )