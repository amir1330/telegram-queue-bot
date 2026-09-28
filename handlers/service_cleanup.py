"""Auto-delete Telegram service messages (joins, leaves, call invites...).

Keeps group chats clean: any status-update message (e.g. "X invited Y to the
call", "X joined the group") is removed best-effort. Requires the bot's
Delete messages admin right (already required for pin/delete features).
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def cleanup_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete the service message that triggered this update."""
    message = update.effective_message
    if not message:
        return
    try:
        await context.bot.delete_message(
            chat_id=message.chat_id, message_id=message.message_id
        )
    except Exception as exc:
        logger.debug("service cleanup: delete failed: %s", exc)
