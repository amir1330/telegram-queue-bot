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
| `/meet` | open an on-demand Jitsi room (joins open 5 min) |
| `/endmeet` | force-close the active Jitsi room |
| `/setask Monday 12:00 \| Q? \| Yes \| No \| ?Reason` | schedule a question with answers |
| `/asks` | list this chat's scheduled questions |
| `/delask <id>` | delete a scheduled question |
| `/askduration [id] <min>` | how long answers stay open (default 360) |
| `/askpost <id>` | post a question now (testing) |

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

## On-demand video rooms (/meet)

Groups only, admins only. `/meet` posts one message with a Join button
(deep link into the bot DM). Members tapping it get a personal Jitsi link;
admins enter as moderators, everyone else as guests. Non-members and expired
links are refused. Joins stay open 5 minutes; at the deadline the session
closes and the group message is deleted, so `/meet` works again.
`/endmeet` closes early.

Limitation (Phase 1): a call already running keeps going after the 5 minutes
— expiry only blocks new joins. Occupancy-based auto-close was investigated
on the VPS (stable-11248): `mod_muc_size` needs an `app_id` module option the
stock templates cannot set, and `mod_muc_census` looks up
`conference.<host>` which does not match this deployment's `muc.meet.jitsi`,
so neither worked. The bot stays on Phase 1.

Requires JWT auth on Jitsi (`AUTH_TYPE=jwt`, `JWT_APP_ID=lessons`, …) and bot
env `JITSI_DOMAIN` + `JITSI_JWT_SECRET` (server `.env` only).

## Scheduled questions (/setask)

Admins schedule repeating questions, e.g.
`/setask Monday 12:00 | Are you coming Mon 18:00? | Yes | No | ?I have a reason`
(`?` = answering needs a reason). Times use the chat timezone. The bot posts
the question weekly with one button per option and live-edits the tally as
people answer; tapping your answer again retracts it. `?` options prompt only
you for a reason (3-minute window), then save. Answers close after
`duration_min` (default 360); buttons are removed and the tally stays.

## Owner rooms (/room)

DM-only, owner-only (`OWNER_ID` env). `/room [name]` replies with a moderator
link (8h) and a shareable guest link (3h). Independent of `/meet`.

## Requirements for a group

- Add the bot and promote it to **admin** with **Pin messages** and **Delete
  messages** rights (the bot tells you if it lacks them).
- In **@BotFather** → your bot → **Group Privacy** → **Turn off**. Otherwise
  Telegram hides normal group messages from the bot, and after `/setlesson`
  typing `23:00` without Reply does nothing.
- Set the chat's timezone once with `/tz` so lesson times and cron jobs match
  your local time. If unset, the bot uses the server's local time.

## Deployment (Docker + CI/CD)

Same idea as **sanaq**, hardened:

1. GitHub Actions builds/pushes `ghcr.io/amir1330/queue-bot`
2. CI SSHs as non-root user **`queuebot`** with a **forced-command** key
3. Remote `deploy/ci-entry.sh` only accepts `sync-deploy` / `deploy`
4. Host key is pinned in `.github/known_hosts`

No webhook. No root SSH from CI.

### One-time VPS + secrets setup

From your laptop (needs `gh` auth + SSH as root once):

```bash
chmod +x deploy/provision-ci-key.sh
./deploy/provision-ci-key.sh
```

This creates `queuebot` (in `docker` group), installs the restricted key, and sets
repo secrets `HOST`, `USERNAME`, `SSH_KEY`.

### Server layout

| Path | Purpose |
|---|---|
| `/home/queuebot/telegram-queue-bot/` | compose + `.env` (`BOT_TOKEN=...`) |
| `/home/queuebot/bin/ci-entry.sh` | forced-command entrypoint |

SQLite stays in Docker volume `queue_bot_data`.

### GitHub secrets

| Secret | Value |
|---|---|
| `HOST` | VPS IP |
| `USERNAME` | `queuebot` |
| `SSH_KEY` | private key (forced-command) |

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
