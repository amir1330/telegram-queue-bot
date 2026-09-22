"""APScheduler integration: auto open/close per lesson.

One lesson row maps to two cron jobs with predictable ids:
  open_{chat_id}_{lesson_id}    at lesson_time - open_before_min
  delete_{chat_id}_{lesson_id}  at lesson_time + lifetime_min  (closes join window)

Timer message is sent 10s after the queue message (separate message under queue).
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
MEET_CLOSE_PREFIX = "meet_close"
ASK_POST_PREFIX = "ask_post"
ASK_CLOSE_PREFIX = "ask_close"
REASON_EXPIRE_PREFIX = "ask_reason_expire"


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
        return open_trigger, delete_trigger

    def schedule_lesson(self, lesson):
        """Add/update the jobs for a lesson (idempotent)."""
        chat_id, lesson_id = lesson["chat_id"], lesson["lesson_id"]
        open_trig, delete_trig = self._triggers(lesson)
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
        # remove legacy timer cron if exists (now timer is 10s after queue)
        try:
            self.scheduler.remove_job(f"{TIMER_PREFIX}_{chat_id}_{lesson_id}")
        except Exception:
            pass

    def unschedule_lesson(self, chat_id, lesson_id):
        for prefix in (OPEN_PREFIX, DELETE_PREFIX, TIMER_PREFIX):
            try:
                self.scheduler.remove_job(f"{prefix}_{chat_id}_{lesson_id}")
            except Exception:
                pass
        # also remove any pending delayed timer jobs for this lesson
        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith(f"timer_delay_{chat_id}_{lesson_id}_"):
                try:
                    self.scheduler.remove_job(job.id)
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
        # schedule timer 10s after queue (separate message under queue)
        try:
            run_date = datetime.now(timezone.utc) + timedelta(seconds=10)
            self.scheduler.add_job(
                self.open_timer,
                "date",
                run_date=run_date,
                args=[chat_id, lesson_id, session_date],
                id=f"timer_delay_{chat_id}_{lesson_id}_{session_date}",
                replace_existing=True,
                misfire_grace_time=3600,
            )
        except Exception as exc:
            logger.warning("open_queue: schedule timer_delay failed %s", exc)

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

        # also stop timer tick, cancel pending timer_delay and clean timer message
        try:
            self.scheduler.remove_job(f"{TICK_PREFIX}_{chat_id}_{lesson_id}")
        except Exception:
            pass
        try:
            self.scheduler.remove_job(f"timer_delay_{chat_id}_{lesson_id}_{session_date}")
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

    async def ensure_timer(self, chat_id, lesson_id, session_date):
        """Create the timer message if an open session has people in the queue
        but no timer yet. Used when the first member joins an empty queue, since
        the one-shot timer_delay attempt at +10s silently skipped an empty queue.
        """
        existing = db.get_active_timer(chat_id, lesson_id, session_date)
        if existing:
            return
        entries = db.get_queue(chat_id, lesson_id, session_date)
        if not entries:
            return
        await self.open_timer(chat_id, lesson_id, session_date=session_date)

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

    # --------------------------------------------------- meet jobs (Phase 1)

    def schedule_meet_close(self, session_id, deadline_epoch):
        """Date job that closes the meet session at join_deadline."""
        run_date = datetime.fromtimestamp(deadline_epoch, tz=timezone.utc)
        self.scheduler.add_job(
            self.close_meet_session_job, "date", run_date=run_date,
            args=[session_id],
            id=f"{MEET_CLOSE_PREFIX}_{session_id}",
            replace_existing=True, misfire_grace_time=3600,
        )

    async def close_meet_session_job(self, session_id):
        from handlers.meet_handler import on_meet_close_job
        await on_meet_close_job(self.bot, session_id)

    # --------------------------------------------------- ask jobs

    def schedule_ask(self, ask):
        """Add/update the weekly cron post job for an ask (idempotent)."""
        try:
            h, m = _parse_time(ask["time"])
            dow = DAY_INDEX[ask["weekday"]]
        except (KeyError, ValueError, TypeError):
            logger.warning("schedule_ask: bad weekday/time ask=%s", ask.get("id"))
            return
        trigger = CronTrigger(
            day_of_week=dow, hour=h, minute=m, timezone=chat_tz(ask["chat_id"])
        )
        self.scheduler.add_job(
            self.post_ask_job, trigger,
            args=[ask["id"]],
            id=f"{ASK_POST_PREFIX}_{ask['chat_id']}_{ask['id']}",
            replace_existing=True, misfire_grace_time=300,
        )

    def unschedule_ask(self, chat_id, ask_id):
        try:
            self.scheduler.remove_job(f"{ASK_POST_PREFIX}_{chat_id}_{ask_id}")
        except Exception:
            pass

    def schedule_ask_close(self, session_id, closes_at_epoch):
        run_date = datetime.fromtimestamp(closes_at_epoch, tz=timezone.utc)
        self.scheduler.add_job(
            self.close_ask_job, "date", run_date=run_date,
            args=[session_id],
            id=f"{ASK_CLOSE_PREFIX}_{session_id}",
            replace_existing=True, misfire_grace_time=3600,
        )

    def schedule_reason_expiry(self, chat_id, user_id, prompt_message_id):
        from handlers.ask_handlers import ASK_REASON_TTL_SEC
        run_date = datetime.now(timezone.utc) + timedelta(seconds=ASK_REASON_TTL_SEC)
        self.scheduler.add_job(
            self.expire_reason_job, "date", run_date=run_date,
            args=[chat_id, user_id, prompt_message_id],
            id=f"{REASON_EXPIRE_PREFIX}_{chat_id}_{user_id}",
            replace_existing=True, misfire_grace_time=60,
        )

    def cancel_reason_expiry(self, chat_id, user_id):
        try:
            self.scheduler.remove_job(f"{REASON_EXPIRE_PREFIX}_{chat_id}_{user_id}")
        except Exception:
            pass

    async def post_ask_job(self, ask_id):
        from handlers.ask_handlers import post_ask_session
        session = await post_ask_session(self.bot, ask_id)
        if session:
            self.schedule_ask_close(session["id"], session["closes_at"])

    async def close_ask_job(self, session_id):
        from handlers.ask_handlers import close_ask_session
        await close_ask_session(self.bot, session_id)

    async def expire_reason_job(self, chat_id, user_id, prompt_message_id):
        from handlers.ask_handlers import expire_reason_prompt
        await expire_reason_prompt(self.bot, chat_id, user_id, prompt_message_id)

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

        # ensure timer is scheduled 10s after queue for open queues without timer
        for row in db.get_active_messages(chat_id=None, status="open"):
            if not db.get_active_timer(row["chat_id"], row["lesson_id"], row["session_date"]):
                # check if there are entries to time; if empty, open_timer will noop
                try:
                    run_date = datetime.now(timezone.utc) + timedelta(seconds=10)
                    self.scheduler.add_job(
                        self.open_timer,
                        "date",
                        run_date=run_date,
                        args=[row["chat_id"], row["lesson_id"], row["session_date"]],
                        id=f"timer_delay_{row['chat_id']}_{row['lesson_id']}_{row['session_date']}",
                        replace_existing=True,
                        misfire_grace_time=3600,
                    )
                except Exception as exc:
                    logger.warning("restore: schedule timer_delay failed %s", exc)

        for lesson in db.get_all_lessons():
            await self.maybe_catchup_open(lesson)

        # --- meet sessions: sweep expired, re-arm the rest (restart-safe) ---
        import time as _time
        from handlers.meet_handler import close_meet_session as _close_meet
        for session in db.get_open_meet_sessions():
            try:
                if _time.time() >= float(session["join_deadline"]):
                    await _close_meet(self.bot, session["id"], reason="restore-sweep")
                else:
                    self.schedule_meet_close(session["id"], float(session["join_deadline"]))
            except Exception as exc:
                logger.warning("restore: meet session %s failed: %s", session.get("id"), exc)

        # --- asks: re-register crons, sweep expired answer windows ---
        from handlers.ask_handlers import close_ask_session as _close_ask
        for ask in db.get_all_asks():
            try:
                self.schedule_ask(ask)
            except Exception as exc:
                logger.warning("restore: schedule ask %s failed: %s", ask.get("id"), exc)
        for session in db.get_open_ask_sessions():
            try:
                if _time.time() >= float(session.get("closes_at") or 0):
                    await _close_ask(self.bot, session["id"])
                else:
                    self.schedule_ask_close(session["id"], float(session["closes_at"]))
            except Exception as exc:
                logger.warning("restore: ask session %s failed: %s", session.get("id"), exc)
