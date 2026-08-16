"""Complete parameter prompts for parametric commands.

Accepts:
- a reply to the bot's prompt, or
- a top-level message from the same (chat_id, user_id) while pending,
  but only if the text looks like an answer (so normal chat is ignored).

Note: in groups with Bot Privacy Mode ON, Telegram may not deliver bare
text to the bot at all — then a Reply (or disabling privacy) is required.
"""

import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.config_handlers import (
    apply_before,
    apply_delete,
    apply_duration,
    apply_setlesson,
    apply_setlesson_time,
    parse_setlesson_payload,
)
from handlers.helpers import is_admin, reply_ephemeral, schedule_delete
from handlers.param_prompt import (
    clear_pending,
    delete_prompt_best_effort,
    get_pending,
)
from handlers.queue_handlers import apply_setname
from i18n import tr

logger = logging.getLogger(__name__)

_ADMIN_COMMANDS = frozenset({"setlesson", "setlesson_time", "before", "duration", "delete"})

_APPLY = {
    "setname": apply_setname,
    "setlesson": apply_setlesson,
    "before": apply_before,
    "duration": apply_duration,
    "delete": apply_delete,
}

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _looks_like_answer(command: str, text: str) -> bool:
    """True if bare chat text is short/shaped like a param answer, not free chat."""
    text = (text or "").strip()
    if not text or "\n" in text:
        return False
    if command == "setlesson_time":
        return bool(_TIME_RE.match(text))
    if command == "setname":
        return 0 < len(text) <= 60
    if command in ("before", "duration"):
        parts = text.split()
        if len(parts) == 1:
            return parts[0].isdigit()
        if len(parts) == 2:
            return parts[1].isdigit()
        return False
    if command == "delete":
        return len(text.split()) == 1 and len(text) <= 40
    if command == "setlesson":
        parts = text.split()
        return len(parts) >= 2 and bool(_TIME_RE.match(parts[-1]))
    return len(text) <= 80


def _is_bot_message(message, bot_id: int) -> bool:
    return bool(message and message.from_user and message.from_user.id == bot_id)


async def on_param_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Complete a pending prompt from a reply or a short follow-up message."""
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if not chat or not user or not message or not message.text:
        return

    pending = get_pending(chat.id, user.id)
    if pending is None:
        return

    replied = message.reply_to_message
    if replied is not None:
        # Reply to our prompt, or to any bot message while pending.
        if replied.message_id != pending["prompt_message_id"] and not _is_bot_message(
            replied, context.bot.id
        ):
            return
    else:
        # Bare chat text: only if it looks like the expected answer.
        if not _looks_like_answer(pending["command"], message.text):
            return

    command = pending["command"]
    if command in _ADMIN_COMMANDS:
        if not await is_admin(update, chat.id, user.id):
            await reply_ephemeral(update, context, tr(db.get_chat_lang(chat.id), "admin_only"))
            clear_pending(chat.id, user.id)
            return

    args = message.text.split()
    logger.info(
        "param reply apply command=%s chat=%s user=%s args=%r payload=%r reply=%s",
        command, chat.id, user.id, args, pending.get("payload"), replied is not None,
    )

    ui_message_id = None
    if command == "setlesson_time":
        day, ui_message_id = parse_setlesson_payload(pending.get("payload"))
        if not day:
            clear_pending(chat.id, user.id)
            return
        ok = await apply_setlesson_time(update, context, args, day)
    else:
        apply_fn = _APPLY.get(command)
        if apply_fn is None:
            clear_pending(chat.id, user.id)
            return
        ok = await apply_fn(update, context, args)

    if not ok:
        return

    prompt_message_id = pending["prompt_message_id"]
    clear_pending(chat.id, user.id)
    await delete_prompt_best_effort(context.bot, chat.id, prompt_message_id)
    if ui_message_id:
        schedule_delete(context.bot, chat.id, ui_message_id, seconds=0)
