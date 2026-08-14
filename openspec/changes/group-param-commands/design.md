## Context

See proposal.md for motivation. Today parametric handlers (`cmd_setname`, `cmd_setlesson`, `cmd_before`/`cmd_duration`, `cmd_delete`) read `context.args` and, if missing, reply with a usage string. There is no pending-input state and no `MessageHandler` for free text. The bot already uses `python-telegram-bot` v21 async; `ForceReply` and per-user context storage are available without new dependencies. `/tz` already has a button UI when called without args and stays out of this flow.

## Goals / Non-Goals

**Goals:**
- Shared helper for “args or selective ForceReply prompt” used by all listed parametric commands.
- Pending state keyed by `(chat_id, user_id)` with a command key and the prompt `message_id`.
- One text handler that completes only matching reply-bound follow-ups.
- Preserve current validation and side effects once arguments are obtained.

**Non-Goals:**
- Changing lesson/queue business rules (overlap checks, windows, DB schema).
- Reworking `/tz` keyboard flow or `/lang` callbacks.
- Persistent DB-backed FSM across bot restarts (in-memory for the process is enough).
- Multi-turn wizards that ask day and time as separate messages (one reply carries the full arg string).

## Decisions

### 1. Lightweight pending map instead of ConversationHandler
**Choice:** Store pending prompts in `application.bot_data` (or a small module-level dict) as `(chat_id, user_id) → {command, prompt_message_id, ...}`.
**Why:** ConversationHandler is heavier and easy to mis-scope in groups; a tiny map makes the `(chat_id, user_id)` isolation explicit and easy to clear.
**Alternatives:** PTB `ConversationHandler` with `per_chat=True, per_user=True` — rejected for less transparent reply-to-message checks and harder optional prompt deletion.

### 2. One follow-up message = full argument string
**Choice:** Prompt text is command-specific (e.g. “Enter name:”, “Enter day and time (e.g. Monday 23:00):”). The user's reply body is split like `context.args` and fed into the same parse/apply path as the one-shot command.
**Why:** Matches existing one-line UX; avoids multi-step FSM for `/setlesson` and optional day on `/before`.
**Alternatives:** Sequential prompts per field — nicer for novices but more state and more group noise; deferred.

### 3. Require reply-to-prompt (plus pending key match)
**Choice:** The text handler accepts a message only if `(chat_id, user_id)` has pending state **and** `message.reply_to_message.message_id == prompt_message_id`.
**Why:** Spec requires not consuming unrelated top-level chat messages from the same user (e.g. chatting while a prompt is open). Selective ForceReply already steers the user to reply; enforcing `reply_to` hardens isolation.
**Alternatives:** Accept any text from that user while pending — simpler but fails the “non-reply does not steal” scenario.

### 4. Shared apply functions
**Choice:** Refactor each command into `parse/apply` helpers callable from both the `CommandHandler` (with `context.args`) and the reply handler (with split reply text). Command handlers only gate permissions, then either apply or `start_param_prompt(...)`.
**Why:** Single validation path; no duplicated overlap/day/time logic.

### 5. Prompt cleanup best-effort
**Choice:** After successful apply, try `delete_message` on the prompt (and optionally the user's reply if bot has delete rights); ignore failures.
**Why:** Spec marks cleanup optional; groups stay cleaner when the bot can delete.

### 6. Invalid reply keeps pending
**Choice:** On validation failure of a bound reply, send an error and leave pending state so the user can reply again to the same prompt (or to a refreshed prompt if we re-send). Prefer keeping the same prompt message when possible.
**Why:** Avoids forcing another `/command` click after a typo; still never applies bad data.

### 7. Handler registration order
**Choice:** Register the pending-reply `MessageHandler` (filters: text, not command, `filters.REPLY`) alongside existing handlers; it no-ops unless pending state matches.
**Why:** Must not interfere with normal chat or future text features; early return when no pending entry.

## Risks / Trade-offs

- **[Risk]** Bot restart drops in-memory pending prompts → **Mitigation:** Acceptable; user re-runs the command. Document briefly in README if needed.
- **[Risk]** User dismisses ForceReply and never replies → **Mitigation:** Optional TTL (e.g. 10 minutes) to clear stale pending entries; cheap to add in the helper.
- **[Risk]** `/before` and `/duration` accept optional day — free-text “Monday 30” vs “30” must reuse existing arg parsing → **Mitigation:** Feed split tokens into the same `_set_window` logic.
- **[Trade-off]** Reply-required follow-up is slightly stricter than “any text while FSM active” → Better group safety; ForceReply makes reply natural.

## Migration Plan

1. Deploy code with new helper + handler; no DB migration.
2. Existing one-shot commands keep working; bare commands switch from usage-only to prompt.
3. Rollback = previous release; no schema to revert.

## Open Questions

None for planning — TTL duration for stale prompts can be chosen at implement time (default 10 minutes) without changing specs.
