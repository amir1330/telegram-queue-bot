"""Shared live-edit of the pinned queue message (design D4)."""

from telegram import Bot
from telegram.error import BadRequest

import db
from message_builder import build_queue_text, queue_markup


async def refresh_queue_message(bot: Bot, chat_id, lesson_id, session_date, lang="en"):
    """Re-read the queue and edit the stored pinned message in place.

    Open sessions keep Join/Leave buttons; closed sessions keep the final list
    but with buttons removed. If the message is gone (or we lack rights), drop
    the active-message row so a later refresh does not keep failing.
    """
    row = db.get_active_message(chat_id, lesson_id, session_date)
    if row is None:
        return
    lesson = db.get_lesson_by_id(lesson_id)
    if lesson is None:
        db.delete_active_message(chat_id, lesson_id, session_date)
        return

    closed = row.get("status") == "closed"
    text = build_queue_text(
        lesson,
        session_date,
        db.get_queue(chat_id, lesson_id, session_date),
        lang=lang,
        closed=closed,
    )
    markup = None if closed else queue_markup(lang)

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=row["message_id"],
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return  # no-op, nothing changed — not a failure
        db.delete_active_message(chat_id, lesson_id, session_date)
    except Exception:
        db.delete_active_message(chat_id, lesson_id, session_date)
