"""Inline button callbacks: join/leave from the pinned message."""

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.all_handler import remember_user
from handlers.helpers import display_name
from i18n import tr
from queue_message import refresh_queue_message


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    chat = query.message.chat if query.message else update.effective_chat
    user = query.from_user
    if not chat or not user:
        await query.answer()
        return

    if query.data == "join":
        await _do_join(update, context)
    elif query.data == "leave":
        await _do_leave(update, context)
    else:
        await query.answer()


def _session_for_message(chat_id, message_id, status="open"):
    """Find the active session whose pinned message was clicked."""
    sessions = db.get_active_messages(chat_id=chat_id, status=status)
    match = next((s for s in sessions if s["message_id"] == message_id), None)
    if match:
        return match
    return sessions[0] if sessions else None


async def _do_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = query.message.chat
    user = query.from_user
    lang = db.get_chat_lang(chat.id)

    session = _session_for_message(chat.id, query.message.message_id, status="open")
    if session is None:
        await query.answer(text=tr(lang, "toast_queue_closed"), show_alert=True)
        return

    lesson_id = session["lesson_id"]
    sdate = session["session_date"]
    name = display_name(user, chat.id)
    remember_user(chat.id, user)
    entry = db.add_queue_entry(chat.id, lesson_id, user.id, name, sdate)
    pos = db.position_of(chat.id, lesson_id, sdate, user.id)
    if entry is None:
        await query.answer(
            text=tr(lang, "toast_already_in", pos=pos), show_alert=True
        )
        return
    await refresh_queue_message(context.bot, chat.id, lesson_id, sdate, lang=lang)
    await query.answer(text=tr(lang, "toast_joined", pos=pos))


async def _do_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = query.message.chat
    user = query.from_user
    lang = db.get_chat_lang(chat.id)

    # Prefer the message that was clicked (open or closed).
    sessions = db.get_active_messages(chat_id=chat.id)
    session = next(
        (s for s in sessions if s["message_id"] == query.message.message_id), None
    )
    candidates = [session] if session else sessions

    for sess in candidates:
        if sess is None:
            continue
        lesson_id = sess["lesson_id"]
        sdate = sess["session_date"]
        pos = db.position_of(chat.id, lesson_id, sdate, user.id)
        if pos is not None:
            db.remove_queue_entry(chat.id, lesson_id, user.id, sdate)
            await refresh_queue_message(context.bot, chat.id, lesson_id, sdate, lang=lang)
            await query.answer(text=tr(lang, "toast_left"))
            return
    await query.answer(text=tr(lang, "toast_not_in_queue"), show_alert=True)
