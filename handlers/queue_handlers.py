"""Queue commands: join (/queue) and leave (/leave)."""

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import display_name, reply_ephemeral, today
from handlers.param_prompt import start_param_prompt
from i18n import tr
from message_builder import day_long
from queue_message import refresh_queue_message


def _today_sessions(chat_id):
    return db.get_active_messages(chat_id=chat_id, session_date=today(chat_id))


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    lang = db.get_chat_lang(chat.id)
    sessions = _today_sessions(chat.id)
    open_session = next((s for s in sessions if s["status"] == "open"), None)
    if open_session is None:
        if sessions:
            await reply_ephemeral(update, context, tr(lang, "q_closed"))
        else:
            await reply_ephemeral(update, context, tr(lang, "q_none_open"))
        return

    lesson = db.get_lesson_by_id(open_session["lesson_id"])
    name = display_name(user, chat.id)
    sdate = today(chat.id)
    entry = db.add_queue_entry(chat.id, open_session["lesson_id"], user.id, name, sdate)
    if entry is None:
        await reply_ephemeral(update, context, tr(lang, "q_already_in"))
        return
    pos = db.position_of(chat.id, open_session["lesson_id"], sdate, user.id)
    await refresh_queue_message(context.bot, chat.id, open_session["lesson_id"], sdate, lang=lang)
    label = f"{day_long(lang, lesson['day_of_week'])} {lesson['lesson_time']}" if lesson else "today"
    await reply_ephemeral(
        update, context, tr(lang, "q_joined_at", name=name, pos=pos, label=label)
    )


async def cmd_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    lang = db.get_chat_lang(chat.id)
    sessions = _today_sessions(chat.id)
    sdate = today(chat.id)
    for session in sessions:
        pos = db.position_of(chat.id, session["lesson_id"], sdate, user.id)
        if pos is not None:
            db.remove_queue_entry(chat.id, session["lesson_id"], user.id, sdate)
            await refresh_queue_message(context.bot, chat.id, session["lesson_id"], sdate, lang=lang)
            await reply_ephemeral(update, context, tr(lang, "q_left", pos=pos))
            return
    await reply_ephemeral(update, context, tr(lang, "q_not_in"))


async def apply_setname(update: Update, context: ContextTypes.DEFAULT_TYPE, args) -> bool:
    """Apply display name from arg tokens. Returns True on success."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    lang = db.get_chat_lang(chat.id)
    if not args:
        await reply_ephemeral(update, context, tr(lang, "usage_setname"))
        return False
    name = " ".join(args).strip()
    if not name or len(name) > 60:
        await reply_ephemeral(update, context, tr(lang, "setname_too_long"))
        return False
    db.set_user_display_name(chat.id, user.id, name)
    for session in _today_sessions(chat.id):
        await refresh_queue_message(
            context.bot, chat.id, session["lesson_id"], session["session_date"], lang=lang
        )
    await reply_ephemeral(update, context, tr(lang, "setname_set", name=name))
    return True


async def cmd_setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the name shown in this chat's queue (disambiguates same first names)."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    lang = db.get_chat_lang(chat.id)
    if not context.args:
        await start_param_prompt(update, context, "setname", tr(lang, "prompt_setname"))
        return
    await apply_setname(update, context, context.args)
