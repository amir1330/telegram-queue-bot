"""Admin /all — mention everyone the bot can reach in the group."""

import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import TRIGGER_DELETE_SECONDS, cleanup_trigger, is_admin, reply_ephemeral, require_group
from i18n import tr

logger = logging.getLogger(__name__)

_CHUNK_CHARS = 3500


def _mention(user_id: int, name: str) -> str:
    safe = html.escape(name or str(user_id))
    return f'<a href="tg://user?id={user_id}">{safe}</a>'


def _chunks(mentions):
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


async def _mention_targets(update: Update, chat_id: int, bot_id: int) -> list[dict]:
    """Admins from Telegram + everyone the bot has seen in this chat."""
    users: dict[int, str] = {}
    try:
        admins = await update.get_bot().get_chat_administrators(chat_id)
        for member in admins:
            user = member.user
            if not user or user.is_bot or user.id == bot_id:
                continue
            users[user.id] = user.first_name or user.username or str(user.id)
    except Exception as exc:
        logger.warning("all: get_chat_administrators failed chat=%s: %s", chat_id, exc)

    for row in db.get_known_users(chat_id):
        uid = row["user_id"]
        if uid == bot_id or uid in users:
            continue
        users[uid] = row["display_name"] or str(uid)

    return [{"user_id": uid, "display_name": name} for uid, name in sorted(users.items())]


async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mention all group members the bot can tag."""
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return

    db.touch_known_user(chat.id, user.id, user.first_name)

    targets = await _mention_targets(update, chat.id, context.bot.id)
    if not targets:
        await reply_ephemeral(update, context, tr(lang, "all_nobody"))
        return

    mentions = [_mention(u["user_id"], u["display_name"]) for u in targets]
    header = tr(lang, "all_header", n=len(mentions))
    parts = _chunks(mentions)

    await cleanup_trigger(update, context, seconds=TRIGGER_DELETE_SECONDS)
    for i, body in enumerate(parts):
        text = f"{header}\n{body}" if i == 0 else body
        await update.effective_message.reply_text(text, parse_mode="HTML")
