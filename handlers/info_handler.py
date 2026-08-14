"""/info command — current settings + commands, available to everyone."""

from telegram import Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import is_admin
from message_builder import build_info_text
from timezone import offset_label, resolve_tz


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    lessons = db.get_lessons(chat.id)
    lang = db.get_chat_lang(chat.id)
    admin = await is_admin(update, chat.id, user.id)
    zone_name = db.get_chat_timezone(chat.id)
    zone = None
    zone_label = ""
    if zone_name:
        tz = resolve_tz(zone_name)
        if tz is not None:
            zone = zone_name
            zone_label = offset_label(tz)
    text = build_info_text(lessons, is_admin=admin, lang=lang, zone=zone, zone_label=zone_label)
    await update.effective_message.reply_text(text, parse_mode="HTML")