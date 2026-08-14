## 1. Project Setup

- [x] 1.1 Create project skeleton: `bot.py`, `db.py`, `scheduler.py`, `handlers/` package with `queue_handlers.py` and `config_handlers.py`
- [x] 1.2 Add `requirements.txt` with `python-telegram-bot==21.*`, `APScheduler==3.*`, `python-dotenv`
- [x] 1.3 Add `.env.example` with `BOT_TOKEN` and load it via `python-dotenv` in `bot.py`
- [x] 1.4 Register `/start` and `/help` handlers with a friendly intro and bot capability summary

## 2. Database Layer

- [x] 2.1 Implement `db.py` with SQLite schema: `chats`, `lessons`, `queue_entries`, `active_messages` (per design D1)
- [x] 2.2 Implement chat/lesson helpers: `add_chat`, `add_lesson`, `get_lessons(chat_id)`, `remove_lesson`, `update_lesson_window`
- [x] 2.3 Implement queue helpers: `add_queue_entry`, `remove_queue_entry`, `get_queue(chat_id, lesson_id, session_date)`, `clear_queue`
- [x] 2.4 Implement active-message helpers: `save_active_message`, `get_active_message`, `delete_active_message`
- [x] 2.5 Write a standalone smoke test that exercises all DB helpers without Telegram

## 3. Lesson Configuration (Admin)

- [x] 3.1 Implement admin check helper using `get_chat_member` (status `administrator`/`creator`); reject non-admins for all config commands
- [x] 3.2 Implement `/setlesson <day> <HH:MM>` — insert or update a lesson for the chat, register scheduler jobs immediately
- [x] 3.3 Implement `/setopenbefore <minutes>` and `/setlifetime <minutes>` updates for the last-edited lesson
- [x] 3.4 Implement `/mylessons` (list configured lessons+settings) and `/removelesson <day>` (delete lesson + its jobs)
- [x] 3.5 If bot lacks Pin/Delete admin rights when a config command runs, reply with setup instructions instead of failing silently

## 4. Scheduler

- [x] 4.1 Implement `scheduler.py` with `AsyncIOScheduler` and job-id scheme `open_/close_/delete_{chat_id}_{lesson_id}` (design D2)
- [x] 4.2 Implement `open_queue(chat_id, lesson_id)` — compute session_date from lesson day, post+silently pin "Queue is open!", save active message
- [x] 4.3 Implement `close_queue(chat_id, lesson_id)` — stop accepting joins, edit pinned message to closed (🔒)
- [x] 4.4 Implement `cleanup_queue(chat_id, lesson_id)` — unpin, delete message, clear entries, drop active-message row
- [x] 4.5 Implement job registration/re-registration from DB for all chats/lessons at bot startup, including cleanup of stale sessions whose cleanup time already passed (design D3)
- [x] 4.6 Add methods to add/update/remove a lesson's jobs on config change (no restart needed)

## 5. Queue Commands

- [x] 5.1 Implement `/queue` — join today's session with duplicate + not-open guards (spec: join queue)
- [x] 5.2 Implement `/leave` — remove user, shift others up; inform if not in queue
- [x] 5.3 Implement `/list` — show numbered current queue, or empty message
- [x] 5.4 Implement `/myposition` — private reply with the user's position
- [x] 5.5 Ensure all queue state is keyed on `chat_id` so chats never mix

## 6. Pinned Live-Edit Message

- [x] 6.1 Implement shared `format_list(entries)` producing numbered display of queue entries
- [x] 6.2 Implement shared `refresh_queue_message(bot, chat_id, lesson_id, session_date)` that live-edits the stored message (design D4)
- [x] 6.3 Wire `refresh_queue_message` into join/leave/close flows so a single message updates in place with no pin spam
- [x] 6.4 Ensure a session never posts a second pinned message (reuse existing active message)

## 7. Error Handling & Permissions Pass

- [x] 7.1 Wrap all Telegram API calls (`edit_message_text`, `pin_chat_message`, `unpin_chat_message`, `delete_message`) in try/except; on failure, clean up DB rows so refresh doesn't recurse forever (design D6 risk)
- [x] 7.2 Handle edge cases: duplicate `/queue`, `/leave` when not in queue, queue-command outside open window, non-admin on admin commands
- [x] 7.3 Prevent lesson time overlap conflicts when adding a new lesson (surface a clear message)

## 8. Testing

- [ ] 8.1 Test full cycle quickly: set a lesson 2–3 minutes in the future, confirm open → join → close → delete sequence
- [ ] 8.2 Test rapid-fire `/queue` from 2+ accounts to confirm no duplicate numbering
- [ ] 8.3 Test bot restart mid-cycle to confirm jobs and open sessions restore from DB
- [ ] 8.4 Test two concurrent chats to confirm full isolation

## 9. Deployment

- [x] 9.1 Document deployment on Railway/Render (or VPS+systemd), setting `BOT_TOKEN` and ensuring persistent SQLite storage

## 10. UX & Visual Polish

- [x] 10.1 Replace typing commands with inline Join/Leave buttons under the pinned message (CallbackQueryHandler + answer_callback_query)
- [x] 10.2 Full HTML formatting: bold numbers, live count, day/header baked into the pinned message, first-name only
- [x] 10.3 Live countdown: recurring 2-min interval job refreshes open messages with "Open for N more min"
- [x] 10.4 Status emojis: 🟢 Open / 🟡 Closing soon (<5 min) / 🔴 Closed, as a single line under the title
- [x] 10.5 Onboarding: /start + auto-welcome on group add with one "⚙️ Set up schedule" button
- [x] 10.6 Position confirmations as callback toasts (no new chat messages); errors as show_alert toasts
- [x] 10.7 /info rewritten with HTML hierarchy, emoji dividers, admin-only section shown only to admins
- [x] 10.8 Closed-state footer added: "🔒 Список закрыт в 23:00 · Урок начался"
- [x] 9.2 Write final `README.md` covering setup, admin commands, group rollout, and admin-rights requirements

- [x] 10.9 Action buttons under /info and /start: "Show queue", "Settings (admin)", "Set up schedule"
- [x] 10.10 Guided admin setup flow: tap day → reply HH:MM → confirm Save (new handlers/setup_flow.py)
- [x] 10.11 Admin Settings panel: tap-to-remove lessons, Add lesson, and window (open-before / lifetime) +/-5 stepper
- [x] 10.12 Time input stays typed (HH:MM) only for the open-ended step; every other action is a real InlineKeyboardButton
