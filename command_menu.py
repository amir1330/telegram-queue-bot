"""Scoped Telegram command menus: per-chat, per-role (students vs admins).

Telegram resolves the most specific matching scope automatically: admins get
the BotCommandScopeChatAdministrators list, everyone else in that chat falls
back to the BotCommandScopeChat list.
"""

import logging

from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat,
    BotCommandScopeChatAdministrators,
    BotCommandScopeDefault,
)

import db

logger = logging.getLogger(__name__)

# Keep the student slash-menu minimal — join/leave buttons cover most use,
# /setname is the one text command they still need in groups.
STUDENT_COMMANDS = [
    ("queue", "Встать в очередь / Join queue"),
    ("leave", "Выйти из очереди / Leave queue"),
    ("setname", "Имя в очереди / Queue display name"),
]

ADMIN_COMMANDS = [
    ("info", "Настройки и команды / Settings & info"),
    ("lang", "Язык / Language"),
    ("setlesson", "Задать урок: день и время / Set a lesson"),
    ("before", "За сколько минут до урока открыть очередь / Open-before minutes"),
    ("duration", "Сколько минут список живёт после урока / List lifetime minutes"),
    ("delete", "Удалить урок для дня / Remove a lesson"),
    ("tz", "Часовой пояс чата / Chat timezone"),
    ("ping", "Тегнуть тех, кто не в очереди / Ping not in queue"),
]


def _to_bot_commands(items):
    return [BotCommand(command=cmd, description=desc) for cmd, desc in items]


async def sync_commands_for_chat(bot, chat_id: int):
    """Set the role-scoped command menus for one chat.

    Everyone in this chat sees student commands; admins also see admin
    commands (the more specific scope wins for them automatically).
    """
    try:
        await bot.set_my_commands(
            _to_bot_commands(STUDENT_COMMANDS),
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
        await bot.set_my_commands(
            _to_bot_commands(STUDENT_COMMANDS + ADMIN_COMMANDS),
            scope=BotCommandScopeChatAdministrators(chat_id=chat_id),
        )
    except Exception as exc:
        logger.warning("sync_commands_for_chat(%s) failed: %s", chat_id, exc)


async def sync_default_commands(bot):
    """Fallback menus for chats that have not been synced yet (and DMs)."""
    try:
        await bot.set_my_commands(
            _to_bot_commands(STUDENT_COMMANDS),
            scope=BotCommandScopeDefault(),
        )
        await bot.set_my_commands(
            _to_bot_commands(STUDENT_COMMANDS),
            scope=BotCommandScopeAllGroupChats(),
        )
    except Exception as exc:
        logger.warning("sync_default_commands failed: %s", exc)


async def sync_all_chats(bot):
    """Startup reconciliation: re-sync menus for every known chat."""
    await sync_default_commands(bot)
    for chat_id in db.get_all_chat_ids():
        await sync_commands_for_chat(bot, chat_id)
