## Why

Classes need a fair, low-friction way to manage lesson participation. Manually tracking who arrives first gets chaotic in busy group chats. A Telegram bot that maintains a live, pinned, self-updating queue would remove that friction — multiple class groups can each configure their own lesson schedule and queue independently, no extra apps or accounts needed.

## What Changes

- Build a new multi-chat Telegram bot (Python 3.11+, `python-telegram-bot` v21 async, APScheduler, SQLite).
- Add a database layer to persist chats, configured lessons, queue entries, and active pinned messages.
- Add group-per-chat lesson scheduling: each group's admin configures lessons (`/setlesson`), open-before/lifetime windows, and can list/remove them (`/mylessons`, `/removelesson`).
- Add a scheduler that automatically opens a queue before a lesson, closes it at lesson time, and cleans it up after the lifetime window — all reflecting real DB changes immediately with no restart.
- Add queue commands scoped per chat: `/queue`, `/leave`, `/list`, `/myposition`.
- Keep a single pinned message per session that silently live-edits as people join/leave (no pin spam).
- Add admin permission checks (only chat admins can configure; bot needs Pin + Delete rights), and defensive error handling around every Telegram API call.
- Make scheduling restart-safe: jobs re-register from the DB on bot startup.

## Capabilities

### New Capabilities
- `lesson-config`: per-chat lesson schedule configuration — add, edit, list, and remove lessons with open-before and lifetime windows, restricted to chat admins.
- `lesson-scheduler`: APScheduler-driven open/close/cleanup cycle per lesson, restart-safe job registration from the DB.
- `queue-management`: per-chat, per-session queue state — join, leave, list, position lookup, with duplicate and window guards.
- `pinned-queue-message`: live-edited, silently-pinned single message per session that reflects the current queue state.
- `chat-registry`: persistence of registered chats and their lessons used to restore scheduler state on startup.

### Modified Capabilities

None. No existing specs are in `openspec/specs/`.

## Impact

- New Python package in this repo (bot entry point, DB layer, scheduler, and handlers split across modules).
- Dependencies added: `python-telegram-bot` (v21.*), `APScheduler` (3.*), `python-dotenv`.
- Runtime requirements: a Telegram bot token (`BOT_TOKEN` env var) and persistent storage for the SQLite DB.
- Bot must be added to groups as admin with "Pin messages" and "Delete messages" rights.