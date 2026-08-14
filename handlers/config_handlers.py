"""Lesson configuration commands (admin only)."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import bot_has_pin_rights, is_admin, is_group
from i18n import tr
from message_builder import day_long, format_lesson_line
from queue_view import DAYS_EN, DAYS_RU

logger = logging.getLogger(__name__)

_DAY_ALIASES = {
    name.lower()[:3]: key
    for key, name in [*DAYS_EN.items(), *DAYS_RU.items()]
}


def _parse_day(text: str):
    return _DAY_ALIASES.get(text.strip().lower()[:3])


def _parse_time(text: str):
    try:
        hh, mm = text.strip().split(":")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            return None
        return f"{int(hh):02d}:{int(mm):02d}"
    except (ValueError, TypeError):
        return None


def _overlaps(lessons, day_of_week, lesson_time, exclude_lesson_id=None):
    """True if an existing same-day lesson's open..lifetime window overlaps."""
    t_now = int(lesson_time[:2]) * 60 + int(lesson_time[3:])
    for lesson in lessons:
        if lesson["day_of_week"] != day_of_week:
            continue
        if exclude_lesson_id is not None and lesson["lesson_id"] == exclude_lesson_id:
            continue
        lt = int(lesson["lesson_time"][:2]) * 60 + int(lesson["lesson_time"][3:])
        existing_start = lt - lesson["open_before_min"]
        existing_end = lt + lesson["lifetime_min"]
        new_start = t_now - 30
        new_end = t_now + 120
        if existing_start < new_end and existing_end > new_start:
            return lesson
    return None


async def cmd_setlesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    lang = db.get_chat_lang(chat.id) if chat else "en"
    if not is_group(update) or not chat or not user:
        return
    if not await is_admin(update, chat.id, user.id):
        await update.effective_message.reply_text(tr(lang, "admin_only"))
        return
    if not await bot_has_pin_rights(context, chat.id):
        await update.effective_message.reply_text(
            tr(lang, "need_admin_rights"), parse_mode="HTML"
        )
        return

    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text(tr(lang, "usage_setlesson"))
        return
    day_of_week = _parse_day(args[0])
    lesson_time = _parse_time(args[1])
    if day_of_week is None or lesson_time is None:
        await update.effective_message.reply_text(tr(lang, "invalid_input"))
        return

    existing = db.get_lessons(chat.id)
    suppress = next((l for l in existing if l["day_of_week"] == day_of_week), None)
    exclude_lesson_id = suppress["lesson_id"] if suppress else None
    overlap = _overlaps(existing, day_of_week, lesson_time, exclude_lesson_id=exclude_lesson_id)
    if overlap:
        other = day_long(lang, overlap["day_of_week"])
        await update.effective_message.reply_text(
            tr(
                lang, "lesson_overlap",
                other=other, time=overlap["lesson_time"],
                ob=overlap["open_before_min"], lt=overlap["lifetime_min"],
            )
        )
        return

    lesson = db.add_lesson(
        chat.id, day_of_week, lesson_time,
        title=chat.title,
    )
    db.set_last_lesson(chat.id, lesson["lesson_id"])
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        scheduler.schedule_lesson(lesson)
    await update.effective_message.reply_text(
        tr(lang, "lesson_set", lesson=format_lesson_line(lesson, lang))
    )


async def cmd_before(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _set_window(update, context, field="open_before_min")


async def cmd_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _set_window(update, context, field="lifetime_min")


async def _set_window(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str):
    chat = update.effective_chat
    user = update.effective_user
    if not is_group(update) or not chat or not user:
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await update.effective_message.reply_text(tr(lang, "admin_only"))
        return

    cmd = "/before" if field == "open_before_min" else "/duration"
    label_key = "label_before" if field == "open_before_min" else "label_duration"
    args = context.args

    day_of_week = None
    value_text = None
    if len(args) == 2:
        day_of_week = _parse_day(args[0])
        if day_of_week is None:
            await update.effective_message.reply_text(tr(lang, "invalid_day"))
            return
        value_text = args[1]
    elif len(args) == 1:
        value_text = args[0]

    if value_text is None or not value_text.strip().isdigit():
        await update.effective_message.reply_text(tr(lang, "usage_window", cmd=cmd))
        return
    value = int(value_text.strip())
    if not (1 <= value <= 1440):
        await update.effective_message.reply_text(tr(lang, "value_range"))
        return

    if day_of_week is not None:
        lesson = next(
            (l for l in db.get_lessons(chat.id) if l["day_of_week"] == day_of_week),
            None,
        )
        if lesson is None:
            await update.effective_message.reply_text(
                tr(lang, "no_lesson_day", day=day_long(lang, day_of_week))
            )
            return
    else:
        lesson = db.get_last_lesson(chat.id)
        if lesson is None:
            await update.effective_message.reply_text(tr(lang, "no_lesson_yet"))
            return
    lesson = db.update_lesson_window(lesson["lesson_id"], **{field: value})
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        scheduler.schedule_lesson(lesson)
    await update.effective_message.reply_text(
        tr(
            lang, "window_set", label=tr(lang, label_key), value=value,
            day=day_long(lang, lesson["day_of_week"]), time=lesson["lesson_time"],
        )
    )


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not is_group(update) or not chat or not user:
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await update.effective_message.reply_text(tr(lang, "admin_only"))
        return
    if not context.args:
        await update.effective_message.reply_text(tr(lang, "usage_delete"))
        return
    day_of_week = _parse_day(context.args[0])
    if day_of_week is None:
        await update.effective_message.reply_text(tr(lang, "invalid_day"))
        return
    removed_id = db.remove_lesson(chat.id, day_of_week)
    if removed_id is None:
        await update.effective_message.reply_text(tr(lang, "no_lesson_day", day=day_long(lang, day_of_week)))
        return
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        try:
            scheduler.unschedule_lesson(chat.id, removed_id)
        except Exception as exc:
            logger.warning("delete: unschedule failed: %s", exc)
    await update.effective_message.reply_text(tr(lang, "removed_lesson", day=day_long(lang, day_of_week)))