"""Telegram lesson-queue bot entry point."""

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import db
from command_menu import sync_all_chats, sync_commands_for_chat
from handlers.buttons import on_button
from handlers.config_handlers import (
    cb_delete_day,
    cb_setlesson_day,
    cb_timer_day,
    cb_window_day,
    cmd_before,
    cmd_delete,
    cmd_duration,
    cmd_setlesson,
    cmd_timer,
)
from handlers.exam_handler import (
    cb_exam_section,
    cb_exam_type,
    cmd_exam,
)
from handlers.helpers import (
    TRIGGER_DELETE_SECONDS,
    cleanup_trigger,
    invalidate_admin_cache,
    is_admin,
    is_group,
    schedule_delete,
)
from handlers.info_handler import cmd_info
from handlers.param_reply import on_param_reply
from handlers.all_handler import cmd_all, learn_group_user, remember_user
from handlers.queue_handlers import cmd_leave, cmd_queue, cmd_setname
from handlers.reuse_handler import cmd_reuse
from handlers.service_cleanup import cleanup_service_message
from handlers.timer_handlers import cb_timer
from handlers.tz_handler import cb_tz, cmd_tz
from i18n import tr
from message_builder import welcome_text
from scheduler import QueueScheduler

load_dotenv()

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context):
    chat = update.effective_chat
    lang = db.get_chat_lang(chat.id) if chat else db.DEFAULT_LANG
    await cleanup_trigger(update, context, seconds=TRIGGER_DELETE_SECONDS)
    msg = await update.effective_message.reply_text(
        welcome_text(lang), parse_mode="HTML"
    )
    if chat and is_group(update):
        await sync_commands_for_chat(context.bot, chat.id)
    schedule_delete(context.bot, msg.chat_id, msg.message_id)


async def on_chat_member(update: Update, context):
    """Welcome + command-menu sync when the bot joins/is promoted, or a user becomes admin."""
    member = update.my_chat_member or update.chat_member
    if not member:
        return
    new = member.new_chat_member
    invalidate_admin_cache(member.chat.id)
    if new.user.id == context.bot.id:
        if new.status in ("member", "administrator", "creator"):
            lang = db.get_chat_lang(member.chat.id)
            msg = await member.chat.send_message(
                welcome_text(lang), parse_mode="HTML"
            )
            await sync_commands_for_chat(context.bot, member.chat.id)
            schedule_delete(context.bot, msg.chat_id, msg.message_id)
            scheduler = context.bot_data.get("scheduler")
            if scheduler:
                await scheduler.catchup_chat(member.chat.id)
        return
    old_status = member.old_chat_member.status if member.old_chat_member else None
    new_status = new.status
    # Remember everyone who joins / stays in the group for /all @mentions.
    if new_status in ("member", "administrator", "creator", "restricted"):
        remember_user(member.chat.id, new.user)
    old_is_admin = old_status in ("administrator", "creator")
    new_is_admin = new_status in ("administrator", "creator")
    if old_is_admin != new_is_admin:
        await sync_commands_for_chat(context.bot, member.chat.id)


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN not set. Copy .env.example to .env and fill it in.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db.init_db()

    application = Application.builder().token(token).build()
    scheduler = QueueScheduler(application)
    application.bot_data["scheduler"] = scheduler

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("queue", cmd_queue))
    application.add_handler(CommandHandler("leave", cmd_leave))
    application.add_handler(CommandHandler("setname", cmd_setname))
    application.add_handler(CommandHandler("info", cmd_info))
    application.add_handler(CommandHandler("setlesson", cmd_setlesson))
    application.add_handler(CommandHandler("before", cmd_before))
    application.add_handler(CommandHandler("duration", cmd_duration))
    application.add_handler(CommandHandler("timer", cmd_timer))
    application.add_handler(CommandHandler("reuse", cmd_reuse))
    application.add_handler(CommandHandler("delete", cmd_delete))
    application.add_handler(CommandHandler("exam", cmd_exam))
    application.add_handler(CommandHandler("tz", cmd_tz))
    application.add_handler(CommandHandler("all", cmd_all))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_param_reply)
    )
    # Learn every group speaker for /all (separate group so other handlers still run).
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL, learn_group_user),
        group=1,
    )
    # Delete ALL service messages (joins, video chats, boosts, gifts...).
    # Catch-all: function itself decides service vs user content, so future
    # Telegram service types are removed even if StatusUpdate.ALL misses them.
    application.add_handler(
        MessageHandler(filters.UpdateType.MESSAGE, cleanup_service_message),
        group=2,
    )
    application.add_handler(CallbackQueryHandler(cb_tz, pattern="^tz_"))
    application.add_handler(CallbackQueryHandler(cb_setlesson_day, pattern="^setlesson_day_"))
    application.add_handler(
        CallbackQueryHandler(cb_window_day, pattern="^(before_day_|duration_day_)")
    )
    application.add_handler(CallbackQueryHandler(cb_delete_day, pattern="^delete_day_"))
    application.add_handler(CallbackQueryHandler(cb_timer_day, pattern="^timer_day_"))
    application.add_handler(CallbackQueryHandler(cb_timer, pattern="^timer_(prev|next|toggle)$"))
    application.add_handler(CallbackQueryHandler(on_button, pattern="^(join|leave)$"))
    application.add_handler(CallbackQueryHandler(cb_exam_type, pattern="^exam_type_"))
    application.add_handler(CallbackQueryHandler(cb_exam_section, pattern="^exam_section_"))
    application.add_handler(
        ChatMemberHandler(on_chat_member, ChatMemberHandler.ANY_CHAT_MEMBER)
    )

    async def post_init(app):
        db.init_db()
        scheduler.start()
        await scheduler.restore()
        await sync_all_chats(app.bot)

    application.post_init = post_init

    logger.info("Starting polling...")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()