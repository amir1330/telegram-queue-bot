## 1. Shared pending-prompt helper

- [x] 1.1 Add a small module (e.g. `handlers/param_prompt.py`) with pending map keyed by `(chat_id, user_id)`, fields `command`, `prompt_message_id`, `created_at`, and helpers `start_param_prompt`, `get_pending`, `clear_pending`, optional TTL purge
- [x] 1.2 Implement `start_param_prompt` to reply with localized prompt text and `ForceReply(selective=True)`, then store pending state including the sent prompt `message_id`
- [x] 1.3 Add i18n keys (en/ru) for each command prompt (setname, setlesson, before, duration, delete)

## 2. Refactor command apply paths

- [x] 2.1 Refactor `/setname` so parse/apply of the name string is callable with either `context.args` or a follow-up text; bare command starts a prompt instead of usage-only
- [x] 2.2 Refactor `/setlesson` the same way (admin + bot-rights gates before prompt; apply path unchanged once day/time parsed)
- [x] 2.3 Refactor `/before` and `/duration` (`_set_window`) to accept split tokens from args or reply; bare command starts a prompt
- [x] 2.4 Refactor `/delete` likewise (admin gate before prompt)

## 3. Reply handler and registration

- [x] 3.1 Add a text `MessageHandler` (not commands, preferably `filters.REPLY`) that loads pending by `(chat_id, user_id)`, verifies `reply_to_message.message_id`, dispatches to the matching apply path, clears state on success, keeps pending on validation error
- [x] 3.2 On success, best-effort delete the prompt message (ignore delete failures)
- [x] 3.3 Register the handler in `bot.py` without breaking existing command/callback handlers
- [x] 3.4 Ensure non-admin bare admin commands never create pending state; other users' messages never complete someone else's prompt

## 4. Docs and sanity check

- [x] 4.1 Update README command examples to mention bare-command prompts in groups (one-shot args still work)
- [x] 4.2 Manually verify scenarios from `specs/group-param-input/spec.md` (one-shot, ForceReply selective, cross-user isolation, invalid reply)
