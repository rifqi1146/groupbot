import asyncio
import logging

from handlers.asupan import (
    send_asupan_once,
    load_asupan_groups,
    load_autodel_groups,
)
from utils.config import LOG_CHAT_ID
from handlers import welcome
from handlers.nsfw import nsfw_db_init
from handlers.backup import start_auto_backup
from database import premium
from handlers import caca

log = logging.getLogger(__name__)


async def startup_tasks(app):
    log.info("✓ Running startup tasks...")

    try:
        nsfw_db_init()
        log.info("✓ NSFW DB initialized")
    except Exception:
        log.exception("NSFW DB init failed")

    try:
        welcome.init_welcome_db()
        log.info("✓ Welcome DB initialized")
    except Exception:
        log.exception("Welcome DB init failed")

    try:
        load_asupan_groups()
        log.info("✓ Asupan groups loaded")
    except Exception:
        log.exception("Asupan groups load failed")

    try:
        load_autodel_groups()
        log.info("✓ Autodel groups loaded")
    except Exception:
        log.exception("Autodel groups load failed")

    try:
        welcome.WELCOME_ENABLED_CHATS = welcome.load_welcome_chats()
        log.info(
            "✓ Welcome-enabled chats loaded: %s",
            len(welcome.WELCOME_ENABLED_CHATS),
        )
    except Exception:
        log.exception("Welcome chats load failed")
        welcome.WELCOME_ENABLED_CHATS = set()

    try:
        welcome.VERIFIED_USERS = welcome.load_verified()
        log.info(
            "✓ Verified users cache loaded for %s chats",
            len(welcome.VERIFIED_USERS),
        )
    except Exception:
        log.exception("Verified users load failed")
        welcome.VERIFIED_USERS = {}

    try:
        await welcome.restore_pending_verifications(app)
        log.info("✓ Pending welcome verifications restored")
    except Exception:
        log.exception("Welcome verify restore failed")

    try:
        premium_service.init()
        log.info("✓ Premium cache initialized")
    except Exception:
        log.exception("Premium init failed")

    try:
        caca.init_background()
        log.info("✓ Caca background initialized")
    except Exception:
        log.exception("Caca init failed")

    try:
        start_auto_backup(app)
        log.info("✓ Auto backup scheduler initialized")
    except Exception:
        log.exception("Auto backup init failed")

    await asyncio.sleep(2)

    if not LOG_CHAT_ID:
        log.warning("Startup asupan skipped: LOG_CHAT_ID kosong")
        return

    try:
        await send_asupan_once(app.bot)
        log.info("✓ Asupan startup sent")
    except Exception:
        log.exception("Asupan startup failed")