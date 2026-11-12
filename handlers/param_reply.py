"""Complete parameter prompts for parametric commands.

While a prompt is pending for (chat_id, user_id), accept:
- a reply to the bot's prompt message, or
- any short answer-shaped text (bare or reply), so broken ForceReply
  clients that attach reply_to the wrong parent still work.

Long free-chat messages are ignored via shape checks.
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
    apply_timer,
    parse_setlesson_payload,
)
from handlers.exam_handler import apply_exam_grade, apply_exam_name
from handlers.helpers import is_admin, reply_ephemeral, schedule_delete
from handlers.param_prompt import (
    clear_pending,
    delete_prompt_best_effort,
    get_pending,
)
from handlers.queue_handlers import apply_setname
from i18n import tr

logger = logging.getLogger(__name__)

_ADMIN_COMMANDS = frozenset(
    {"setlesson", "setlesson_time", "before", "duration", "delete", "timer", "exam_name", "exam_grade"}
)

_APPLY = {
    "setname": apply_setname,
    "setlesson": apply_setlesson,
    "before": apply_before,
    "duration": apply_duration,
    "timer": apply_timer,
    "delete": apply_delete,
    "exam_name": apply_exam_name,
    "exam_grade": apply_exam_grade,
}

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _looks_like_answer(command: str, text: str) -> bool:
    """True if text is short/shaped like a param answer, not free chat."""
    text = (text or "").strip()
    if not text:
        return False
    if "\n" in text:
        return False
    if command == "setlesson_time":
        return bool(_TIME_RE.match(text))
    if command == "setname":
        return 0 < len(text) <= 60
    if command in ("before", "duration", "timer"):
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
    if command == "exam_name":
        return 0 < len(text) <= 100
    if command == "exam_grade":
        return text.isdigit() and len(text) <= 3
    return len(text) <= 80


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

    command = pending["command"]
    text = message.text
    replied = message.reply_to_message

    if command == "setask_confirm":
        # Terminal wizard step advances via Save/Cancel buttons only, so the
        # flow never depends on Group Privacy. Ignore stray typed text.
        return

    # Some clients attach ForceReply to the wrong parent (e.g. the user's
    # original /setname instead of the bot prompt). Accept either an exact
    # reply to our prompt, or any answer-shaped text while pending.
    is_reply_to_prompt = False
    if replied is not None:
        try:
            is_reply_to_prompt = int(replied.message_id) == int(
                pending["prompt_message_id"]
            )
        except (TypeError, ValueError):
            is_reply_to_prompt = False

    if not is_reply_to_prompt and not _looks_like_answer(command, text):
        return

    if command in _ADMIN_COMMANDS:
        if not await is_admin(update, chat.id, user.id):
            await reply_ephemeral(update, context, tr(db.get_chat_lang(chat.id), "admin_only"))
            clear_pending(chat.id, user.id)
            return

    args = text.split()
    logger.info(
        "param reply apply command=%s chat=%s user=%s args=%r payload=%r "
        "reply_to_prompt=%s reply_to=%s",
        command,
        chat.id,
        user.id,
        args,
        pending.get("payload"),
        is_reply_to_prompt,
        replied.message_id if replied else None,
    )

    ui_message_id = None
    if command == "exam_name":
        ok = await apply_exam_name(update, context, pending.get("payload"))
    elif command == "exam_grade":
        ok = await apply_exam_grade(update, context, pending.get("payload"))
    elif command == "setlesson_time":
        day, ui_message_id = parse_setlesson_payload(pending.get("payload"))
        if not day:
            clear_pending(chat.id, user.id)
            return
        ok = await apply_setlesson_time(update, context, args, day)
    elif command in ("before", "duration", "timer") and pending.get("payload"):
        day, ui_message_id = parse_setlesson_payload(pending.get("payload"))
        if day and len(args) == 1:
            args = [day, args[0]]
        apply_fn = _APPLY[command]
        ok = await apply_fn(update, context, args)
    else:
        apply_fn = _APPLY.get(command)
        if apply_fn is None:
            clear_pending(chat.id, user.id)
            return
        ok = await apply_fn(update, context, args)

    if not ok:
        return

    # Chained wizards (e.g. setask time -> question) start a NEW prompt inside
    # apply, overwriting pending. Only clear when pending is unchanged;
    # otherwise delete just the old prompt and keep the new one.
    prompt_message_id = pending["prompt_message_id"]
    fresh = get_pending(chat.id, user.id)
    chained = (
        fresh is not None
        and (
            fresh.get("command") != command
            or int(fresh.get("prompt_message_id") or 0) != int(prompt_message_id or 0)
        )
    )
    if not chained:
        clear_pending(chat.id, user.id)
    await delete_prompt_best_effort(context.bot, chat.id, prompt_message_id)
    if ui_message_id:
        schedule_delete(context.bot, chat.id, ui_message_id, seconds=0)

