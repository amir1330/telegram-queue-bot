"""Shared live-edit of the pinned queue message (design D4)."""

import asyncio
import logging
import time

from telegram import Bot
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

import db
from message_builder import build_queue_text, queue_markup

logger = logging.getLogger(__name__)

# Only these BadRequest messages mean the queue message is truly gone/inaccessible.
# Everything else (TimedOut/NetworkError/transient) must keep the row open for retry.
_DELETE_MARKERS = (
    "message to edit not found",
    "message to delete not found",
    "message not found",
    "message can't be edited",
    "message cannot be edited",
    "message is not found",
    "chat not found",
    "have no rights to send a message",
    "not enough rights",
    "bot was kicked",
    "bot is not a member",
)


def _should_delete_on_bad_request(exc: BadRequest) -> bool:
    msg = str(exc).lower()
    if "message is not modified" in msg:
        return False
    return any(marker in msg for marker in _DELETE_MARKERS)


_EDIT_LOCKS: dict[int, asyncio.Lock] = {}
_LAST_EDIT: dict[int, float] = {}


async def _throttle(chat_id: int):
    lock = _EDIT_LOCKS.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _EDIT_LOCKS[chat_id] = lock
    async with lock:
        now = time.monotonic()
        last = _LAST_EDIT.get(chat_id, 0)
        wait = 0.4 - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_EDIT[chat_id] = time.monotonic()


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

    await _throttle(chat_id)
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
        if _should_delete_on_bad_request(exc):
            logger.warning(
                "refresh_queue_message: deleting active row chat=%s lesson=%s session=%s (BadRequest: %s)",
                chat_id, lesson_id, session_date, exc,
            )
            db.delete_active_message(chat_id, lesson_id, session_date)
        else:
            # Unexpected BadRequest (e.g. retryable) — keep row open, will be retried on next join/leave
            logger.warning(
                "refresh_queue_message: keeping active row chat=%s lesson=%s session=%s (BadRequest not delete-marker: %s)",
                chat_id, lesson_id, session_date, exc,
            )
    except RetryAfter as exc:
        logger.warning(
            "refresh_queue_message: Flood RetryAfter %ss chat=%s lesson=%s session=%s — keeping open",
            getattr(exc, "retry_after", "?"), chat_id, lesson_id, session_date,
        )
    except Forbidden as exc:
        # Bot kicked / no rights — message is dead, clean up
        if _should_delete_on_bad_request(exc):
            logger.warning(
                "refresh_queue_message: deleting active row chat=%s lesson=%s session=%s (Forbidden: %s)",
                chat_id, lesson_id, session_date, exc,
            )
            db.delete_active_message(chat_id, lesson_id, session_date)
        else:
            logger.warning(
                "refresh_queue_message: Forbidden chat=%s lesson=%s session=%s — keeping open (%s)",
                chat_id, lesson_id, session_date, exc,
            )
    except (TimedOut, NetworkError) as exc:
        # Transient network error — keep row open, do NOT delete. Next refresh will retry.
        logger.warning(
            "refresh_queue_message: transient %s chat=%s lesson=%s session=%s — keeping open",
            type(exc).__name__, chat_id, lesson_id, session_date,
        )
    except Exception as exc:
        # Safety: unknown error — keep open by default, log. Only delete if we have strong signal.
        logger.warning(
            "refresh_queue_message: unexpected %s chat=%s lesson=%s session=%s: %s — keeping open",
            type(exc).__name__, chat_id, lesson_id, session_date, exc,
        )
