import html
from telegram import Update
from telegram.ext import ContextTypes
from utils.config import OWNER_ID
from database.groups_db import _db_init, _load_groups

def _chat_sort_key(item):
    title = (item.get("title") or "").lower()
    return title

async def groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    bot = context.bot
    if not msg or not user or user.id not in OWNER_ID:
        return
    group_ids = _load_groups()
    if not group_ids:
        return await msg.reply_text("📭 <b>No groups recorded yet.</b>", parse_mode="HTML")
    public_groups = []
    private_groups = []
    skipped = 0
    for gid in group_ids:
        try:
            chat = await bot.get_chat(gid)
            title = html.escape((chat.title or "Unknown").strip() or "Unknown")
            username = (getattr(chat, "username", None) or "").strip()
            item = {"id": gid, "title": title, "username": username}
            if username:
                public_groups.append(item)
            else:
                private_groups.append(item)
        except Exception:
            skipped += 1
            continue
    public_groups.sort(key=_chat_sort_key)
    private_groups.sort(key=_chat_sort_key)
    total_valid = len(public_groups) + len(private_groups)
    if total_valid == 0:
        return await msg.reply_text(
            "📭 <b>No active groups found.</b>\n\n<i>Saved entries exist, but the bot can no longer access them.</i>",
            parse_mode="HTML"
        )
    lines = [f"📋 <b>Current Bot Groups</b> — <b>{total_valid}</b>"]
    if public_groups:
        lines.append(f"\n<b>🔗 Public Groups</b> — <b>{len(public_groups)}</b>")
        for item in public_groups:
            link = f"https://t.me/{html.escape(item['username'])}"
            lines.append(f"• <a href=\"{link}\">{item['title']}</a>\n  <code>{item['id']}</code>")
    if private_groups:
        lines.append(f"\n<b>🏷️ Private / Hidden Groups</b> — <b>{len(private_groups)}</b>")
        for item in private_groups:
            lines.append(f"• {item['title']}\n  <code>{item['id']}</code>")
    if skipped:
        lines.append(f"\n<i>Skipped inaccessible groups: {skipped}</i>")
    text = "\n".join(lines)
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]
    for i, chunk in enumerate(chunks):
        if i == 0:
            await msg.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        else:
            await msg.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)

try:
    _db_init()
except Exception:
    pass