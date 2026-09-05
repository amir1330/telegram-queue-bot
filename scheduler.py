"""APScheduler integration: auto open/close per lesson.

One lesson row maps to two cron jobs with predictable ids:
  open_{chat_id}_{lesson_id}    at lesson_time - open_before_min
  delete_{chat_id}_{lesson_id}  at lesson_time + lifetime_min  (closes join window)

The queue stays joinable from open until close. At lifetime end the list stays
in chat: buttons off, message unpinned. Sessions are keyed by stored
session_date (lesson calendar day), so windows that cross midnight still work.
"""

import asyncio
import logging
import time as time_mod
from datetime import datetime, date, time, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.error import RetryAfter

import db
from message_builder import build_queue_text, build_timer_text, queue_markup, timer_markup
from queue_message import refresh_queue_message
from queue_view import DAY_INDEX
from timezone import chat_now, chat_tz

logger = logging.getLogger(__name__)

_TIMER_LOCKS: dict[int, asyncio.Lock] = {}
_TIMER_LAST: dict[int, float] = {}


async def _timer_throttle(chat_id: int):
    lock = _TIMER_LOCKS.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _TIMER_LOCKS[chat_id] = lock
    async with lock:
        now = time_mod.monotonic()
        last = _TIMER_LAST.get(chat_id, 0)
        wait = 0.4 - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _TIMER_LAST[chat_id] = time_mod.monotonic()

OPEN_PREFIX, DELETE_PREFIX = "open", "delete"
TIMER_PREFIX = "timer"
TICK_PREFIX = "timertick"


def _parse_time(hhmm):
    h, m = hhmm.split(":")
    return int(h), int(m)


def _cron_for(lesson):
    """Return (open, delete) tuples of (day_of_week 0-6, hour, minute).

    Times that spill over midnight are shifted to the neighbouring weekday so
    CronTrigger fires them correctly.
    """
    h, m = _parse_time(lesson["lesson_time"])
    total = h * 60 + m
    dow = DAY_INDEX[lesson["day_of_week"]]
    open_before = lesson["open_before_min"]
    lifetime = lesson["lifetime_min"]

    delta_open = total - open_before
    if delta_open < 0:
        days_back = (-delta_open) // 1440 + 1
        open_min = delta_open + 1440 * days_back
    else:
        days_back = delta_open // 1440
        open_min = delta_open % 1440
    open_dow = (dow - days_back) % 7
    open_h, open_m = divmod(open_min, 60)
    open_t = (open_dow, open_h, open_m)

    delta_del = total + lifetime
    days_fwd = delta_del // 1440
    del_h, del_m = divmod(delta_del % 1440, 60)
    delete_t = ((dow + days_fwd) % 7, del_h, del_m)

    return open_t, delete_t


class QueueScheduler:
    def __init__(self, app):
        self.app = app
        self.scheduler = AsyncIOScheduler()

    @property
    def bot(self):
        return self.app.bot

    def start(self):
        self.scheduler.start()

    def shutdown(self):
        self.scheduler.shutdown(wait=False)

    # ------------------------------------------------------------ jobs

    def _triggers(self, lesson):
        open_t, delete_t = _cron_for(lesson)
        tz = chat_tz(lesson["chat_id"])
        open_trigger = CronTrigger(
            day_of_week=open_t[0], hour=open_t[1], minute=open_t[2], timezone=tz
        )
        delete_trigger = CronTrigger(
            day_of_week=delete_t[0], hour=delete_t[1], minute=delete_t[2], timezone=tz
        )
        h, m = _parse_time(lesson["lesson_time"])
        dow = DAY_INDEX[lesson["day_of_week"]]
        timer_trigger = CronTrigger(
            day_of_week=dow, hour=h, minute=m, timezone=tz
        )
        return open_trigger, delete_trigger, timer_trigger

    def schedule_lesson(self, lesson):
        """Add/update the jobs for a lesson (idempotent)."""
        chat_id, lesson_id = lesson["chat_id"], lesson["lesson_id"]
        open_trig, delete_trig, timer_trig = self._triggers(lesson)
        self.scheduler.add_job(
            self.open_queue, open_trig,
            args=[chat_id, lesson_id],
            id=f"{OPEN_PREFIX}_{chat_id}_{lesson_id}",
            replace_existing=True, misfire_grace_time=3600,
        )
        self.scheduler.add_job(
            self.close_queue, delete_trig,
            args=[chat_id, lesson_id],
            id=f"{DELETE_PREFIX}_{chat_id}_{lesson_id}",
            replace_existing=True, misfire_grace_time=3600,
        )
        self.scheduler.add_job(
            self.open_timer, timer_trig,
            args=[chat_id, lesson_id],
            id=f"{TIMER_PREFIX}_{chat_id}_{lesson_id}",
            replace_existing=True, misfire_grace_time=3600,
        )

    def unschedule_lesson(self, chat_id, lesson_id):
        for prefix in (OPEN_PREFIX, DELETE_PREFIX, TIMER_PREFIX):
            try:
                self.scheduler.remove_job(f"{prefix}_{chat_id}_{lesson_id}")
            except Exception:
                pass
        # also remove any ticking job
        try:
            self.scheduler.remove_job(f"{TICK_PREFIX}_{chat_id}_{lesson_id}")
        except Exception:
            pass

    # --------------------------------------------------- job callbacks

    async def open_queue(self, chat_id, lesson_id, session_date=None):
        lesson = db.get_lesson_by_id(lesson_id)
        if not lesson:
            return
        lang = db.get_chat_lang(chat_id)
        if session_date is None:
            # Job fires at open time: now + open_before ≈ lesson start date.
            session_date = (
                chat_now(chat_id) + timedelta(minutes=lesson["open_before_min"])
            ).date().isoformat()
        existing = db.get_active_message(chat_id, lesson_id, session_date)
        if existing and existing.get("status") == "open":
            return
        if existing and existing.get("status") == "closed":
            return
        text = build_queue_text(lesson, session_date, [], lang=lang)
        try:
            msg = await self.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=queue_markup(lang)
            )
        except Exception as exc:
            logger.warning("open_queue: send_message failed in %s: %s", chat_id, exc)
            return
        try:
            await self.bot.pin_chat_message(
                chat_id=chat_id, message_id=msg.message_id, disable_notification=True
            )
        except Exception as exc:
            logger.warning("open_queue: pin failed in %s: %s", chat_id, exc)
        db.save_active_message(chat_id, lesson_id, session_date, msg.message_id, "open")
        await refresh_queue_message(self.bot, chat_id, lesson_id, session_date, lang=lang)

    async def close_queue(self, chat_id, lesson_id, session_date=None):
        """End the join window: unpin, drop buttons, keep the final list in chat.

        Prefer the stored session_date. If omitted (cron fire), close any open
        row for this lesson — critical when the window crossed midnight.
        """
        lesson = db.get_lesson_by_id(lesson_id)
        if not lesson:
            return

        if session_date is None:
            opens = [
                r for r in db.get_active_messages(chat_id=chat_id, status="open")
                if r["lesson_id"] == lesson_id
            ]
            if not opens:
                return
            session_date = opens[0]["session_date"]

        row = db.get_active_message(chat_id, lesson_id, session_date)
        if not row:
            return
        if row.get("status") == "closed":
            return

        lang = db.get_chat_lang(chat_id)
        db.mark_active_closed(chat_id, lesson_id, session_date)

        try:
            await self.bot.unpin_chat_message(
                chat_id=chat_id, message_id=row["message_id"]
            )
        except Exception as exc:
            logger.warning("close_queue: unpin failed in %s: %s", chat_id, exc)

        await refresh_queue_message(self.bot, chat_id, lesson_id, session_date, lang=lang)

        # also stop timer tick and clean timer message (keep text, strip keyboard)
        try:
            self.scheduler.remove_job(f"{TICK_PREFIX}_{chat_id}_{lesson_id}")
        except Exception:
            pass
        timer_row = db.get_active_timer(chat_id, lesson_id, session_date)
        if timer_row:
            try:
                await self.bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=timer_row["message_id"], reply_markup=None
                )
            except Exception as exc:
                logger.debug("close_queue: strip timer markup failed: %s", exc)
            db.delete_active_timer(chat_id, lesson_id, session_date)

    # --------------------------------------------------- timer jobs

    def _tick_job_id(self, chat_id, lesson_id):
        return f"{TICK_PREFIX}_{chat_id}_{lesson_id}"

    def _start_tick(self, chat_id, lesson_id):
        try:
            self.scheduler.remove_job(self._tick_job_id(chat_id, lesson_id))
        except Exception:
            pass
        self.scheduler.add_job(
            self._tick, "interval", seconds=3,
            args=[chat_id, lesson_id],
            id=self._tick_job_id(chat_id, lesson_id),
            replace_existing=True, misfire_grace_time=30,
        )

    def _stop_tick(self, chat_id, lesson_id):
        try:
            self.scheduler.remove_job(self._tick_job_id(chat_id, lesson_id))
        except Exception:
            pass

    def _compute_remaining(self, timer_row):
        if not timer_row.get("running"):
            return timer_row["remaining_seconds"]
        started_at = timer_row.get("started_at")
        if not started_at:
            return timer_row["remaining_seconds"]
        try:
            start_dt = datetime.fromisoformat(started_at)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except Exception:
            return timer_row["remaining_seconds"]
        now = datetime.now(timezone.utc)
        elapsed = int((now - start_dt).total_seconds())
        remaining = timer_row["remaining_seconds"] - elapsed
        return max(0, remaining)

    async def _refresh_timer_message(self, chat_id, lesson_id, session_date):
        lesson = db.get_lesson_by_id(lesson_id)
        if not lesson:
            return
        timer_row = db.get_active_timer(chat_id, lesson_id, session_date)
        if not timer_row:
            return
        lang = db.get_chat_lang(chat_id)
        entries = db.get_queue(chat_id, lesson_id, session_date)
        remaining = self._compute_remaining(timer_row)
        running = bool(timer_row.get("running")) and remaining > 0
        text = build_timer_text(lesson, entries, timer_row.get("current_index", 0), remaining, running, lang=lang)
        markup = timer_markup(lang, running)  # always visible, so Next/Prev possible after time is up
        await _timer_throttle(chat_id)
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=timer_row["message_id"],
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except RetryAfter as exc:
            logger.warning("_refresh_timer: Flood RetryAfter %ss chat=%s lesson=%s session=%s", getattr(exc, "retry_after", "?"), chat_id, lesson_id, session_date)
        except Exception as exc:
            # keep row, log - similar to queue_message handling
            logger.warning("_refresh_timer: edit failed chat=%s lesson=%s session=%s: %s", chat_id, lesson_id, session_date, exc)
            # if message not found, clean up
            if "message to edit not found" in str(exc).lower() or "message not found" in str(exc).lower() or "chat not found" in str(exc).lower():
                db.delete_active_timer(chat_id, lesson_id, session_date)
                self._stop_tick(chat_id, lesson_id)

    async def open_timer(self, chat_id, lesson_id, session_date=None):
        lesson = db.get_lesson_by_id(lesson_id)
        if not lesson:
            return
        lang = db.get_chat_lang(chat_id)
        if session_date is None:
            # timer fires at lesson_time exact -> session_date is today in chat tz
            session_date = chat_now(chat_id).date().isoformat()
            # adjust if lesson day does not match today (e.g. triggered via cron on correct dow)
            # but chat_now already on correct dow, so just use it
        existing = db.get_active_timer(chat_id, lesson_id, session_date)
        if existing:
            return
        entries = db.get_queue(chat_id, lesson_id, session_date)
        if not entries:
            # nothing to time - don't send empty timer
            return
        timer_sec = lesson.get("answer_timer_sec") or 420
        text = build_timer_text(lesson, entries, 0, timer_sec, False, lang=lang)
        try:
            msg = await self.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=timer_markup(lang, False)
            )
        except Exception as exc:
            logger.warning("open_timer: send failed chat=%s: %s", chat_id, exc)
            return
        db.save_active_timer(chat_id, lesson_id, session_date, msg.message_id, current_index=0, remaining_seconds=timer_sec, running=0, started_at=None)

    async def _tick(self, chat_id, lesson_id):
        # find the open timer for this lesson (there should be at most one running)
        timers = db.get_active_timers(chat_id=chat_id, lesson_id=lesson_id)
        # find running one
        target = None
        for t in timers:
            if t.get("running"):
                target = t
                break
        if not target:
            self._stop_tick(chat_id, lesson_id)
            return
        remaining = self._compute_remaining(target)
        if remaining <= 0:
            db.update_active_timer(target["chat_id"], target["lesson_id"], target["session_date"], remaining_seconds=0, running=0, started_at=None)
            self._stop_tick(chat_id, lesson_id)
            await self._refresh_timer_message(target["chat_id"], target["lesson_id"], target["session_date"])
            return
        await self._refresh_timer_message(target["chat_id"], target["lesson_id"], target["session_date"])

    async def discard_queue_message(self, chat_id, lesson_id, session_date, message_id, lang="en"):
        """Unpin and strip buttons from a queue message (e.g. after /delete)."""
        try:
            await self.bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            logger.warning("discard_queue_message: unpin failed in %s: %s", chat_id, exc)
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
        except Exception as exc:
            logger.debug("discard_queue_message: edit markup failed: %s", exc)

    # ------------------------------------------------------------ restore

    def _occurrence(self, lesson, session_date):
        h, m = _parse_time(lesson["lesson_time"])
        tz = chat_tz(lesson["chat_id"])
        if tz is None:
            tz = datetime.now().astimezone().tzinfo
        if isinstance(session_date, str):
            session_date = date.fromisoformat(session_date)
        lesson_start = datetime.combine(session_date, time(h, m), tzinfo=tz)
        return lesson_start, lesson_start + timedelta(minutes=lesson["lifetime_min"])

    async def refresh_lesson(self, lesson):
        """Re-register cron jobs and open the queue if we are already in the window."""
        self.schedule_lesson(lesson)
        await self.maybe_catchup_open(lesson)

    async def catchup_chat(self, chat_id):
        """Open any lesson windows already in progress for this chat."""
        for lesson in db.get_lessons(chat_id):
            await self.maybe_catchup_open(lesson)

    async def maybe_catchup_open(self, lesson):
        """If we are inside an open window with no active message, open now."""
        chat_id = lesson["chat_id"]
        now = chat_now(chat_id)
        dow = DAY_INDEX[lesson["day_of_week"]]
        for delta in (-1, 0, 1):
            d = now.date() + timedelta(days=delta)
            if d.weekday() != dow:
                continue
            lesson_start, close_dt = self._occurrence(lesson, d)
            open_dt = lesson_start - timedelta(minutes=lesson["open_before_min"])
            if open_dt <= now < close_dt:
                session_date = d.isoformat()
                existing = db.get_active_message(chat_id, lesson["lesson_id"], session_date)
                if existing:
                    return
                logger.info(
                    "catch-up open chat=%s lesson=%s session=%s",
                    chat_id, lesson["lesson_id"], session_date,
                )
                await self.open_queue(chat_id, lesson["lesson_id"], session_date=session_date)
                return

    async def restore(self):
        """Re-register jobs, close stale opens, catch up missed opens."""
        for lesson in db.get_all_lessons():
            self.schedule_lesson(lesson)

        for row in db.get_active_messages():
            if row.get("status") == "closed":
                continue
            lesson = db.get_lesson_by_id(row["lesson_id"])
            if lesson is None:
                continue
            try:
                session_date = date.fromisoformat(row["session_date"])
            except ValueError:
                continue
            _, cleanup_dt = self._occurrence(lesson, session_date)
            if chat_now(row["chat_id"]) >= cleanup_dt:
                await self.close_queue(
                    row["chat_id"], row["lesson_id"], session_date=row["session_date"]
                )

        # active timers: pause any running ones (simplification, don't restore tick accurately)
        for row in db.get_active_timers():
            if row.get("running"):
                # compute remaining up to now and pause
                remaining = self._compute_remaining(row)
                db.update_active_timer(row["chat_id"], row["lesson_id"], row["session_date"], remaining_seconds=remaining, running=0, started_at=None)
                try:
                    await self._refresh_timer_message(row["chat_id"], row["lesson_id"], row["session_date"])
                except Exception as exc:
                    logger.warning("restore: refresh timer failed %s", exc)

        for lesson in db.get_all_lessons():
            await self.maybe_catchup_open(lesson)
