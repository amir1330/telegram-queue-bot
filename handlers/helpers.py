"""Shared helpers for command handlers."""

import asyncio
import logging
import time

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

import db
from i18n import tr

logger = logging.getLogger(__name__)

ADMIN_STATUSES = frozenset({
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
    "administrator",
    "creator",
})
# Telegram's hidden user when an admin has "Remain anonymous" on.
TELEGRAM_ANONYMOUS_ADMIN_ID = 1087968824
TELEGRAM_CHANNEL_BOT_ID = 136817688
_ADMIN_CACHE_TTL = 60.0
# chat_id -> (fetched_at, admin_user_ids)
_admin_ids_cache: dict[int, tuple[float, set[int]]] = {}

AUTO_DELETE_SECONDS = 30
# Delay before removing the user's command/answer. Instant deletes race with
# desktop Telegram ForceReply / delivery and can make /setname look ignored.
TRIGGER_DELETE_SECONDS = 5


async def delete_later(bot, chat_id, message_id, seconds=AUTO_DELETE_SECONDS):
    """Delete a message after a delay (best-effort, silent on failure)."""
    if seconds:
        await asyncio.sleep(seconds)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def schedule_delete(bot, chat_id, message_id, seconds=AUTO_DELETE_SECONDS):
    """Fire-and-forget delete_later."""
    if chat_id is None or message_id is None:
        return
    asyncio.create_task(delete_later(bot, chat_id, message_id, seconds))


async def cleanup_trigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    seconds: float = TRIGGER_DELETE_SECONDS,
) -> None:
    """Delete the user message that triggered this update (groups only).

    Skips callback queries so we do not delete the message being edited.
    """
    if update.callback_query:
        return
    chat = update.effective_chat
    message = update.effective_message
    if not chat or not message or not is_group(update):
        return
    schedule_delete(context.bot, chat.id, message.message_id, seconds)


async def reply_ephemeral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    parse_mode=None,
    reply_markup=None,
    seconds: float = AUTO_DELETE_SECONDS,
    delete_trigger: bool = True,
):
    """Reply, auto-delete the bot reply, and (in groups) the user trigger message."""
    if delete_trigger:
        await cleanup_trigger(update, context, seconds=TRIGGER_DELETE_SECONDS)
    kwargs = {}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    msg = await update.effective_message.reply_text(text, **kwargs)
    schedule_delete(context.bot, msg.chat_id, msg.message_id, seconds)
    return msg


async def reply_keep(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    parse_mode=None,
    reply_markup=None,
    delete_trigger: bool = True,
):
    """Reply without auto-deleting the bot message (interactive UI).

    Still removes the user command in groups so the chat stays clean.
    """
    if delete_trigger:
        await cleanup_trigger(update, context, seconds=TRIGGER_DELETE_SECONDS)
    kwargs = {}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    return await update.effective_message.reply_text(text, **kwargs)


def _status_is_admin(status) -> bool:
    value = getattr(status, "value", status)
    return status in ADMIN_STATUSES or str(value).lower() in ADMIN_STATUSES


def invalidate_admin_cache(chat_id: int | None = None) -> None:
    """Drop cached admin ids (one chat, or all)."""
    if chat_id is None:
        _admin_ids_cache.clear()
        return
    _admin_ids_cache.pop(chat_id, None)


async def _admin_ids(bot, chat_id: int) -> set[int] | None:
    now = time.monotonic()
    cached = _admin_ids_cache.get(chat_id)
    if cached and now - cached[0] < _ADMIN_CACHE_TTL:
        return cached[1]
    try:
        admins = await bot.get_chat_administrators(chat_id)
        ids = {a.user.id for a in admins if getattr(a, "user", None)}
        _admin_ids_cache[chat_id] = (now, ids)
        return ids
    except Exception as exc:
        logger.warning("get_chat_administrators failed chat=%s: %s", chat_id, exc)
        return None


def _is_anonymous_admin_update(update: Update, chat_id: int, user_id: int) -> bool:
    """True when an admin is posting as the group (Remain anonymous)."""
    user = update.effective_user
    message = update.effective_message
    sender_chat = getattr(message, "sender_chat", None) if message else None
    if sender_chat is not None and sender_chat.id == chat_id:
        return True
    if user_id in (TELEGRAM_ANONYMOUS_ADMIN_ID, TELEGRAM_CHANNEL_BOT_ID):
        # Channel_Bot is only an admin if they posted as this chat, handled above.
        return user_id == TELEGRAM_ANONYMOUS_ADMIN_ID
    username = (getattr(user, "username", None) or "").lower()
    return username == "groupanonymousbot"


async def is_admin(update: Update, chat_id: int, user_id: int) -> bool:
    """True if this update is from a chat admin/creator. Never raises.

    Anonymous admins post as GroupAnonymousBot (or sender_chat = the group),
    so looking up user_id in getChatMember would wrongly fail.
    """
    if _is_anonymous_admin_update(update, chat_id, user_id):
        return True
    if not user_id:
        return False

    bot = update.get_bot()
    admin_ids = await _admin_ids(bot, chat_id)
    if admin_ids is not None:
        ok = user_id in admin_ids
        if not ok:
            user = update.effective_user
            logger.info(
                "admin denied chat=%s user=%s username=%s known_admins=%s",
                chat_id,
                user_id,
                getattr(user, "username", None),
                sorted(admin_ids),
            )
        return ok

    try:
        member = await bot.get_chat_member(chat_id, user_id)
        ok = _status_is_admin(member.status)
        if not ok:
            logger.info(
                "admin denied chat=%s user=%s status=%s",
                chat_id,
                user_id,
                member.status,
            )
        return ok
    except Exception as exc:
        logger.warning("get_chat_member failed chat=%s user=%s: %s", chat_id, user_id, exc)
        return False


async def require_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True if this command was sent in a group. Otherwise explain and return False."""
    if is_group(update) and update.effective_chat and update.effective_user:
        return True
    chat = update.effective_chat
    lang = db.get_chat_lang(chat.id) if chat else db.DEFAULT_LANG
    await reply_ephemeral(update, context, tr(lang, "group_only"))
    return False


async def bot_has_pin_rights(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    """True if the bot can pin/delete messages in the chat (or is creator)."""
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        status_value = str(getattr(me.status, "value", me.status)).lower()
        if status_value in ("creator", "owner"):
            return True
        return (
            _status_is_admin(me.status)
            and me.can_pin_messages is True
            and me.can_delete_messages is True
        )
    except Exception:
        return False


def is_group(update: Update) -> bool:
    return update.effective_chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    )


def display_name(user, chat_id=None) -> str:
    """Name shown in the queue: custom /setname if set, else Telegram first name.

    Falls back to username, then user id. Unknown users become "unknown".
    """
    if user is None:
        return "unknown"
    if chat_id is not None:
        stored = db.get_user_display_name(chat_id, user.id)
        if stored:
            return stored
    return user.first_name or user.username or str(user.id)


def today(chat_id=None):
    """ISO date string in the chat's timezone (server-local if no chat/tz)."""
    from timezone import chat_today
    if chat_id is None:
        from datetime import date
        return date.today().isoformat()
    return chat_today(chat_id)
