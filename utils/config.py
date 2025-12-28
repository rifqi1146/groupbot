import os
from dotenv import load_dotenv

load_dotenv()

OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

ASUPAN_STARTUP_CHAT_ID = (
    int(os.getenv("ASUPAN_STARTUP_CHAT_ID"))
    if os.getenv("ASUPAN_STARTUP_CHAT_ID")
    else None
)

