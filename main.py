import os
import subprocess
import time
import signal
import sys
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("[!] API_ID atau API_HASH belum diset")
    sys.exit(1)

TGDATA_DIR = "tgdata"
os.makedirs(TGDATA_DIR, exist_ok=True)

BOT_API_CMD = [
    "telegram-bot-api",
    f"--api-id={API_ID}",
    f"--api-hash={API_HASH}",
    "--local",
    "--http-port=8081",
    f"--dir={TGDATA_DIR}",
]

BOT_CMD = ["python3", "bot.py"]

bot_api_proc = None
bot_proc = None


def shutdown(signum, frame):
    print("\n[!] Shutting down...")
    if bot_proc:
        bot_proc.terminate()
    if bot_api_proc:
        bot_api_proc.terminate()
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


print("[+] Starting Telegram Bot API...")
bot_api_proc = subprocess.Popen(BOT_API_CMD)

time.sleep(2)

print("[+] Starting bot.py...")
bot_proc = subprocess.Popen(BOT_CMD)

bot_api_proc.wait()