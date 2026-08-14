"""Shared helpers for command handlers."""

import asyncio

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

import db

ADMIN_STATUSES = ("administrator", "creator")

AUTO_DELETE_SECONDS = 30


async def delete_later(bot, chat_id, message_id, seconds=AUTO_DELETE_SECONDS):
    """Delete a message after a delay (best-effort, silent on failure)."""
    await asyncio.sleep(seconds)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


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