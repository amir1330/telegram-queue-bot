# Telegram Lesson-Queue Bot — Implementation Plan

**Stack:** Python 3.11+, `python-telegram-bot` v20+ (async), `APScheduler`, `SQLite`
**Scope:** multi-chat bot — any group can add it and self-configure its own lesson schedule.

---

## Phase 0 — Project setup (30–45 min)

1. Create bot via **@BotFather** in Telegram → `/newbot` → save the bot token.
2. Set bot privacy mode to allow reading commands only (default is fine — commands like `/queue` always reach the bot regardless of privacy mode).
3. Create project folder:
   ```
   queue-bot/
     bot.py
     db.py
     scheduler.py
     handlers/
       queue_handlers.py
       config_handlers.py
     queue_bot.db      (created automatically)
     requirements.txt
     .env
   ```
4. `requirements.txt`:
   ```
   python-telegram-bot==21.*
   APScheduler==3.*
   python-dotenv
   ```
5. `.env`:
   ```
   BOT_TOKEN=your_token_here
   ```
6. `pip install -r requirements.txt`

**Output of this phase:** empty runnable bot that responds to `/start`.

---

## Phase 1 — Database schema (30 min)

`db.py` — SQLite, 3 tables:

```sql
CREATE TABLE chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT
);

CREATE TABLE lessons (
    lesson_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    day_of_week TEXT,       -- 'mon','tue',...
    lesson_time TEXT,       -- 'HH:MM'
    open_before_min INTEGER DEFAULT 30,
    lifetime_min INTEGER DEFAULT 60,
    FOREIGN KEY(chat_id) REFERENCES chats(chat_id)
);

CREATE TABLE queue_entries (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    lesson_id INTEGER,
    user_id INTEGER,
    display_name TEXT,
    joined_at TEXT,
    session_date TEXT       -- so today's queue doesn't mix with next week's
);

CREATE TABLE active_messages (
    chat_id INTEGER,
    lesson_id INTEGER,
    session_date TEXT,
    message_id INTEGER,
    PRIMARY KEY (chat_id, lesson_id, session_date)
);
```

Write thin wrapper functions: `add_chat`, `add_lesson`, `get_lessons(chat_id)`, `remove_lesson`, `add_queue_entry`, `remove_queue_entry`, `get_queue(chat_id, lesson_id, session_date)`, `clear_queue`, `save_active_message`, `get_active_message`, `delete_active_message`.

**Output:** working data layer, testable independently of Telegram.

---

## Phase 2 — Core bot skeleton (30 min)

`bot.py`:
- Load token from `.env`
- Build `Application`
- Register `/start`, `/help`
- On startup: for every chat in DB, re-register that chat's scheduled jobs (covers bot restarts/redeploys)
- `application.run_polling()`

**Output:** bot connects, responds to `/start` in any chat it's added to.

---

## Phase 3 — Admin config commands (1–1.5 hr)

In `handlers/config_handlers.py`. Each checks sender is chat admin via `context.bot.get_chat_member(chat_id, user_id)` → status in `('administrator','creator')`.

| Command | Effect |
|---|---|
| `/setlesson Monday 23:00` | insert/update a lesson row for this chat |
| `/setopenbefore 30` | update `open_before_min` for last-edited lesson |
| `/setlifetime 60` | update `lifetime_min` |
| `/mylessons` | list this chat's configured lessons |
| `/removelesson Monday` | delete that lesson row + its scheduler jobs |

Every successful config change immediately calls into Phase 5's scheduler functions to add/update/remove the corresponding jobs — no restart needed.

**Output:** any group admin can fully configure their own schedule from inside their chat.

---

## Phase 4 — Queue commands (1 hr)

In `handlers/queue_handlers.py`. All scoped by `chat_id` from `update.effective_chat.id` — no cross-chat leakage.

| Command | Effect |
|---|---|
| `/queue` | adds user to today's open queue for this chat (reject if already in, reject if queue not open) |
| `/leave` | removes user, shifts others up |
| `/list` | shows current formatted list |
| `/myposition` | replies privately with their number |

After every join/leave, call a shared `refresh_queue_message()` function (Phase 6) instead of posting a new message.

**Output:** queue logic fully working when manually opened — testable before scheduler is even wired in.

---

## Phase 5 — Scheduler (1.5–2 hr)

`scheduler.py`, using `AsyncIOScheduler` from APScheduler.

For each lesson row, register 3 jobs with predictable IDs (`open_{chat_id}_{lesson_id}`, `close_...`, `delete_...`):

1. **Open job** — `CronTrigger(day_of_week=X, hour=Y, minute=Z)` computed as `lesson_time − open_before_min` → calls `open_queue(chat_id, lesson_id)`
2. **Close job** — at exact `lesson_time` → calls `close_queue(chat_id, lesson_id)` (stops accepting `/queue`, edits message to show 🔒)
3. **Delete job** — at `lesson_time + lifetime_min` (recommended default — see note below) → calls `cleanup_queue(chat_id, lesson_id)` (delete message, unpin, clear queue rows)

Functions:
- `open_queue()`: create `session_date` = today's date, post "Queue is open!" message, pin silently (`disable_notification=True`), save to `active_messages`
- `close_queue()`: edit message text to mark closed
- `cleanup_queue()`: `bot.unpin_chat_message()`, `bot.delete_message()`, delete row from `active_messages`, delete that session's `queue_entries`

**Design note to confirm with your group:** lifetime counts from lesson **start** (list stays visible through the lesson, vanishes after) — this was the earlier default. Flip to counting from **open time** if you'd rather it disappear mid-lesson.

**Output:** fully automated open/close/delete cycle, no manual triggering needed.

---

## Phase 6 — Pin + live-edit logic (30–45 min)

Shared helper used by both queue commands and scheduler:

```python
async def refresh_queue_message(bot, chat_id, lesson_id, session_date):
    entries = get_queue(chat_id, lesson_id, session_date)
    text = format_list(entries)   # "1. Amir\n2. Damir..."
    msg_id = get_active_message(chat_id, lesson_id, session_date)
    await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
```

This is what keeps one pinned message silently updating instead of spamming new pins.

**Output:** clean, non-spammy live queue in the chat.

---

## Phase 7 — Permission & error handling pass (30–45 min)

- Bot must be promoted to **admin with "Pin messages" + "Delete messages"** rights in every group that uses it — add a friendly check: if `/setlesson` is run but bot lacks admin rights, reply with instructions instead of failing silently.
- Handle: queue command used before opening time, duplicate `/queue`, `/leave` when not in queue, admin-only command used by non-admin, lesson time overlaps.
- Wrap all Telegram API calls (`edit_message_text`, `pin_chat_message`, etc.) in try/except — messages can be manually deleted by users, which would otherwise crash a scheduled job.

**Output:** bot survives real-world messiness without crashing.

---

## Phase 8 — Testing (1–1.5 hr)

1. Add bot to a private test group, promote to admin.
2. Run `/setlesson` with a time 2–3 minutes in the future to test the full open → queue → close → delete cycle quickly without waiting days.
3. Test with 2+ accounts joining "simultaneously" (rapid-fire `/queue`) — confirm no duplicate numbering.
4. Test bot restart mid-cycle — confirm scheduled jobs reload correctly from DB on startup.
5. Test in a second group concurrently — confirm total isolation between chats.

**Output:** confidence before rolling out to your real class groups.

---

## Phase 9 — Deployment (30–60 min)

- Host: **Railway** or **Render** (free/cheap tier, keeps a long-running process alive) — simplest for polling mode, no HTTPS/webhook setup needed.
- Alternative: small VPS (e.g. Hetzner) + `systemd` service or `tmux`/`screen` if you want more control.
- Set `BOT_TOKEN` as an environment variable on the host (not committed to git).
- Make sure the SQLite file is on **persistent storage** (some free hosts wipe the filesystem on redeploy — check this, or switch to a small managed Postgres if it's an issue).

**Output:** bot running 24/7, independent of your own machine being on.

---

## Phase 10 — Rollout (ongoing)

1. Add bot to your groups, promote to admin (Pin + Delete rights).
2. Each group's admin runs `/setlesson`, `/setopenbefore`, `/setlifetime` once.
3. Share `/help` output with students so they know `/queue`, `/leave`, `/list`.
4. Watch the first real cycle live in case a timezone or permission issue shows up.

---

## Total rough estimate
**~7–9 hours** of focused work for a working, multi-chat, self-configuring bot — spread over Phases 0–9. Phase 10 is just rollout, not build time.

## Suggested build order if done incrementally
Phase 0 → 1 → 2 → 4 (test queue logic manually first, without scheduler) → 3 → 5 → 6 → 7 → 8 → 9
