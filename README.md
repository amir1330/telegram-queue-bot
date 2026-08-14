# Telegram Lesson-Queue Bot

A multi-chat Telegram bot that manages a fair, live queue for lessons. Each
group adds the bot, an admin configures the group's own lesson schedule, and
the bot auto-opens a silently-pinned queue before each lesson, live-edits it as
students join/leave, closes it at lesson time, and cleans it up afterwards.

## Stack

- Python 3.11+
- `python-telegram-bot` v21 (async, polling)
- `APScheduler` 3.x
- SQLite (single file `queue_bot.db`)

## Setup

1. Create a bot via **@BotFather** → `/newbot`, copy the token.
2. `cp .env.example .env` and set `BOT_TOKEN=...`
3. `pip install -r requirements.txt`
4. `python bot.py`

The bot re-registers all scheduled jobs from the DB on startup, so restarts
and redeploys are safe.

## Admin commands (group admins only)

| Command | Effect |
|---|---|
| `/setlesson Monday 23:00` | add/update a lesson for this chat (English or Russian day names work) |
| `/before [day] <min>` | minutes before the lesson the queue opens (default 30) |
| `/duration [day] <min>` | minutes after lesson start the queue keeps accepting joins (default 120) |
| `/delete Monday` | remove a lesson (English or Russian day names work) |
| `/tz` | set the chat's timezone (IANA name or UTC+HH:MM) |

Config changes apply to the scheduler immediately — no restart needed.

## Student commands

| Command | Effect |
|---|---|
| `/queue` | join today's open queue |
| `/leave` | leave the queue |
| `/setname Amir Abu Yunus` | set the name shown in this chat's queue |
| `/info` | current settings + command list |
| `/lang` | choose chat language (English / Русский) |

Students can also join/leave by tapping the buttons under the pinned queue
message. All queue state is scoped per chat — groups never mix.

## Requirements for a group

- Add the bot and promote it to **admin** with **Pin messages** and **Delete
  messages** rights (the bot tells you if it lacks them).
- Set the chat's timezone once with `/tz` so lesson times and the cron jobs
  match your local time. If unset, the bot uses the server's local time.

## Deployment

### Railway / Render (simplest)
- Push this repo, add a worker/service process running `python bot.py`.
- Set `BOT_TOKEN` as an environment variable.
- **Persistent storage is required** — SQLite must survive redeploys. Railway
  volume (mounted at `/data`) or Render Disk: set `DB_PATH=/data/queue_bot.db`.

### VPS + systemd
- `pip install -r requirements.txt`, place the repo at e.g. `/opt/queue_bot`.
- `systemd` service:

```
[Unit]
Description=Telegram Lesson-Queue Bot
After=network.target

[Service]
User=bot
WorkingDirectory=/opt/queue_bot
EnvironmentFile=/opt/queue_bot/.env
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

- Keep `.env` (with the token) out of git; make sure `queue_bot.db` lives on
  persistent storage.

## Rollout

1. Add the bot to your groups, promote to admin (Pin + Delete).
2. Each group admin runs `/setlesson` (+ optional `/before`, `/duration`).
3. Tell students to tap **Join** under the pinned message.
4. Watch the first real cycle live in case a timezone or permission issue shows up.

## Notes / design decisions

- The queue opens `before` minutes before the lesson and keeps accepting joins
  until `duration` minutes after the lesson starts (then the message is
  deleted). No intermediate "closed" state. The pinned message shows this
  window, so students know when it closes.
- Users can override the name shown in the queue with `/setname` — handy when
  two students share a first name.
- A single pinned message per session is updated in place — no pin spam.
- A lesson at 00:10 is opened the previous day; the session date is the lesson
  date, so today's queue never mixes with next week's.
