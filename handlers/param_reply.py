"""Complete ForceReply parameter prompts for parametric commands."""

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

_ADMIN_COMMANDS = frozenset({"setlesson", "before", "duration", "delete"})

_APPLY = {
    "setname": apply_setname,
    "setlesson": apply_setlesson,
    "before": apply_before,
    "duration": apply_duration,
    "delete": apply_delete,
}


async def on_param_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text replies that complete a pending parameter prompt."""
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if not chat or not user or not message or not message.text:
        return
    if not message.reply_to_message:
        return

    pending = get_pending(chat.id, user.id)
    if pending is None:
        return
    if message.reply_to_message.message_id != pending["prompt_message_id"]:
        return

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
    ok = await apply_fn(update, context, args)
    if not ok:
        # Keep pending so the user can reply again to the same prompt.
        return

    prompt_message_id = pending["prompt_message_id"]
    clear_pending(chat.id, user.id)
    await delete_prompt_best_effort(context.bot, chat.id, prompt_message_id)
