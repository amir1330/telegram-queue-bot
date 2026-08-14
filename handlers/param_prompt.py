"""Per-(chat, user) ForceReply prompts for parametric group commands."""

import logging
import time

from telegram import ForceReply, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 600  # 10 minutes

# (chat_id, user_id) -> {command, prompt_message_id, created_at}
_pending: dict[tuple[int, int], dict] = {}


def _purge_expired(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    expired = [
        key
        for key, entry in _pending.items()
        if now - entry["created_at"] > PENDING_TTL_SECONDS
    ]
    for key in expired:
        _pending.pop(key, None)


def get_pending(chat_id: int, user_id: int) -> dict | None:
    """Return pending entry for (chat_id, user_id), or None if missing/expired."""
    _purge_expired()
    return _pending.get((chat_id, user_id))


def clear_pending(chat_id: int, user_id: int) -> None:
    _pending.pop((chat_id, user_id), None)


def set_pending(chat_id: int, user_id: int, command: str, prompt_message_id: int) -> None:
    _purge_expired()
    _pending[(chat_id, user_id)] = {
        "command": command,
        "prompt_message_id": prompt_message_id,
        "created_at": time.monotonic(),
    }


async def start_param_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    command: str,
    prompt_text: str,
) -> None:
    """Reply with selective ForceReply and store pending state for this user."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not update.effective_message:
        return
    # Replace any previous pending prompt for this user in this chat.
    clear_pending(chat.id, user.id)
    msg = await update.effective_message.reply_text(
        prompt_text,
        reply_markup=ForceReply(selective=True, input_field_placeholder=prompt_text[:64]),
    )
    set_pending(chat.id, user.id, command, msg.message_id)


async def delete_prompt_best_effort(bot, chat_id: int, prompt_message_id: int) -> None:
    """Best-effort delete of the intermediate prompt message."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=prompt_message_id)
    except Exception as exc:
        logger.debug("param prompt delete failed: %s", exc)
