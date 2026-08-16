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
    cb_window_day,
    cmd_before,
    cmd_delete,
    cmd_duration,
    cmd_setlesson,
)
from handlers.helpers import TRIGGER_DELETE_SECONDS, cleanup_trigger, is_admin, is_group, schedule_delete
from handlers.info_handler import cmd_info
from handlers.param_reply import on_param_reply
from handlers.ping_handler import cmd_ping
from handlers.queue_handlers import cmd_leave, cmd_queue, cmd_setname
from handlers.tz_handler import cb_tz, cmd_tz
from i18n import LANGS, tr
from message_builder import lang_markup, welcome_text
from scheduler import QueueScheduler

load_dotenv()

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context):
    chat = update.effective_chat
    lang = db.get_chat_lang(chat.id) if chat else "en"
    await cleanup_trigger(update, context, seconds=TRIGGER_DELETE_SECONDS)
    msg = await update.effective_message.reply_text(
        welcome_text(lang), parse_mode="HTML"
    )
    if chat and is_group(update):
        await sync_commands_for_chat(context.bot, chat.id)
    schedule_delete(context.bot, msg.chat_id, msg.message_id)


async def cmd_lang(update: Update, context):
    """Pick the chat language (en/ru). Admins only in groups."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat:
        return
    lang = db.get_chat_lang(chat.id)
    if is_group(update) and user and not await is_admin(update, chat.id, user.id):
        from handlers.helpers import reply_ephemeral
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    await cleanup_trigger(update, context, seconds=TRIGGER_DELETE_SECONDS)
    msg = await update.effective_message.reply_text(
        tr(lang, "lang_prompt"), parse_mode="HTML", reply_markup=lang_markup(lang)
    )
    schedule_delete(context.bot, msg.chat_id, msg.message_id)


async def cb_lang(update: Update, context):
    """Apply the chosen chat language from the lang buttons."""
    query = update.callback_query
    chat = query.message.chat
    user = query.from_user
    if not chat or not user:
        await query.answer()
        return
    if not await is_admin(update, chat.id, user.id):
        lang = db.get_chat_lang(chat.id)
        await query.answer(text=tr(lang, "toast_admins_only"), show_alert=True)
        return
    code = query.data.split("_")[-1]
    if code not in ("en", "ru"):
        await query.answer()
        return
    db.set_chat_lang(chat.id, code, title=chat.title)
    await query.edit_message_text(
        tr(code, "lang_prompt"), parse_mode="HTML", reply_markup=lang_markup(code)
    )
    await query.answer(text=tr(code, "lang_set", lang=LANGS[code]))
    schedule_delete(context.bot, query.message.chat_id, query.message.message_id)


async def on_bot_added(update: Update, context):
    """Welcome message when the bot is added to a group; sync command menus."""
    member = update.chat_member
    if member.new_chat_member.user.id != context.bot.id:
        return
    if member.new_chat_member.status in ("member", "administrator"):
        lang = db.get_chat_lang(member.chat.id)
        msg = await member.chat.send_message(
            welcome_text(lang), parse_mode="HTML"
        )
        await sync_commands_for_chat(context.bot, member.chat.id)
        schedule_delete(context.bot, msg.chat_id, msg.message_id)


async def on_member_status_change(update: Update, context):
    """Re-sync command menus when a member is promoted/demoted to/from admin."""
    member = update.chat_member
    if not member or member.new_chat_member.user.id == context.bot.id:
        return
    old = member.old_chat_member.status if member.old_chat_member else None
    new = member.new_chat_member.status if member.new_chat_member else None
    old_is_admin = old in ("administrator", "creator")
    new_is_admin = new in ("administrator", "creator")
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
    application.add_handler(CommandHandler("lang", cmd_lang))
    application.add_handler(CommandHandler("queue", cmd_queue))
    application.add_handler(CommandHandler("leave", cmd_leave))
    application.add_handler(CommandHandler("setname", cmd_setname))
    application.add_handler(CommandHandler("info", cmd_info))
    application.add_handler(CommandHandler("setlesson", cmd_setlesson))
    application.add_handler(CommandHandler("before", cmd_before))
    application.add_handler(CommandHandler("duration", cmd_duration))
    application.add_handler(CommandHandler("delete", cmd_delete))
    application.add_handler(CommandHandler("tz", cmd_tz))
    application.add_handler(CommandHandler("ping", cmd_ping))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_param_reply)
    )
    application.add_handler(CallbackQueryHandler(cb_lang, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(cb_tz, pattern="^tz_"))
    application.add_handler(CallbackQueryHandler(cb_setlesson_day, pattern="^setlesson_day_"))
    application.add_handler(
        CallbackQueryHandler(cb_window_day, pattern="^(before_day_|duration_day_)")
    )
    application.add_handler(CallbackQueryHandler(cb_delete_day, pattern="^delete_day_"))
    application.add_handler(CallbackQueryHandler(on_button, pattern="^(join|leave)$"))
    application.add_handler(ChatMemberHandler(on_bot_added, ChatMemberHandler.ANY_CHAT_MEMBER))
    application.add_handler(
        ChatMemberHandler(on_member_status_change, ChatMemberHandler.CHAT_MEMBER)
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