"""Lesson configuration commands (admin only)."""

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import (
    bot_has_pin_rights,
    is_admin,
    is_group,
    reply_ephemeral,
    reply_keep,
)
from handlers.param_prompt import start_param_prompt
from i18n import tr
from message_builder import day_long, lesson_days_markup, setlesson_day_markup
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


def parse_setlesson_payload(raw):
    """Return (day_key, optional_ui_message_id) from pending payload."""
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("day"), data.get("ui_message_id")
    except (TypeError, json.JSONDecodeError):
        pass
    return raw, None


async def apply_setlesson(update: Update, context: ContextTypes.DEFAULT_TYPE, args) -> bool:
    """Apply lesson day/time from arg tokens. Returns True on success."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    lang = db.get_chat_lang(chat.id)
    if len(args) < 2:
        await reply_ephemeral(update, context, tr(lang, "usage_setlesson"))
        return False
    day_of_week = _parse_day(args[0])
    lesson_time = _parse_time(args[1])
    if day_of_week is None or lesson_time is None:
        await reply_ephemeral(update, context, tr(lang, "invalid_input"))
        return False
    return await _save_lesson(update, context, day_of_week, lesson_time)


async def apply_setlesson_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args, day_of_week: str
) -> bool:
    """Apply lesson time for a day already chosen via buttons. Returns True on success."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    lang = db.get_chat_lang(chat.id)
    if not args:
        await reply_ephemeral(update, context, tr(lang, "prompt_setlesson_time"))
        return False
    lesson_time = _parse_time(args[0])
    if lesson_time is None:
        await reply_ephemeral(update, context, tr(lang, "invalid_time"))
        return False
    if day_of_week not in DAYS_EN:
        await reply_ephemeral(update, context, tr(lang, "invalid_day"))
        return False
    return await _save_lesson(update, context, day_of_week, lesson_time)


async def _save_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE, day_of_week, lesson_time) -> bool:
    chat = update.effective_chat
    lang = db.get_chat_lang(chat.id)

    existing = db.get_lessons(chat.id)
    suppress = next((l for l in existing if l["day_of_week"] == day_of_week), None)
    exclude_lesson_id = suppress["lesson_id"] if suppress else None
    overlap = _overlaps(existing, day_of_week, lesson_time, exclude_lesson_id=exclude_lesson_id)
    if overlap:
        other = day_long(lang, overlap["day_of_week"])
        await reply_ephemeral(
            update,
            context,
            tr(
                lang, "lesson_overlap",
                other=other, time=overlap["lesson_time"],
                ob=overlap["open_before_min"], lt=overlap["lifetime_min"],
            ),
        )
        return False

    lesson = db.add_lesson(
        chat.id, day_of_week, lesson_time,
        title=chat.title,
    )
    db.set_last_lesson(chat.id, lesson["lesson_id"])
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        scheduler.schedule_lesson(lesson)
    await reply_ephemeral(
        update,
        context,
        tr(
            lang,
            "lesson_set",
            day=day_long(lang, lesson["day_of_week"]),
            time=lesson["lesson_time"],
            ob=lesson["open_before_min"],
        ),
    )
    return True


async def cmd_setlesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    lang = db.get_chat_lang(chat.id) if chat else "en"
    if not is_group(update) or not chat or not user:
        return
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    if not await bot_has_pin_rights(context, chat.id):
        await reply_ephemeral(
            update, context, tr(lang, "need_admin_rights"), parse_mode="HTML"
        )
        return

    args = context.args or []
    if not args:
        await reply_keep(
            update,
            context,
            tr(lang, "prompt_setlesson_day"),
            reply_markup=setlesson_day_markup(lang),
        )
        return
    if len(args) == 1:
        day_of_week = _parse_day(args[0])
        if day_of_week is None:
            await reply_ephemeral(update, context, tr(lang, "invalid_day"))
            return
        await start_param_prompt(
            update,
            context,
            "setlesson_time",
            tr(lang, "prompt_setlesson_time"),
            payload=day_of_week,
        )
        return
    await apply_setlesson(update, context, args)


async def cb_setlesson_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin picked a weekday button — ask only for HH:MM next."""
    query = update.callback_query
    chat = query.message.chat if query.message else None
    user = query.from_user
    if not chat or not user:
        await query.answer()
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await query.answer(text=tr(lang, "toast_admins_only"), show_alert=True)
        return
    day_of_week = query.data.rsplit("_", 1)[-1]
    if day_of_week not in DAYS_EN:
        await query.answer()
        return
    await query.answer()
    try:
        await query.edit_message_text(
            tr(lang, "setlesson_day_picked", day=day_long(lang, day_of_week))
        )
    except Exception:
        pass
    payload = json.dumps(
        {"day": day_of_week, "ui_message_id": query.message.message_id}
    )
    await start_param_prompt(
        update,
        context,
        "setlesson_time",
        tr(lang, "prompt_setlesson_time"),
        payload=payload,
    )


async def cmd_before(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _window_command(update, context, field="open_before_min")


async def cmd_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _window_command(update, context, field="lifetime_min")


async def apply_before(update: Update, context: ContextTypes.DEFAULT_TYPE, args) -> bool:
    return await apply_window(update, context, args, field="open_before_min")


async def apply_duration(update: Update, context: ContextTypes.DEFAULT_TYPE, args) -> bool:
    return await apply_window(update, context, args, field="lifetime_min")


async def _window_command(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str):
    chat = update.effective_chat
    user = update.effective_user
    if not is_group(update) or not chat or not user:
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return

    if not context.args:
        lessons = db.get_lessons(chat.id)
        if not lessons:
            await reply_ephemeral(update, context, tr(lang, "no_lesson_yet"))
            return
        day_prompt = (
            "prompt_before_day" if field == "open_before_min" else "prompt_duration_day"
        )
        prefix = "before_day" if field == "open_before_min" else "duration_day"
        await reply_keep(
            update,
            context,
            tr(lang, day_prompt),
            reply_markup=lesson_days_markup(lang, lessons, prefix),
        )
        return
    await apply_window(update, context, context.args, field=field)


async def cb_window_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin picked a lesson day for /before or /duration — ask for minutes."""
    query = update.callback_query
    chat = query.message.chat if query.message else None
    user = query.from_user
    if not chat or not user:
        await query.answer()
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await query.answer(text=tr(lang, "toast_admins_only"), show_alert=True)
        return

    data = query.data or ""
    if data.startswith("before_day_"):
        command = "before"
        prompt_key = "prompt_before"
        day_of_week = data[len("before_day_") :]
    elif data.startswith("duration_day_"):
        command = "duration"
        prompt_key = "prompt_duration"
        day_of_week = data[len("duration_day_") :]
    else:
        await query.answer()
        return

    if day_of_week not in DAYS_EN:
        await query.answer()
        return
    lesson = next(
        (l for l in db.get_lessons(chat.id) if l["day_of_week"] == day_of_week),
        None,
    )
    if lesson is None:
        await query.answer(text=tr(lang, "no_lesson_yet"), show_alert=True)
        return

    await query.answer()
    try:
        await query.edit_message_text(
            tr(
                lang,
                "window_day_picked",
                day=day_long(lang, day_of_week),
                time=lesson["lesson_time"],
            )
        )
    except Exception:
        pass
    payload = json.dumps(
        {"day": day_of_week, "ui_message_id": query.message.message_id}
    )
    await start_param_prompt(
        update,
        context,
        command,
        tr(lang, prompt_key),
        payload=payload,
    )


async def apply_window(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args, field: str
) -> bool:
    """Apply open-before / lifetime from arg tokens. Returns True on success."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    lang = db.get_chat_lang(chat.id)
    cmd = "/before" if field == "open_before_min" else "/duration"

    day_of_week = None
    value_text = None
    if len(args) == 2:
        day_of_week = _parse_day(args[0])
        if day_of_week is None:
            await reply_ephemeral(update, context, tr(lang, "invalid_day"))
            return False
        value_text = args[1]
    elif len(args) == 1:
        value_text = args[0]

    if value_text is None or not value_text.strip().isdigit():
        await reply_ephemeral(update, context, tr(lang, "usage_window", cmd=cmd))
        return False
    value = int(value_text.strip())
    if not (1 <= value <= 1440):
        await reply_ephemeral(update, context, tr(lang, "value_range"))
        return False

    if day_of_week is not None:
        lesson = next(
            (l for l in db.get_lessons(chat.id) if l["day_of_week"] == day_of_week),
            None,
        )
        if lesson is None:
            await reply_ephemeral(
                update, context, tr(lang, "no_lesson_day", day=day_long(lang, day_of_week))
            )
            return False
    else:
        lesson = db.get_last_lesson(chat.id)
        if lesson is None:
            await reply_ephemeral(update, context, tr(lang, "no_lesson_yet"))
            return False
    lesson = db.update_lesson_window(lesson["lesson_id"], **{field: value})
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        scheduler.schedule_lesson(lesson)
    set_key = "window_set_before" if field == "open_before_min" else "window_set_duration"
    await reply_ephemeral(
        update,
        context,
        tr(
            lang,
            set_key,
            value=value,
            day=day_long(lang, lesson["day_of_week"]),
            time=lesson["lesson_time"],
        ),
    )
    return True


async def apply_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, args) -> bool:
    """Remove a lesson by day token. Returns True on success."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    lang = db.get_chat_lang(chat.id)
    if not args:
        await reply_ephemeral(update, context, tr(lang, "usage_delete"))
        return False
    day_of_week = _parse_day(args[0])
    if day_of_week is None:
        await reply_ephemeral(update, context, tr(lang, "invalid_day"))
        return False

    lesson = next(
        (l for l in db.get_lessons(chat.id) if l["day_of_week"] == day_of_week),
        None,
    )
    if lesson is None:
        await reply_ephemeral(
            update, context, tr(lang, "no_lesson_day", day=day_long(lang, day_of_week))
        )
        return False

    # Snapshot live messages before DB wipe so we can unpin / strip buttons.
    actives = [
        r for r in db.get_active_messages(chat_id=chat.id)
        if r["lesson_id"] == lesson["lesson_id"]
    ]
    removed_id = db.remove_lesson(chat.id, day_of_week)
    if removed_id is None:
        await reply_ephemeral(
            update, context, tr(lang, "no_lesson_day", day=day_long(lang, day_of_week))
        )
        return False

    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        try:
            scheduler.unschedule_lesson(chat.id, removed_id)
        except Exception as exc:
            logger.warning("delete: unschedule failed: %s", exc)
        for row in actives:
            try:
                await scheduler.discard_queue_message(
                    chat.id, removed_id, row["session_date"], row["message_id"], lang=lang
                )
            except Exception as exc:
                logger.warning("delete: discard message failed: %s", exc)

    await reply_ephemeral(
        update, context, tr(lang, "removed_lesson", day=day_long(lang, day_of_week))
    )
    return True


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not is_group(update) or not chat or not user:
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    if not context.args:
        lessons = db.get_lessons(chat.id)
        if not lessons:
            await reply_ephemeral(update, context, tr(lang, "no_lesson_yet"))
            return
        await reply_keep(
            update,
            context,
            tr(lang, "prompt_delete_day"),
            reply_markup=lesson_days_markup(lang, lessons, "delete_day"),
        )
        return
    await apply_delete(update, context, context.args)


async def cb_delete_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin picked a lesson day for /delete — remove it immediately."""
    query = update.callback_query
    chat = query.message.chat if query.message else None
    user = query.from_user
    if not chat or not user:
        await query.answer()
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await query.answer(text=tr(lang, "toast_admins_only"), show_alert=True)
        return

    day_of_week = (query.data or "").removeprefix("delete_day_")
    if day_of_week not in DAYS_EN:
        await query.answer()
        return

    await query.answer()
    ok = await apply_delete(update, context, [day_of_week])
    if ok:
        try:
            await query.message.delete()
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
    else:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
