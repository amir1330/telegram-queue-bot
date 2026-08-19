"""Timezone configuration (/tz) for chat admins."""

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import (
    AUTO_DELETE_SECONDS,
    bot_has_pin_rights,
    is_admin,
    reply_ephemeral,
    reply_keep,
    require_group,
    schedule_delete,
)
from i18n import tr
from message_builder import tz_markup
from timezone import resolve_tz, offset_label


def _describe(tz):
    key = getattr(tz, "key", None)
    if key:
        return key, offset_label(tz)
    return tz.tzname(None) or str(tz), offset_label(tz)


async def cmd_tz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    if not await bot_has_pin_rights(context, chat.id):
        await reply_ephemeral(
            update, context, tr(lang, "need_admin_rights"), parse_mode="HTML"
        )
        return

    args = context.args
    if args:
        value = " ".join(args).strip()
        tz = resolve_tz(value)
        if tz is None:
            await reply_ephemeral(update, context, tr(lang, "tz_invalid", value=value))
            return
        zone, label = _describe(tz)
        db.set_chat_timezone(chat.id, zone, title=chat.title)
        await reply_ephemeral(update, context, tr(lang, "tz_set", zone=zone, label=label))
        await _resync(context, chat.id)
        return

    zone, label = _current(chat.id)
    text = "\n\n".join(
        [
            tr(lang, "tz_title"),
            tr(lang, "tz_current", zone=zone, label=label),
            tr(lang, "tz_pick_hint"),
        ]
    )
    await reply_keep(
        update, context, text, parse_mode="HTML", reply_markup=tz_markup()
    )


def _current(chat_id):
    name = db.get_chat_timezone(chat_id)
    tz = resolve_tz(name)
    if tz is None:
        import timezone
        return timezone.offset_label(timezone.chat_now(chat_id).tzinfo), ""
    return name, offset_label(tz)


async def cb_tz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = query.message.chat
    user = query.from_user
    lang = db.get_chat_lang(chat.id)
    if not chat or not user:
        await query.answer()
        return
    if not await is_admin(update, chat.id, user.id):
        await query.answer(text=tr(lang, "toast_admins_only"), show_alert=True)
        return
    zone = query.data.split("_", 1)[-1]
    tz = resolve_tz(zone)
    if tz is None:
        await query.answer(text=tr(lang, "tz_invalid", value=zone), show_alert=True)
        return
    zone_name, label = _describe(tz)
    db.set_chat_timezone(chat.id, zone_name, title=chat.title)
    await query.edit_message_text(
        tr(lang, "tz_set", zone=zone_name, label=label), parse_mode="HTML"
    )
    await query.answer()
    schedule_delete(
        context.bot, chat.id, query.message.message_id, seconds=AUTO_DELETE_SECONDS
    )
    await _resync(context, chat.id)


async def _resync(context, chat_id):
    """Re-register lessons so cron times apply under the new timezone."""
    scheduler = context.bot_data.get("scheduler")
    if scheduler is None:
        return
    for lesson in db.get_lessons(chat_id):
        await scheduler.refresh_lesson(lesson)
