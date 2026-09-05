"""Reuse previous queue: copy last lesson's list to current open queue."""

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import is_admin, reply_ephemeral, require_group
from i18n import tr
from queue_message import refresh_queue_message


async def cmd_reuse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return

    # find current open queue
    opens = db.get_active_messages(chat_id=chat.id, status="open")
    if not opens:
        await reply_ephemeral(update, context, tr(lang, "reuse_no_open"))
        return
    # pick the open session (prefer exact match if multiple, take first)
    cur = opens[0]
    cur_lesson_id = cur["lesson_id"]
    cur_session = cur["session_date"]

    prev = db.get_last_queue(chat.id, before_session_date=cur_session)
    if not prev:
        # fallback: try any previous queue before today without filter
        prev = db.get_last_queue(chat.id)
        # if prev is same session, ignore
        if prev and prev["session_date"] == cur_session:
            prev = None
    if not prev:
        await reply_ephemeral(update, context, tr(lang, "reuse_no_prev"))
        return

    n = db.copy_queue(chat.id, prev["lesson_id"], prev["session_date"], cur_lesson_id, cur_session)
    if n == 0:
        await reply_ephemeral(update, context, tr(lang, "reuse_no_prev"))
        return

    # reset timer to first person and pause
    timer = db.get_active_timer(chat.id, cur_lesson_id, cur_session)
    if timer:
        db.update_active_timer(chat.id, cur_lesson_id, cur_session, current_index=0, running=0, started_at=None)
        scheduler = context.bot_data.get("scheduler")
        if scheduler:
            scheduler._stop_tick(chat.id, cur_lesson_id)

    await refresh_queue_message(context.bot, chat.id, cur_lesson_id, cur_session, lang=lang)
    # also refresh timer if exists (show new current name)
    timer_after = db.get_active_timer(chat.id, cur_lesson_id, cur_session)
    if timer_after:
        scheduler = context.bot_data.get("scheduler")
        if scheduler:
            try:
                await scheduler._refresh_timer_message(chat.id, cur_lesson_id, cur_session)
            except Exception:
                pass

    await reply_ephemeral(update, context, tr(lang, "reuse_done", n=n, prev_date=prev["session_date"]))
