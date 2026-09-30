"""Auto-delete Telegram service messages (joins, leaves, video chats, boosts...).

Keeps group chats clean: any service message is removed best-effort. Requires
the bot's Delete messages admin right (already required for pin/delete).
Uses a catch-all heuristic instead of filters.StatusUpdate.ALL so new/future
service types (boosts, gifts, giveaways...) are also removed even on older
python-telegram-bot versions.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# User content: never delete messages carrying these, even without text/caption
# (photo without caption, sticker, voice, poll, location...).
_USER_CONTENT_FIELDS = (
    "photo",
    "video",
    "voice",
    "document",
    "sticker",
    "animation",
    "audio",
    "contact",
    "dice",
    "game",
    "poll",
    "venue",
    "location",
    "invoice",
    "successful_payment",
    "passport_data",
    "paid_media",
    "story",  # forwarded story = user content, keep
)


def is_service_message(message) -> bool:
    """True for Telegram service messages (no user text/media)."""
    if message is None:
        return False
    # Normal user/bot messages: text or caption present -> keep.
    if getattr(message, "text", None) or getattr(message, "caption", None):
        return False
    # User media without caption (sticker, photo, voice...) -> keep.
    for field in _USER_CONTENT_FIELDS:
        if getattr(message, field, None):
            return False
    return True


async def cleanup_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete the service message that triggered this update (catch-all)."""
    message = update.effective_message
    if not message:
        return
    if not is_service_message(message):
        return
    try:
        await context.bot.delete_message(
            chat_id=message.chat_id, message_id=message.message_id
        )
    except Exception as exc:
        # Warning (not debug): silent failures look like "bot ignores video chats".
        # Most common cause: bot is not admin with "Delete messages" right.
        logger.warning(
            "service cleanup: delete failed chat=%s msg=%s: %s",
            getattr(message, "chat_id", "?"),
            getattr(message, "message_id", "?"),
            exc,
        )
