"""Complete ForceReply / FSM parameter prompts for parametric commands."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.config_handlers import (
    apply_before,
    apply_delete,
    apply_duration,
    apply_setlesson,
)
from handlers.helpers import is_admin
from handlers.param_prompt import (
    clear_pending,
    delete_prompt_best_effort,
    get_pending,
)
from handlers.queue_handlers import apply_setname
from i18n import tr

logger = logging.getLogger(__name__)

_ADMIN_COMMANDS = frozenset({"setlesson", "before", "duration", "delete"})

_APPLY = {
    "setname": apply_setname,
    "setlesson": apply_setlesson,
    "before": apply_before,
    "duration": apply_duration,
    "delete": apply_delete,
}


def _is_reply_to_bot(message, bot_id: int) -> bool:
    replied = message.reply_to_message
    if not replied or not replied.from_user:
        return False
    return replied.from_user.id == bot_id


async def on_param_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle follow-up text that completes a pending parameter prompt.

    Accepts:
    - a reply to the bot's prompt message, or
    - any non-command text from the same (chat_id, user_id) while pending (FSM),
      which covers clients that don't attach reply_to reliably.
    """
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if not chat or not user or not message or not message.text:
        return

    pending = get_pending(chat.id, user.id)
    if pending is None:
        # User replied to an old bot prompt after restart/TTL — tell them why.
        if _is_reply_to_bot(message, context.bot.id):
            lang = db.get_chat_lang(chat.id)
            await message.reply_text(tr(lang, "prompt_expired"))
            logger.info(
                "param reply ignored: no pending chat=%s user=%s", chat.id, user.id
            )
        return

    replied = message.reply_to_message
    if replied is not None:
        # If they replied to some other message (not our prompt / not the bot),
        # leave pending alone and ignore — they are chatting.
        if replied.message_id != pending["prompt_message_id"] and not _is_reply_to_bot(
            message, context.bot.id
        ):
            return
    # else: bare text while pending — accept (FSM fallback for group clients)

    command = pending["command"]
    apply_fn = _APPLY.get(command)
    if apply_fn is None:
        clear_pending(chat.id, user.id)
        return

    if command in _ADMIN_COMMANDS:
        if not await is_admin(update, chat.id, user.id):
            lang = db.get_chat_lang(chat.id)
            await message.reply_text(tr(lang, "admin_only"))
            clear_pending(chat.id, user.id)
            return

    args = message.text.split()
    logger.info(
        "param reply apply command=%s chat=%s user=%s args=%r",
        command, chat.id, user.id, args,
    )
    ok = await apply_fn(update, context, args)
    if not ok:
        return

    prompt_message_id = pending["prompt_message_id"]
    clear_pending(chat.id, user.id)
    await delete_prompt_best_effort(context.bot, chat.id, prompt_message_id)
