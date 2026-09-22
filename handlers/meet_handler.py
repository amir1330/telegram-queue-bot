"""On-demand Jitsi rooms: /meet, /endmeet, deep-link join (groups only).

Phase 1 lifecycle: one open session per chat, joins allowed for 5 minutes
(join_deadline). At the deadline the session closes, the group message is
deleted, and /meet works again. Date jobs are persisted/restored on startup;
a running call keeps going after expiry (exp only blocks new joins).
"""

import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import jitsi
from handlers.helpers import (
    cleanup_trigger,
    display_name,
    is_admin,
    is_group,
    reply_ephemeral,
    require_group,
    schedule_delete,
)
from i18n import tr
from message_builder import build_meet_text, meet_message_markup

logger = logging.getLogger(__name__)

MEET_CLOSE_PREFIX = "meet_close"


def _meet_job_id(session_id):
    return f"{MEET_CLOSE_PREFIX}_{session_id}"


def _delete_message_best_effort_sync(bot, chat_id, message_id):
    """Schedule a best-effort delete that ignores 'message not found'."""
    async def _go():
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            logger.debug("meet: delete message %s in %s failed: %s", message_id, chat_id, exc)
    try:
        import asyncio
        asyncio.create_task(_go())
    except RuntimeError:
        pass


async def close_meet_session(bot, session_id, reason="deadline"):
    """Close a session: mark closed, drop its date job, delete group message."""
    session = db.get_meet_session(session_id)
    if not session:
        return
    db.set_meet_session_state(session_id, "closed")
    try:
        from telegram.ext import Application
        app = bot if isinstance(bot, Application) else None
        sched = None
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
    if not jitsi.is_configured():
        await reply_ephemeral(update, context, tr(lang, "meet_unconfigured"))
        return
    blocking = db.get_blocking_meet_session(chat.id)
    if blocking:
        await reply_ephemeral(update, context, tr(lang, "meet_active"))
        return
    room = jitsi.new_room_name("lesson-")
    deadline = time.time() + jitsi.MEET_JOIN_WINDOW_SEC
    session = db.create_meet_session(chat.id, room, user.id, deadline)
    bot_username = (context.bot.username or "").lstrip("@")
    msg = await update.effective_message.reply_text(
        build_meet_text(lang),
        reply_markup=meet_message_markup(bot_username, session["id"], lang),
    )
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
    """APScheduler date-job callback at join_deadline (Phase 1: close)."""
    await close_meet_session(bot, session_id, reason="deadline")


def _parse_deeplink(args):
    """Return meet session id from /start args, or None."""
    if not args:
        return None
    first = args[0]
    if first.startswith("m_"):
        try:
            return int(first[2:])
        except (TypeError, ValueError):
            return None
    return None


async def handle_meet_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """DM handler for t.me/<bot>?start=m_<session_id>. Returns True if handled."""
    session_id = _parse_deeplink(context.args or [])
    if session_id is None:
        return False
    lang = db.DEFAULT_LANG
    session = db.get_meet_session(session_id)
    if not session or session.get("state") != "open":
        await update.effective_message.reply_text(tr(lang, "meet_closed"))
        return True
    if time.time() > float(session["join_deadline"]):
        await update.effective_message.reply_text(tr(lang, "meet_expired"))
        return True
    chat_id = session["chat_id"]
    user = update.effective_user
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        status = str(getattr(member.status, "value", member.status)).lower()
    except Exception as exc:
        logger.debug("meet deeplink: get_chat_member failed: %s", exc)
        await update.effective_message.reply_text(tr(lang, "meet_not_member"))
        return True
    if status not in ("member", "restricted", "administrator", "creator", "owner"):
        await update.effective_message.reply_text(tr(lang, "meet_not_member"))
        return True
    moderator = status in ("administrator", "creator", "owner")
    if not moderator:
        # Re-check admin list (handles edge cases); non-admins stay guests.
        try:
            moderator = await is_admin(update, chat_id, user.id)
        except Exception:
            moderator = False
    name = display_name(user, chat_id)
    if not jitsi.is_configured():
        await update.effective_message.reply_text(tr(lang, "meet_unconfigured"))
        return True
    exp = float(session["join_deadline"]) + 60
    try:
        token = jitsi.make_jwt(session["room"], user.id, name, moderator, exp)
    except RuntimeError:
        await update.effective_message.reply_text(tr(lang, "meet_unconfigured"))
        return True
    url = jitsi.meet_url(session["room"], token)
    chat_lang = db.get_chat_lang(chat_id)
    await update.effective_message.reply_text(
        tr(chat_lang, "meet_dm"),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(tr(chat_lang, "meet_open_btn"), url=url)]]
        ),
    )
    logger.info(
        "meet link issued session=%s chat=%s user=%s moderator=%s",
        session_id, chat_id, user.id, moderator,
    )
    return True
