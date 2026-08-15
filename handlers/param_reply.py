"""Complete ForceReply parameter prompts for parametric commands.

Only accepts a reply *to the bot's prompt message*. Bare chat text is ignored
so normal conversation is never treated as a command answer or deleted.
"""

import logging

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


async def on_param_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a reply to the bot's ForceReply prompt only."""
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if not chat or not user or not message or not message.text:
        return

    replied = message.reply_to_message
    if replied is None:
        return  # never consume top-level chat messages

    pending = get_pending(chat.id, user.id)
    if pending is None:
        return  # stale reply to an old bot message — ignore silently

    if replied.message_id != pending["prompt_message_id"]:
        return  # replied to something else — leave chat alone

    command = pending["command"]
    if command in _ADMIN_COMMANDS:
        if not await is_admin(update, chat.id, user.id):
            await reply_ephemeral(update, context, tr(db.get_chat_lang(chat.id), "admin_only"))
            clear_pending(chat.id, user.id)
            return

    args = message.text.split()
    logger.info(
        "param reply apply command=%s chat=%s user=%s args=%r payload=%r",
        command, chat.id, user.id, args, pending.get("payload"),
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
