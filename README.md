# Telegram Queue Bot

A multi-chat Telegram bot that manages a fair, live queue for lessons. Each
group adds the bot, an admin configures the group's own lesson schedule, and
the bot auto-opens a silently-pinned queue before each lesson, live-edits it as
students join/leave, closes it at lesson time, and cleans it up afterwards.

## Stack

- Python 3.11+
- `python-telegram-bot` v21 (async, polling)
- `APScheduler` 3.x
- SQLite (single file `queue_bot.db`)

## How it works

- An admin sets up lessons per chat (`/setlesson Monday 23:00`).
- `before` minutes before a lesson the bot pins a queue message; students join
  and leave by tapping the buttons under it (or with `/queue`, `/leave`).
- The queue keeps accepting joins until `duration` minutes after the lesson
  starts, then buttons turn off and the message is unpinned (the list stays).
  Windows that cross midnight (e.g. 23:00 → 01:00) work: the session is keyed
  by the lesson's calendar day, not "today".
- All state is scoped per chat and persisted in SQLite; on restart the bot
  re-registers every scheduled job from the DB.

## Setup (local)

1. Create a bot via **@BotFather** → `/newbot`, copy the token.
2. `cp .env.example .env` and set `BOT_TOKEN=...`
3. `pip install -r requirements.txt`
4. `python bot.py`

## Commands

### Group admins

| Command | Effect |
|---|---|
| `/setlesson Monday 23:00` | add/update a lesson (or bare `/setlesson` → day buttons, then type time) |
| `/before [day] <min>` | minutes before the lesson the queue opens (default 30) |
| `/duration [day] <min>` | minutes after lesson start the queue keeps accepting joins (default 120) |
| `/delete Monday` | remove a lesson (English or Russian day names work) |
| `/tz` | set the chat's timezone (IANA name or UTC+HH:MM) |
| `/ping` | mention known members who are not in the open queue |

Config changes apply to the scheduler immediately — no restart needed.

Parametric admin commands also work **without arguments** (`/setlesson`,
`/before`, `/duration`, `/delete`): the bot asks only the caller for the
value via a selective reply prompt, so other group members are not pulled
into the flow. One-shot forms with args still work as above.

### Students

| Command | Effect |
|---|---|
| `/queue` | join today's open queue |
| `/leave` | leave the queue |
| `/setname Amir Abu Yunus` | set the name shown in this chat's queue |
| `/info` | current settings + command list |
| `/lang` | choose chat language (English / Русский) |

Bare `/setname` prompts only you for a name (same selective reply pattern).
One-shot `/setname <name>` still applies immediately.

## Requirements for a group

- Add the bot and promote it to **admin** with **Pin messages** and **Delete
  messages** rights (the bot tells you if it lacks them).
- In **@BotFather** → your bot → **Group Privacy** → **Turn off**. Otherwise
  Telegram hides normal group messages from the bot, and after `/setlesson`
  typing `23:00` without Reply does nothing.
- Set the chat's timezone once with `/tz` so lesson times and cron jobs match
  your local time. If unset, the bot uses the server's local time.

## Deployment (Docker + CI/CD)

Same pattern as **sanaq**: GitHub Actions builds the image, pushes to GHCR,
then SSHs into the VPS and recreates the container. **No webhook.**

Workflow: `.github/workflows/ci.yml`

1. build + push `ghcr.io/amir1330/queue-bot:latest` (and `:sha`)
2. SCP `docker-compose.prod.yml` + `deploy/remote.sh` to `/root/telegram-queue-bot`
3. SSH-run `deploy/remote.sh` → `docker login` → `compose pull` → recreate

### Server setup

1. Directory on the VPS: `/root/telegram-queue-bot`
2. `.env` next to compose (only runtime secrets):

   ```env
   BOT_TOKEN=your_bot_token
   ```

3. SQLite lives in the Docker volume `queue_bot_data` — survives recreates.

### GitHub secrets

Repo → Settings → Secrets → Actions (same names as sanaq):

| Secret | Value |
|---|---|
| `HOST` | VPS IP / hostname |
| `USERNAME` | SSH user (e.g. `root`) |
| `SSH_KEY` | private key for that user |

`GITHUB_TOKEN` is provided by Actions for GHCR push/pull — no deploy token needed.

**Never commit the bot token.** It stays in the server `.env` only.

## Notes / design decisions

- The queue opens `before` minutes before the lesson and keeps accepting joins
  until `duration` minutes after the lesson starts. Then the list stays in
  chat (buttons off, unpinned) — it is not deleted.
- Users can override the name shown in the queue with `/setname` — handy when
  two students share a first name. In groups, bare `/setname` (and other
  parametric commands) use a selective ForceReply so only the caller is
  prompted; pending input is keyed by `(chat_id, user_id)`.
- A single pinned message per session is updated in place — no pin spam.
- A lesson at 00:10 is opened the previous day; the session date is the lesson
  date, so today's queue never mixes with next week's.

## Tests

```bash
pip install -r requirements.txt
python tests/test_db.py
```
