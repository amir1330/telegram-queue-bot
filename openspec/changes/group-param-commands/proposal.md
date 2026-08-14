## Why

Parametric commands (`/setname`, `/setlesson`, `/before`, `/duration`, `/delete`) currently reply with a usage hint when arguments are missing. In a group chat that is awkward: several people may type at once, and without per-user reply targeting the bot can confuse one member's free-text answer with another's. We need a group-safe argument collection flow so bare commands prompt only the caller and never steal other users' messages.

## What Changes

- Add dual input for every parametric command: process args immediately when present; when absent, start a per-user prompt flow instead of only showing usage text.
- Prompt with `ForceReply(selective=True)` so Telegram's reply UI appears only for the user who issued the command.
- Track pending input keyed by `(chat_id, user_id)` plus a command key, so Vasya's `/setname` cannot consume Petya's chat message.
- Accept the follow-up only when it is a reply to the bot's prompt (or the matching FSM state for that user) and then clear state; optionally delete the intermediate prompt message.
- Keep existing one-line forms working unchanged (`/setname Иван`, `/setlesson Monday 23:00`, etc.).
- `/tz` stays on its current keyboard/picker when called without args (already interactive); only text-arg one-shot remains as today.

## Capabilities

### New Capabilities
- `group-param-input`: shared group-safe collection of command parameters via one-shot args or ForceReply + per-(chat, user) pending state, covering `/setname`, `/setlesson`, `/before`, `/duration`, and `/delete`.

### Modified Capabilities

None. No existing specs are in `openspec/specs/`.

## Impact

- Handlers: `handlers/queue_handlers.py` (`/setname`), `handlers/config_handlers.py` (`/setlesson`, `/before`, `/duration`, `/delete`).
- Registration: `bot.py` gains a `MessageHandler` for text replies that completes pending prompts.
- Likely a small shared helper module for pending state, ForceReply prompts, and cleanup.
- i18n: new prompt strings (e.g. “Enter [parameter]:”) in en/ru; usage strings remain for invalid replies.
- Dependency surface unchanged (`python-telegram-bot` already supports `ForceReply` and ConversationHandler / custom context storage).
