"""Per-(chat, user) ForceReply prompts for parametric group commands."""

import logging
import time

from telegram import ForceReply, Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import TRIGGER_DELETE_SECONDS, cleanup_trigger, is_group

logger = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 600  # 10 minutes


def _purge_expired() -> None:
    db.purge_expired_param_pending(time.time() - PENDING_TTL_SECONDS)


def get_pending(chat_id: int, user_id: int) -> dict | None:
    """Return pending entry for (chat_id, user_id), or None if missing/expired."""
    _purge_expired()
    return db.get_param_pending(chat_id, user_id)


def clear_pending(chat_id: int, user_id: int) -> None:
    db.clear_param_pending(chat_id, user_id)


def set_pending(
    chat_id: int,
    user_id: int,
    command: str,
    prompt_message_id: int,
    payload: str | None = None,
) -> None:
    _purge_expired()
    db.set_param_pending(
        chat_id, user_id, command, prompt_message_id, time.time(), payload=payload
    )


async def start_param_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    command: str,
    prompt_text: str,
    payload: str | None = None,
) -> None:
    """Ask for a parameter via ForceReply and remember pending state for this user."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not update.effective_message:
        return
    clear_pending(chat.id, user.id)
    # Remove the triggering /command in groups (not callback button messages).
    if is_group(update) and not update.callback_query:
        await cleanup_trigger(update, context, seconds=TRIGGER_DELETE_SECONDS)

    # Mention the caller so ForceReply(selective=True) targets only them.
    # Also tell them they can just type the answer (works when privacy is off
    # or when the client attaches a reply automatically).
    if user.username:
        text = f"@{user.username}\n{prompt_text}"
        parse_mode = None
    else:
        text = f"{user.mention_html()}\n{prompt_text}"
        parse_mode = "HTML"

    # Prefer sending after a button tap from that message; otherwise reply
    # to the user's command so ForceReply binds to them more reliably.
    if update.callback_query and update.callback_query.message:
        send = update.callback_query.message.reply_text
    else:
        send = update.effective_message.reply_text

    msg = await send(
        text,
        parse_mode=parse_mode,
        reply_markup=ForceReply(
            selective=True,
            input_field_placeholder=prompt_text[:64],
        ),
    )
    set_pending(chat.id, user.id, command, msg.message_id, payload=payload)
    logger.info(
        "param prompt started command=%s chat=%s user=%s prompt_msg=%s payload=%r",
        command, chat.id, user.id, msg.message_id, payload,
    )


async def delete_prompt_best_effort(bot, chat_id: int, prompt_message_id: int) -> None:
    """Best-effort delete of the intermediate prompt message."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=prompt_message_id)
    except Exception as exc:
        logger.debug("param prompt delete failed: %s", exc)
