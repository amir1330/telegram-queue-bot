## Context

Greenfield bot for this repo — there is no existing code. The implementation plan (`telegram_queue_bot_implementation_plan.md`) specifies the stack: Python 3.11+, `python-telegram-bot` v21 (async), APScheduler, SQLite. The bot is multi-chat: any group adds it, and its own admins self-configure lessons. All queue state is scoped per chat, and a single pinned message per session live-edits as the queue changes.

## Goals / Non-Goals

**Goals:**
- Persist chats, lessons, queue entries, and active messages in SQLite so scheduler state and open sessions survive restarts.
- Provide admin-only lesson config (`/setlesson`, `/setopenbefore`, `/setlifetime`, `/mylessons`, `/removelesson`) that takes effect immediately via scheduler re-registration.
- Automate the open → close → cleanup cycle per lesson using APScheduler jobs.
- Keep one silently-pinned, live-edited queue message per chat-lesson-session.
- Wrap all Telegram API calls defensively so manual deletion of a pinned message never crashes a job.

**Non-Goals:**
- No webhook mode (polling only).
- No web UI, no multi-language support, no per-user history beyond queue entries.
- No admin settings for timezone (bot server TZ assumed to match the groups' TZ).
- No feature to count lifetime from queue *open* time — lifetime counts from lesson start (per the plan's default).

## Decisions

**D1 — SQLite with thin wrapper functions (`db.py`).**
Tables: `chats`, `lessons`, `queue_entries`, `active_messages`. All access goes through small functions (`add_chat`, `add_lesson`, `get_lessons(chat_id)`, `remove_lesson`, `add_queue_entry`, `remove_queue_entry`, `get_queue(chat_id, lesson_id, session_date)`, `clear_queue`, `save_active_message`, `get_active_message`, `delete_active_message`). Rationale: keep the data layer testable independent of Telegram. Alternative: SQLAlchemy — rejected as overkill for 4 tables.

**D2 — APScheduler `AsyncIOScheduler` with predictable job IDs.**
Per lesson row, three jobs: `open_{chat_id}_{lesson_id}`, `close_{chat_id}_{lesson_id}`, `delete_{chat_id}_{lesson_id}`, driven by `CronTrigger(day_of_week, hour, minute)`. Open time computed as `lesson_time − open_before_min`; close at `lesson_time`; cleanup at `lesson_time + lifetime_min`. Rationale: predictable IDs make remove/replace idempotent. Alternative: rolling next-run computations in a single loop — rejected for complexity and drift.

**D3 — Scheduler is the single place that posts the pinned message.**
`open_queue(chat_id, lesson_id)` creates `session_date` (lesson day, i.e. the date the lesson occurs — so a lesson at 00:10 opened the previous day still maps to the lesson date), posts "Queue is open!", pins silently, records the message id. `close_queue()` edits the message to a closed state. `cleanup_queue()` unpins, deletes the message, clears entries, drops the active-message row. Rationale: one writer to `active_messages` avoids race conditions between scheduler and handlers.

**D4 — Shared `refresh_queue_message()` live-edits the pinned message.**
After every join/leave, handlers call a single helper that re-reads the queue and `edit_message_text`s the stored message id. Rationale: no pin spam, no duplication between handlers and scheduler.

**D5 — Admin checks via `get_chat_member`.**
Each config handler verifies the sender's status is `administrator` or `creator` before acting. The bot itself must have Pin + Delete admin rights; if a config command is run while the bot lacks rights, reply with setup instructions instead of failing silently.

**D6 — Session date is the lesson date, not "now".**
Queue entries and active messages are keyed by `session_date` so a lesson on a later weekday never mixes with a previous week's session. Open job computes the next occurrence of the lesson's weekday and stores that date.

## Risks / Trade-offs

- **Message manually deleted by a user** → all Telegram calls wrapped in try/except; on failure, clean up DB rows so the next refresh doesn't error forever.
- **Bot restarts mid-cycle** → jobs re-register from DB on startup; a session whose cleanup time already passed is cleaned up on startup.
- **Server timezone mismatch** → CronTrigger uses server-local time; documented requirement that host TZ matches group TZ (per-group TZ is a non-goal).
- **Race on rapid simultaneous `/queue`** → single-process bot serializes updates through `Application`; DB ops are quick. Acceptable for expected load; a `UNIQUE` guard on user+session is a possible hardening follow-up.
- **Pin/delete permissions revoked** → every pin/edit/delete failure is caught and surfaced as a friendly message so the scheduler keeps running.

## Migration Plan

Greenfield — no migration. Deploy by adding the bot to groups, promoting to admin (Pin + Delete), setting `BOT_TOKEN`, and configuring lessons. SQLite file lives on persistent storage on the host.

## Open Questions

- None blocking. The plan's noted open item (lifetime counting from lesson start vs. open time) is resolved to "from lesson start" per the default; trivially changeable in the close/delete job timing if a group prefers otherwise.