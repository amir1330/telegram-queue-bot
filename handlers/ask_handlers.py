"""Scheduled questions with answers (/setask and friends, admins only).

Full form:
  /setask Monday 12:00 | Are you coming Mon 18:00? | Yes | No | ?I have a reason
Bare /setask walks the admin through day buttons -> time -> question -> options
via the selective ForceReply flow. Times use the chat timezone (/tz) and the
same day/time parser as /setlesson. Option labels cap at 60 chars, reasoning
text at 200 chars; all names/reasons are HTML-escaped on render.
"""

import html
import json
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

import db
from ask_message import refresh_ask_message
from handlers.config_handlers import _parse_day, _parse_time
from handlers.helpers import (
    is_admin,
    reply_ephemeral,
    reply_keep,
    require_group,
    schedule_delete,
)
from handlers.param_prompt import delete_prompt_best_effort, start_param_prompt
from i18n import tr
from message_builder import ask_markup, build_ask_text, day_long, setask_day_markup
from queue_view import DAYS_EN
from timezone import chat_today

logger = logging.getLogger(__name__)

ASK_REASON_TTL_SEC = 180  # pending reason answers expire after 3 minutes
REASON_MAX_LEN = 200
OPTION_MAX_LEN = 60
QUESTION_MAX_LEN = 500
ASK_JOB_PREFIX = "ask_post"
ASK_CLOSE_PREFIX = "ask_close"
REASON_EXPIRE_PREFIX = "ask_reason_expire"


def parse_ask_options(raw):
    """Split 'a | b | ?c' into [(label, needs_reason)]. Leading ? = reason."""
    out = []
    for piece in (raw or "").split("|"):
        label = piece.strip()
        if not label:
            continue
        if label.startswith("?"):
            name = label[1:].strip()
            if name:
                out.append((name[:OPTION_MAX_LEN], True))
        else:
            out.append((label[:OPTION_MAX_LEN], False))
    return out


def parse_setask_full(text):
    """Parse the one-shot form. Returns (day, time, question, options) or None."""
    segments = [s.strip() for s in (text or "").split("|")]
    if len(segments) < 3:
        return None
    head = segments[0].split()
    if len(head) < 2:
        return None
    day = _parse_day(head[0])
    tm = _parse_time(head[-1])
    if day is None or tm is None:
        return None
    question = segments[1].strip()
    options = parse_ask_options("|".join(segments[2:]))
    if not question or len(options) < 2:
        return None
    return day, tm, question[:QUESTION_MAX_LEN], options


async def _save_ask_and_schedule(update, context, day, tm, question, options):
    chat = update.effective_chat
    lang = db.get_chat_lang(chat.id)
    ask = db.create_ask(chat.id, day, tm, question)
    db.set_ask_options(ask["id"], options)
    logger.info(
        "setask saved chat=%s ask=%s day=%s time=%s options=%d",
        chat.id, ask["id"], day, tm, len(options),
    )
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        scheduler.schedule_ask(db.get_ask(ask["id"]))
    await reply_ephemeral(
        update, context,
        tr(lang, "setask_saved", id=ask["num"], day=day_long(lang, day), time=tm),
    )
    return True


async def cmd_setask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    raw = " ".join(context.args or [])
    if raw.strip():
        parsed = parse_setask_full(raw)
        if parsed is None:
            await reply_ephemeral(update, context, tr(lang, "usage_setask"))
            return
        day, tm, question, options = parsed
        await _save_ask_and_schedule(update, context, day, tm, question, options)
        return
    await reply_keep(
        update, context, tr(lang, "prompt_setask_day"),
        reply_markup=setask_day_markup(lang),
    )


async def cb_setask_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    day = (query.data or "").removeprefix("setask_day_")
    if day not in DAYS_EN:
        await query.answer()
        return
    await query.answer()
    try:
        await query.edit_message_text(
            tr(lang, "setask_day_picked", day=day_long(lang, day))
        )
    except Exception:
        pass
    payload = json.dumps({"day": day, "ui_message_id": query.message.message_id})
    await start_param_prompt(
        update, context, "setask_time", tr(lang, "setask_r_time"), payload=payload
    )


def _wizard_payload(raw):
    try:
        data = json.loads(raw or "")
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


async def apply_setask_time(update, context, args, payload_raw=None) -> bool:
    """Wizard step 2: time given, day in payload -> ask for the question."""
    chat = update.effective_chat
    lang = db.get_chat_lang(chat.id)
    data = _wizard_payload(payload_raw)
    day = data.get("day")
    if day not in DAYS_EN:
        await reply_ephemeral(update, context, tr(lang, "invalid_day"))
        return False
    tm = _parse_time((args or [""])[0])
    if tm is None:
        await reply_ephemeral(update, context, tr(lang, "invalid_time"))
        return False
    payload = json.dumps(
        {"day": day, "time": tm, "ui_message_id": data.get("ui_message_id")}
    )
    await start_param_prompt(
        update, context, "setask_question", tr(lang, "setask_r_question"),
        payload=payload,
    )
    return True


async def apply_setask_question(update, context, args, payload_raw=None) -> bool:
    """Wizard step 3: question text -> ask for options."""
    chat = update.effective_chat
    message = update.effective_message
    lang = db.get_chat_lang(chat.id)
    data = _wizard_payload(payload_raw)
    if data.get("day") not in DAYS_EN or not _parse_time(data.get("time") or ""):
        await reply_ephemeral(update, context, tr(lang, "invalid_input"))
        return False
    question = (message.text or "").strip()
    if not question:
        await reply_ephemeral(update, context, tr(lang, "usage_setask"))
        return False
    payload = json.dumps(
        {
            "day": data["day"], "time": data["time"],
            "question": question[:QUESTION_MAX_LEN],
            "ui_message_id": data.get("ui_message_id"),
        }
    )
    await start_param_prompt(
        update, context, "setask_options", tr(lang, "setask_r_options"),
        payload=payload,
    )
    return True


async def apply_setask_options(update, context, args, payload_raw=None) -> bool:
    """Wizard step 4: options given (one per line, ? = needs reason).

    Does NOT save yet: posts a Save/Cancel confirmation (inline buttons work
    with Group Privacy on) and stashes the draft in pending.
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    from handlers.param_prompt import set_pending

    chat = update.effective_chat
    message = update.effective_message
    lang = db.get_chat_lang(chat.id)
    data = _wizard_payload(payload_raw)
    if data.get("day") not in DAYS_EN or not data.get("question"):
        await reply_ephemeral(update, context, tr(lang, "invalid_input"))
        return False
    options = parse_ask_options((message.text or "").replace("\n", "|"))
    if len(options) < 2:
        await reply_ephemeral(update, context, tr(lang, "usage_setask"))
        return False
    opt_lines = "".join(
        tr(
            lang, "setask_confirm_opt", label=label,
            reason=tr(lang, "setask_confirm_reason") if needs_reason else "",
        )
        for label, needs_reason in options
    )
    msg = await message.reply_text(
        tr(
            lang, "setask_confirm", day=day_long(lang, data["day"]),
            time=data["time"], question=data["question"], options=opt_lines,
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(tr(lang, "btn_save"), callback_data="ask_save"),
                    InlineKeyboardButton(tr(lang, "btn_cancel"), callback_data="ask_cancel"),
                ]
            ]
        ),
    )
    draft = {
        "day": data["day"], "time": data["time"], "question": data["question"],
        "options": [[label, needs_reason] for label, needs_reason in options],
        "confirm_message_id": msg.message_id,
        "ui_message_id": data.get("ui_message_id"),
    }
    set_pending(chat.id, update.effective_user.id, "setask_confirm", msg.message_id,
                payload=json.dumps(draft))
    logger.info(
        "setask confirm posted chat=%s user=%s day=%s time=%s options=%d",
        chat.id, update.effective_user.id, data["day"], data["time"], len(options),
    )
    return True


async def cb_ask_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save or discard the stashed setask draft (buttons = privacy-proof)."""
    from handlers.param_prompt import clear_pending, get_pending

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
    action = (query.data or "").removeprefix("ask_")
    pending = get_pending(chat.id, user.id)
    data = _wizard_payload((pending or {}).get("payload"))
    if not pending or pending.get("command") != "setask_confirm" or not data.get("question"):
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    await query.answer()
    if action == "cancel":
        clear_pending(chat.id, user.id)
        try:
            await query.edit_message_text(tr(lang, "setask_cancelled"))
        except Exception:
            pass
        schedule_delete(context.bot, chat.id, query.message.message_id)
        if data.get("ui_message_id"):
            schedule_delete(context.bot, chat.id, data["ui_message_id"], seconds=0)
        return
    options = [(label, bool(nr)) for label, nr in data["options"]]
    ok = await _save_ask_and_schedule(update, context, data["day"], data["time"],
                                      data["question"], options)
    if ok:
        clear_pending(chat.id, user.id)
        try:
            await query.message.delete()
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        if data.get("ui_message_id"):
            schedule_delete(context.bot, chat.id, data["ui_message_id"], seconds=0)


async def cmd_asks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    asks = db.get_asks(chat.id)
    if not asks:
        await reply_ephemeral(update, context, tr(lang, "setask_empty"))
        return
    lines = [
        tr(
            lang, "setask_list_line", id=a["num"],
            day=day_long(lang, a["weekday"]), time=a["time"],
            dur=a["duration_min"], text=a["text"][:80],
        )
        for a in asks
    ]
    await reply_ephemeral(update, context, "\n".join(lines))


async def cmd_delask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await reply_ephemeral(update, context, tr(lang, "usage_delask"))
        return
    num = int(args[0])
    ask = db.get_ask_by_number(chat.id, num)
    if not ask:
        await reply_ephemeral(update, context, tr(lang, "setask_no_id", id=num))
        return
    ask_id = ask["id"]
    scheduler = context.bot_data.get("scheduler")
    if scheduler:
        scheduler.unschedule_ask(chat.id, ask_id)
    db.delete_ask(chat.id, ask_id)
    await reply_ephemeral(update, context, tr(lang, "setask_deleted", id=num))


async def _resolve_ask_duration_target(chat_id, args):
    """Return (ask, minutes) or (None, error_key)."""
    if len(args) == 1 and args[0].isdigit():
        asks = db.get_asks(chat_id)
        if len(asks) != 1:
            return None, "usage_askduration"
        return asks[0], int(args[0])
    if len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        ask = db.get_ask_by_number(chat_id, int(args[0]))
        if not ask:
            return None, "setask_no_id"
        return ask, int(args[1])
    return None, "usage_askduration"


async def cmd_askduration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    args = context.args or []
    if not args:
        await reply_ephemeral(update, context, tr(lang, "usage_askduration"))
        return
    ask, minutes = await _resolve_ask_duration_target(chat.id, args)
    if ask is None:
        key = minutes
        extra = {"id": args[0]} if key == "setask_no_id" else {}
        await reply_ephemeral(update, context, tr(lang, key, **extra))
        return
    if not (1 <= minutes <= 1440):
        await reply_ephemeral(update, context, tr(lang, "askduration_bad"))
        return
    db.set_ask_duration(chat.id, ask["id"], minutes)
    await reply_ephemeral(
        update, context, tr(lang, "askduration_set", id=ask["num"], value=minutes)
    )


async def post_ask_session(bot, ask_id, date_text=None):
    """Post an ask as a new open session. Returns the session row or None."""
    ask = db.get_ask(ask_id)
    if not ask:
        return None
    options = db.get_ask_options(ask_id)
    if not options:
        return None
    if date_text is None:
        date_text = chat_today(ask["chat_id"])
    closes_at = time.time() + int(ask["duration_min"]) * 60
    session = db.create_ask_session(ask_id, ask["chat_id"], date_text, closes_at)
    lang = db.get_chat_lang(ask["chat_id"])
    text = build_ask_text(ask["text"], options, [], {}, closed=False,
                          closes_at=session["closes_at"], chat_id=ask["chat_id"],
                          lang=lang)
    try:
        msg = await bot.send_message(
            chat_id=ask["chat_id"], text=text, parse_mode="HTML",
            reply_markup=ask_markup(session["id"], options),
        )
    except Exception as exc:
        logger.warning("post_ask: send failed chat=%s ask=%s: %s", ask["chat_id"], ask_id, exc)
        db.set_ask_session_state(session["id"], "closed")
        return None
    db.set_ask_session_message(session["id"], msg.message_id)
    return db.get_ask_session(session["id"])


async def cmd_askpost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post an ask right now (testing). Admin only."""
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await reply_ephemeral(update, context, tr(lang, "usage_askpost"))
        return
    ask = db.get_ask_by_number(chat.id, int(args[0]))
    if not ask:
        await reply_ephemeral(update, context, tr(lang, "setask_no_id", id=args[0]))
        return
    session = await post_ask_session(context.bot, ask["id"])
    scheduler = context.bot_data.get("scheduler")
    if scheduler and session:
        scheduler.schedule_ask_close(session["id"], session["closes_at"])
    await reply_ephemeral(update, context, tr(lang, "setask_saved",
                                              id=ask["num"],
                                              day=day_long(lang, ask["weekday"]),
                                              time=ask["time"]),
                          delete_trigger=True)


async def close_ask_session(bot, session_id):
    """Close answers: strip buttons, keep the final tally in chat."""
    session = db.get_ask_session(session_id)
    if not session or session.get("state") == "closed":
        return
    db.set_ask_session_state(session_id, "closed")
    lang = db.get_chat_lang(session["chat_id"])
    await refresh_ask_message(bot, session_id, lang=lang)
    logger.info("ask closed session=%s chat=%s", session_id, session["chat_id"])


async def on_ask_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answer / retract via inline buttons. needs_reason opens a DM-style prompt."""
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "ask":
        await query.answer()
        return
    try:
        session_id, position = int(parts[1]), int(parts[2])
    except ValueError:
        await query.answer()
        return
    session = db.get_ask_session(session_id)
    chat = query.message.chat if query.message else update.effective_chat
    user = query.from_user
    if not session or not chat or not user:
        await query.answer()
        return
    lang = db.get_chat_lang(chat.id)
    if session.get("state") != "open":
        await query.answer(text=tr(lang, "ask_closed"), show_alert=True)
        return
    options = db.get_ask_options(session["ask_id"])
    option = next((o for o in options if o["position"] == position), None)
    if option is None:
        await query.answer()
        return
    current = db.get_ask_response(session_id, user.id)
    if current and current["option_id"] == position:
        db.delete_ask_response(session_id, user.id)
        await refresh_ask_message(context.bot, session_id, lang=lang)
        await query.answer(text=tr(lang, "ask_retracted"))
        return
    if option["needs_reason"]:
        await query.answer(text=tr(lang, "ask_reason_needed"))
        await start_reason_prompt(update, context, session_id, position)
        return
    db.save_ask_response(session_id, user.id, position, None)
    from handlers.all_handler import remember_user
    remember_user(chat.id, user)
    await refresh_ask_message(context.bot, session_id, lang=lang)
    await query.answer()


async def start_reason_prompt(update, context, session_id, option_id):
    """Selective ForceReply asking only this user for a reason (3-min TTL)."""
    query = update.callback_query
    chat = query.message.chat
    user = query.from_user
    lang = db.get_chat_lang(chat.id)
    from handlers.param_prompt import set_pending
    name = html.escape(user.first_name or user.username or str(user.id))
    if user.username:
        text = f"@{user.username}\n{tr(lang, 'ask_reason_prompt', name=name)}"
        parse_mode = None
    else:
        text = f"{user.mention_html()}\n{tr(lang, 'ask_reason_prompt', name=name)}"
        parse_mode = "HTML"
    from telegram import ForceReply
    msg = await query.message.reply_text(
        text, parse_mode=parse_mode,
        reply_markup=ForceReply(selective=True, input_field_placeholder="..."),
    )
    payload = json.dumps({"session_id": session_id, "option_id": option_id})
    set_pending(chat.id, user.id, "ask_reason", msg.message_id, payload=payload)
    scheduler = context.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.schedule_reason_expiry(chat.id, user.id, msg.message_id)


async def apply_ask_reason(update, context) -> bool:
    """Save the reason reply: option + reason, refresh, delete prompt + reply."""
    from handlers.param_prompt import clear_pending, delete_prompt_best_effort, get_pending
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    lang = db.get_chat_lang(chat.id)
    pending = get_pending(chat.id, user.id)
    if not pending or pending.get("command") != "ask_reason":
        return False
    try:
        data = json.loads(pending.get("payload") or "{}")
        session_id, option_id = int(data["session_id"]), int(data["option_id"])
    except (TypeError, ValueError, KeyError):
        clear_pending(chat.id, user.id)
        return False
    session = db.get_ask_session(session_id)
    if not session or session.get("state") != "open":
        clear_pending(chat.id, user.id)
        await delete_prompt_best_effort(context.bot, chat.id, pending["prompt_message_id"])
        await reply_ephemeral(update, context, tr(lang, "ask_closed"))
        return True
    reason = (message.text or "").strip()[:REASON_MAX_LEN]
    if not reason:
        await reply_ephemeral(update, context, tr(lang, "ask_reason_needed"))
        return False
    db.save_ask_response(session_id, user.id, option_id, reason)
    from handlers.all_handler import remember_user
    remember_user(chat.id, user)
    await refresh_ask_message(context.bot, session_id, lang=lang)
    clear_pending(chat.id, user.id)
    await delete_prompt_best_effort(context.bot, chat.id, pending["prompt_message_id"])
    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
    except Exception as exc:
        logger.debug("ask reason: delete user reply failed: %s", exc)
    scheduler = context.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.cancel_reason_expiry(chat.id, user.id)
    return True


async def expire_reason_prompt(bot, chat_id, user_id, prompt_message_id):
    """3-minute TTL: delete the prompt, keep any previous answer unchanged."""
    from handlers.param_prompt import clear_pending, delete_prompt_best_effort, get_pending
    pending = get_pending(chat_id, user_id)
    if not pending or pending.get("command") != "ask_reason":
        return
    try:
        if int(pending["prompt_message_id"]) != int(prompt_message_id):
            return
    except (TypeError, ValueError):
        return
    try:
        created = float(pending.get("created_at") or 0)
    except (TypeError, ValueError):
        created = 0
    import time as _time
    if _time.time() - created < ASK_REASON_TTL_SEC - 5:
        return
    clear_pending(chat_id, user_id)
    await delete_prompt_best_effort(bot, chat_id, prompt_message_id)
