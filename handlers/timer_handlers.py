"""Timer inline buttons: prev/next/toggle."""

import asyncio
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

import db
from i18n import tr
from queue_message import refresh_queue_message


def _find_timer_by_message(chat_id, message_id):
    for t in db.get_active_timers(chat_id=chat_id):
        if t["message_id"] == message_id:
            return t
    return None


async def cb_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    chat = query.message.chat if query.message else update.effective_chat
    if not chat:
        await query.answer()
        return
    data = query.data  # timer_prev, timer_next, timer_toggle
    # find timer row by message_id
    timer = _find_timer_by_message(chat.id, query.message.message_id)
    if timer is None:
        # fallback to any active timer in chat (like queue buttons do)
        timers = db.get_active_timers(chat_id=chat.id)
        timer = timers[0] if timers else None
    if timer is None:
        lang = db.get_chat_lang(chat.id)
        await query.answer(text=tr(lang, "toast_queue_closed"), show_alert=True)
        return

    lesson = db.get_lesson_by_id(timer["lesson_id"])
    if not lesson:
        await query.answer()
        return
    chat_id = timer["chat_id"]
    lesson_id = timer["lesson_id"]
    session_date = timer["session_date"]
    lang = db.get_chat_lang(chat_id)
    entries = db.get_queue(chat_id, lesson_id, session_date)
    scheduler = context.bot_data.get("scheduler")

    if data == "timer_prev":
        if not entries:
            await query.answer()
            return
        new_index = (timer["current_index"] - 1) % len(entries)
        timer_sec = lesson.get("answer_timer_sec") or 300
        # stop tick if running
        if scheduler:
            scheduler._stop_tick(chat_id, lesson_id)
        db.update_active_timer(chat_id, lesson_id, session_date, current_index=new_index, remaining_seconds=timer_sec, running=0, started_at=None)
        if scheduler:
            await scheduler._refresh_timer_message(chat_id, lesson_id, session_date)
        # small gap to avoid Flood (timer+queue edits in same callback)
        await asyncio.sleep(0.35)
        # also refresh queue message to move << marker
        try:
            await refresh_queue_message(context.bot, chat_id, lesson_id, session_date, lang=lang)
        except Exception:
            pass
        await query.answer()
        return

    if data == "timer_next":
        if not entries:
            await query.answer()
            return
        new_index = (timer["current_index"] + 1) % len(entries)
        timer_sec = lesson.get("answer_timer_sec") or 300
        if scheduler:
            scheduler._stop_tick(chat_id, lesson_id)
        db.update_active_timer(chat_id, lesson_id, session_date, current_index=new_index, remaining_seconds=timer_sec, running=0, started_at=None)
        if scheduler:
            await scheduler._refresh_timer_message(chat_id, lesson_id, session_date)
        await asyncio.sleep(0.35)
        try:
            await refresh_queue_message(context.bot, chat_id, lesson_id, session_date, lang=lang)
        except Exception:
            pass
        await query.answer()
        return

    if data == "timer_toggle":
        # compute current remaining if running
        if timer.get("running"):
            # stop
            remaining = timer["remaining_seconds"]
            started_at = timer.get("started_at")
            if started_at:
                try:
                    start_dt = datetime.fromisoformat(started_at)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    elapsed = int((now - start_dt).total_seconds())
                    remaining = max(0, timer["remaining_seconds"] - elapsed)
                except Exception:
                    pass
            db.update_active_timer(chat_id, lesson_id, session_date, remaining_seconds=remaining, running=0, started_at=None)
            if scheduler:
                scheduler._stop_tick(chat_id, lesson_id)
                await scheduler._refresh_timer_message(chat_id, lesson_id, session_date)
            await query.answer()
            return
        else:
            # start - if already 0, reset to full?
            remaining = timer["remaining_seconds"]
            if remaining <= 0:
                remaining = lesson.get("answer_timer_sec") or 300
                db.update_active_timer(chat_id, lesson_id, session_date, remaining_seconds=remaining)
                timer["remaining_seconds"] = remaining
            now_iso = datetime.now(timezone.utc).isoformat()
            db.update_active_timer(chat_id, lesson_id, session_date, running=1, started_at=now_iso)
            if scheduler:
                scheduler._start_tick(chat_id, lesson_id)
                await scheduler._refresh_timer_message(chat_id, lesson_id, session_date)
            await query.answer()
            return

    await query.answer()
