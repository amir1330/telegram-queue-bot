"""Inline button callbacks: join/leave from the pinned message."""

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import display_name, today
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


async def _do_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = query.message.chat
    user = query.from_user
    lang = db.get_chat_lang(chat.id)
    sdate = today(chat.id)

    sessions = db.get_active_messages(chat_id=chat.id, session_date=sdate, status="open")
    if not sessions:
        await query.answer(text=tr(lang, "toast_queue_closed"), show_alert=True)
        return
    session = sessions[0]
    lesson_id = session["lesson_id"]

    name = display_name(user, chat.id)
    db.touch_known_user(chat.id, user.id, name)
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
    sdate = today(chat.id)

    for session in db.get_active_messages(chat_id=chat.id, session_date=sdate):
        lesson_id = session["lesson_id"]
        pos = db.position_of(chat.id, lesson_id, sdate, user.id)
        if pos is not None:
            db.remove_queue_entry(chat.id, lesson_id, user.id, sdate)
            await refresh_queue_message(context.bot, chat.id, lesson_id, sdate, lang=lang)
            await query.answer(text=tr(lang, "toast_left"))
            return
    await query.answer(text=tr(lang, "toast_not_in_queue"), show_alert=True)