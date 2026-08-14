"""Shared helpers for command handlers."""

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

import db

logger = logging.getLogger(__name__)

ADMIN_STATUSES = ("administrator", "creator")

AUTO_DELETE_SECONDS = 30


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
    seconds: float = 0,
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
        await cleanup_trigger(update, context, seconds=0)
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
        await cleanup_trigger(update, context, seconds=0)
    kwargs = {}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    return await update.effective_message.reply_text(text, **kwargs)


async def is_admin(update: Update, chat_id: int, user_id: int) -> bool:
    """True if user_id is an admin/creator of chat. Never raises."""
    try:
        member = await update.get_bot().get_chat_member(chat_id, user_id)
        return member.status in ADMIN_STATUSES
    except Exception:
        return False


async def bot_has_pin_rights(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    """True if the bot can pin/delete messages in the chat (or is creator)."""
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status == "creator":
            return True
        return (
            me.status == "administrator"
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
