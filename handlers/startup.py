import asyncio
import logging

from handlers.asupan import (
    ASUPAN_STARTUP_CHAT_ID,
    send_asupan_once,
    load_asupan_groups,
    load_autodel_groups,
)
from handlers.welcome import load_welcome_chats

log = logging.getLogger(__name__)

async def startup_tasks(app):
    load_asupan_groups()
    load_welcome_chats()
    load_autodel_groups()

    await asyncio.sleep(5)

    if not ASUPAN_STARTUP_CHAT_ID:
        log.warning("ASUPAN STARTUP chat_id kosong")
        return

    try:
        await send_asupan_once(app.bot)
        log.info("Asupan startup sent")
    except Exception as e:
        log.warning(f"Asupan startup failed: {e}")