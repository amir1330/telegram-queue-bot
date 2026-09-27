"""On-demand Jitsi rooms with plain links: /meet, /endmeet (groups only).

No tokens, no DM step: /meet posts a plain clickable link straight to the
room on the self-hosted site (password auth lives on the site itself).
One open session per chat; at join_deadline (5 min) the session closes, the
group message is deleted, and /meet works again. Date jobs are restored on
startup along with an expiry sweep.
"""

import logging
import os
import secrets
import time

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import (
    cleanup_trigger,
    is_admin,
    reply_ephemeral,
    require_group,
    schedule_delete,
)
from i18n import tr

logger = logging.getLogger(__name__)

MEET_CLOSE_PREFIX = "meet_close"
MEET_JOIN_WINDOW_SEC = 300  # 5 minutes of open joins per /meet


def _meet_job_id(session_id):
    return f"{MEET_CLOSE_PREFIX}_{session_id}"


def jitsi_domain():
    return (os.environ.get("JITSI_DOMAIN") or "").strip().strip("/")


def new_plain_room(chat_id):
    """Room unique enough per chat: chat<abs(chat_id)>-<6 random chars>."""
    return f"chat{abs(int(chat_id))}-{secrets.token_urlsafe(4).lower()}"


def meet_plain_url(room):
    return f"https://{jitsi_domain()}/{room}"


async def close_meet_session(bot, session_id, reason="deadline"):
    """Close a session: mark closed, drop its date job, delete group message."""
    session = db.get_meet_session(session_id)
    if not session:
        return
    db.set_meet_session_state(session_id, "closed")
    try:
        from telegram.ext import Application
        app = bot if isinstance(bot, Application) else None
        if app is not None:
            sched_holder = app.bot_data.get("scheduler")
            if sched_holder is not None:
                try:
                    sched_holder.scheduler.remove_job(_meet_job_id(session_id))
                except Exception:
                    pass
    except Exception:
        pass
    if session.get("message_id"):
        try:
            await bot.delete_message(
                chat_id=session["chat_id"], message_id=session["message_id"]
            )
        except Exception as exc:
            logger.debug(
                "close_meet_session: delete failed chat=%s msg=%s (%s)",
                session["chat_id"], session["message_id"], exc,
            )
    logger.info("meet closed session=%s chat=%s reason=%s", session_id, session["chat_id"], reason)


async def cmd_meet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    if not jitsi_domain():
        await reply_ephemeral(update, context, tr(lang, "meet_unconfigured"))
        return
    blocking = db.get_blocking_meet_session(chat.id)
    if blocking:
        await reply_ephemeral(update, context, tr(lang, "meet_active"))
        return
    room = new_plain_room(chat.id)
    deadline = time.time() + MEET_JOIN_WINDOW_SEC
    session = db.create_meet_session(chat.id, room, user.id, deadline)
    msg = await update.effective_message.reply_text(meet_plain_url(room))
    db.set_meet_session_message(session["id"], msg.message_id)
    await cleanup_trigger(update, context)
    scheduler = context.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.schedule_meet_close(session["id"], deadline)
    logger.info("meet opened session=%s chat=%s room=%s", session["id"], chat.id, room)


async def cmd_endmeet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    blocking = db.get_blocking_meet_session(chat.id)
    await cleanup_trigger(update, context)
    if not blocking:
        await reply_ephemeral(
            update, context, tr(lang, "meet_closed"), delete_trigger=False
        )
        return
    await close_meet_session(context.bot, blocking["id"], reason="endmeet")
    msg = await update.effective_message.reply_text(tr(lang, "meet_ended"))
    schedule_delete(context.bot, msg.chat_id, msg.message_id)


async def on_meet_close_job(bot, session_id):
    """APScheduler date-job callback at join_deadline: close the session."""
    await close_meet_session(bot, session_id, reason="deadline")
