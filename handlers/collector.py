import os
import json
from telegram import Update
from telegram.ext import ContextTypes

BROADCAST_FILE = "data/broadcast_chats.json"


def _load():
    if not os.path.exists(BROADCAST_FILE):
        return {"users": [], "groups": []}
    with open(BROADCAST_FILE, "r") as f:
        return json.load(f)


def _save(data):
    os.makedirs("data", exist_ok=True)
    with open(BROADCAST_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def collect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return

    data = _load()

    if chat.type == "private":
        if chat.id not in data["users"]:
            data["users"].append(chat.id)
    else:
        if chat.id not in data["groups"]:
            data["groups"].append(chat.id)

    _save(data)