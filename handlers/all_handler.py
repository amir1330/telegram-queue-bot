"""Admin /all — mention everyone the bot can reach in the group."""

import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import (
    TRIGGER_DELETE_SECONDS,
    cleanup_trigger,
    is_admin,
    is_group,
    reply_ephemeral,
    require_group,
)
from i18n import tr

logger = logging.getLogger(__name__)

_CHUNK_CHARS = 3500


def remember_user(chat_id: int, user) -> None:
    """Store a Telegram user so /all can @mention them later."""
    if not chat_id or user is None or getattr(user, "is_bot", False):
        return
    name = user.first_name or user.username or str(user.id)
    db.touch_known_user(chat_id, user.id, name, username=user.username)


def _mention(user_id: int, name: str, username: str | None = None) -> str:
    """Prefer @username (real ping), else silent HTML deep-link."""
    if username:
        return f"@{username.lstrip('@')}"
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
    users: dict[int, dict] = {}

    def _put(user_id, name, username=None):
        if not user_id or user_id == bot_id:
            return
        prev = users.get(user_id, {})
        users[user_id] = {
            "user_id": user_id,
            "display_name": name or prev.get("display_name") or str(user_id),
            "username": username or prev.get("username"),
        }

    try:
        admins = await update.get_bot().get_chat_administrators(chat_id)
        for member in admins:
            user = member.user
            if not user or user.is_bot:
                continue
            _put(
                user.id,
                user.first_name or user.username or str(user.id),
                user.username,
            )
            remember_user(chat_id, user)
    except Exception as exc:
        logger.warning("all: get_chat_administrators failed chat=%s: %s", chat_id, exc)

    for row in db.get_known_users(chat_id):
        _put(row["user_id"], row["display_name"], row.get("username"))

    return [users[uid] for uid in sorted(users)]


async def learn_group_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remember senders (and reply parents) from every group message."""
    if not is_group(update):
        return
    chat = update.effective_chat
    if not chat:
        return
    remember_user(chat.id, update.effective_user)
    message = update.effective_message
    if message and message.reply_to_message and message.reply_to_message.from_user:
        remember_user(chat.id, message.reply_to_message.from_user)


async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mention all group members the bot can tag (@username when known)."""
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return

    remember_user(chat.id, user)

    targets = await _mention_targets(update, chat.id, context.bot.id)
    if not targets:
        await reply_ephemeral(update, context, tr(lang, "all_nobody"))
        return

    mentions = [
        _mention(u["user_id"], u["display_name"], u.get("username")) for u in targets
    ]
    header = tr(lang, "all_header", n=len(mentions))
    parts = _chunks(mentions)

    await cleanup_trigger(update, context, seconds=TRIGGER_DELETE_SECONDS)
    for i, body in enumerate(parts):
        text = f"{header}\n{body}" if i == 0 else body
        await update.effective_message.reply_text(text, parse_mode="HTML")
