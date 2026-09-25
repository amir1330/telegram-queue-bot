"""Shared live-edit of ask poll messages (mirrors queue_message.py).

One asyncio lock per session serializes edits; a 0.4s throttle matches the
queue behavior so Telegram flood limits are not hit.
"""

import asyncio
import logging
import time

from telegram import Bot
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

import db
from message_builder import ask_markup, build_ask_text

logger = logging.getLogger(__name__)

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

_EDIT_LOCKS: dict[int, asyncio.Lock] = {}
_LAST_EDIT: dict[float, float] = {}


def _lock(session_id: int):
    lock = _EDIT_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _EDIT_LOCKS[session_id] = lock
    return lock


async def refresh_ask_message(bot: Bot, session_id, lang="en"):
    """Re-read responses and edit the ask message in place.

    Open sessions keep option buttons; closed sessions keep the final tally
    with buttons removed. Gone messages mark the session closed.
    """
    session = db.get_ask_session(session_id)
    if session is None:
        return
    ask = db.get_ask(session["ask_id"])
    if ask is None:
        return
    if not session.get("message_id"):
        return
    options = db.get_ask_options(session["ask_id"])
    responses = db.get_ask_responses(session_id)
    user_names = {}
    for row in db.get_known_users(session["chat_id"]):
        user_names[row["user_id"]] = row["display_name"]
    closed = session.get("state") == "closed"
    text = build_ask_text(ask["text"], options, responses, user_names, closed=closed,
                          closes_at=session.get("closes_at"), chat_id=session["chat_id"],
                          lang=lang)
    markup = None if closed else ask_markup(session_id, options)

    lock = _lock(session_id)
    async with lock:
        now = time.monotonic()
        last = _LAST_EDIT.get(session_id, 0)
        wait = 0.4 - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_EDIT[session_id] = time.monotonic()
        try:
            await bot.edit_message_text(
                chat_id=session["chat_id"],
                message_id=session["message_id"],
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except BadRequest as exc:
            msg = str(exc).lower()
            if "message is not modified" in msg:
                return
            if any(m in msg for m in _DELETE_MARKERS):
                logger.warning("refresh_ask: message gone session=%s, closing", session_id)
                db.set_ask_session_state(session_id, "closed")
            else:
                logger.warning("refresh_ask: BadRequest session=%s (kept open): %s", session_id, exc)
        except RetryAfter as exc:
            logger.warning(
                "refresh_ask: Flood RetryAfter %ss session=%s — keeping open",
                getattr(exc, "retry_after", "?"), session_id,
            )
        except (Forbidden, TimedOut, NetworkError) as exc:
            logger.warning(
                "refresh_ask: %s session=%s — keeping open",
                type(exc).__name__, session_id,
            )
        except Exception as exc:
            logger.warning("refresh_ask: unexpected %s session=%s: %s — keeping open",
                           type(exc).__name__, session_id, exc)
