"""Admin /ping — mention known users who are not in the open queue."""

import html

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import cleanup_trigger, is_admin, is_group, reply_ephemeral
from i18n import tr

# Keep each ping message under Telegram's limit with room for the header.
_CHUNK_CHARS = 3500


def _mention(user_id: int, name: str) -> str:
    safe = html.escape(name or str(user_id))
    return f'<a href="tg://user?id={user_id}">{safe}</a>'


def _chunks(mentions):
    """Split mention list into messages that fit Telegram's length limit."""
    if not mentions:
        return []
    chunks, cur = [], ""
    for m in mentions:
        piece = m if not cur else ", " + m
        if len(cur) + len(piece) > _CHUNK_CHARS:
            chunks.append(cur)
            cur = m
        else:
            cur += piece
    if cur:
        chunks.append(cur)
    return chunks


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mention known members who are not in today's open queue.

    Ping messages are kept (so people see the tags); only the /ping command
    itself is removed. Telegram bots can only tag users they have already seen
    (joined queue, /setname, etc.) — not the full group roster.
    """
    chat = update.effective_chat
    user = update.effective_user
    if not is_group(update) or not chat or not user:
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return

    db.touch_known_user(chat.id, user.id, user.first_name)

    sessions = db.get_active_messages(chat_id=chat.id, status="open")
    if not sessions:
        await reply_ephemeral(update, context, tr(lang, "ping_no_open"))
        return

    session = sessions[0]
    in_queue = {
        e["user_id"]
        for e in db.get_queue(chat.id, session["lesson_id"], session["session_date"])
    }
    missing = [
        u
        for u in db.get_known_users(chat.id)
        if u["user_id"] not in in_queue and u["user_id"] != context.bot.id
    ]
    if not missing:
        await reply_ephemeral(update, context, tr(lang, "ping_everyone_in"))
        return

    mentions = [_mention(u["user_id"], u["display_name"]) for u in missing]
    header = tr(lang, "ping_header", n=len(mentions))
    parts = _chunks(mentions)

    await cleanup_trigger(update, context, seconds=0)
    for i, body in enumerate(parts):
        text = f"{header}\n{body}" if i == 0 else body
        await update.effective_message.reply_text(text, parse_mode="HTML")
