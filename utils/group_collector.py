from utils.storage import load_groups, save_groups

async def collect_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return

    if chat.type not in ("group", "supergroup"):
        return

    groups = load_groups()

    groups[str(chat.id)] = {
        "title": chat.title or "Unknown Group",
        "last_seen": int(time.time())
    }

    save_groups(groups)