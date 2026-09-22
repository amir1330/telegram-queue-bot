"""Owner-only personal Jitsi rooms (/room) — private chat with the bot only.

Silently ignored for anyone but OWNER_ID. Never uses meet_sessions, so it
never blocks /meet and has no 5-minute limit. Tokens are never logged.
"""

import logging
import os
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
import jitsi
from i18n import tr

logger = logging.getLogger(__name__)

MOD_LINK_TTL_SEC = 8 * 3600
GUEST_LINK_TTL_SEC = 3 * 3600


def owner_id():
    try:
        return int((os.environ.get("OWNER_ID") or "").strip())
    except (TypeError, ValueError):
        return 0


async def cmd_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    if user.id != owner_id() or owner_id() == 0:
        return  # silently ignore non-owners
    if chat.type != "private":
        return  # DM only, silently ignore groups
    lang = db.get_chat_lang(chat.id)
    if not jitsi.is_configured():
        await update.effective_message.reply_text(tr(lang, "meet_unconfigured"))
        return
    raw = " ".join(context.args or [])
    room = jitsi.sanitize_room_name(raw, prefix="room-")
    now = time.time()
    try:
        mod_token = jitsi.make_jwt(room, user.id, "owner", True, now + MOD_LINK_TTL_SEC)
        guest_token = jitsi.make_jwt(room, user.id, "owner", False, now + GUEST_LINK_TTL_SEC)
    except RuntimeError:
        await update.effective_message.reply_text(tr(lang, "meet_unconfigured"))
        return
    mod_url = jitsi.meet_url(room, mod_token)
    guest_url = jitsi.meet_url(room, guest_token)
    await update.effective_message.reply_text(
        tr(lang, "room_text", room=room),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(tr(lang, "room_mod_btn"), url=mod_url)],
                [InlineKeyboardButton(tr(lang, "room_guest_btn"), url=guest_url)],
            ]
        ),
    )
    logger.info("room issued room=%s", room)
