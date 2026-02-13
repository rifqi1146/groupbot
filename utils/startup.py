import asyncio
import logging

from handlers.asupan import (
    LOG_CHAT_ID,
    send_asupan_once,
    load_asupan_groups,
    load_autodel_groups,
)

from handlers.welcome import load_welcome_chats

from utils import premium_service
from handlers import caca

log = logging.getLogger(__name__)


async def startup_tasks(app):
    log.info("🔧 Running startup tasks...")

    try:
        load_asupan_groups()
        load_welcome_chats()
        load_autodel_groups()
        log.info("✓ Asupan & welcome cache loaded")
    except Exception as e:
        log.warning(f"Startup cache load failed: {e}")

    try:
        premium_service.init()
        log.info("✓ Premium cache initialized")
    except Exception as e:
        log.warning(f"Premium init failed: {e}")

    try:
        caca.init_background()
        log.info("✓ Caca background initialized")
    except Exception as e:
        log.warning(f"Caca init failed: {e}")

    await asyncio.sleep(2)

    if not LOG_CHAT_ID:
        log.warning("ASUPAN STARTUP chat_id kosong")
        return

    try:
        await send_asupan_once(app.bot)
        log.info("✓ Asupan startup sent")
    except Exception as e:
        log.warning(f"Asupan startup failed: {e}")
        