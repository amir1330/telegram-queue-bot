"""SQLite data layer for the telegram lesson-queue bot.

Thin wrapper functions around a single SQLite connection. Everything is
guarded by a lock because APScheduler jobs and the polling update queue
run concurrently in the event loop.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone

_DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "queue_bot.db"))

DEFAULT_LANG = "ru"
DEFAULT_TIMEZONE = "Asia/Almaty"

_CONN = None
_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    lang TEXT DEFAULT 'ru',
    timezone TEXT DEFAULT 'Asia/Almaty'
);

CREATE TABLE IF NOT EXISTS lessons (
    lesson_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    day_of_week TEXT,
    lesson_time TEXT,
    open_before_min INTEGER DEFAULT 30,
    lifetime_min INTEGER DEFAULT 120,
    header_text TEXT,
    answer_timer_sec INTEGER NOT NULL DEFAULT 420,
    UNIQUE (chat_id, day_of_week),
    FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
);

CREATE TABLE IF NOT EXISTS queue_entries (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    lesson_id INTEGER,
    user_id INTEGER,
    display_name TEXT,
    joined_at TEXT,
    session_date TEXT,
    UNIQUE (chat_id, lesson_id, user_id, session_date)
);

CREATE TABLE IF NOT EXISTS active_messages (
    chat_id INTEGER,
    lesson_id INTEGER,
    session_date TEXT,
    message_id INTEGER,
    status TEXT DEFAULT 'open',
    PRIMARY KEY (chat_id, lesson_id, session_date)
);

CREATE TABLE IF NOT EXISTS user_names (
    chat_id INTEGER,
    user_id INTEGER,
    display_name TEXT,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS known_users (
    chat_id INTEGER,
    user_id INTEGER,
    display_name TEXT,
    username TEXT,
    last_seen TEXT,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS chat_state (
    chat_id INTEGER PRIMARY KEY,
    last_lesson_id INTEGER
);

CREATE TABLE IF NOT EXISTS param_pending (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    command TEXT NOT NULL,
    prompt_message_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    payload TEXT,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS active_timers (
    chat_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    session_date TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    current_index INTEGER NOT NULL DEFAULT 0,
    remaining_seconds INTEGER NOT NULL,
    running INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    PRIMARY KEY (chat_id, lesson_id, session_date)
);
"""


def _connect():
    global _CONN
    if _CONN is None:
        _CONN = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA journal_mode=WAL")
        _CONN.execute("PRAGMA foreign_keys=ON")
        with _LOCK:
            _CONN.executescript(_SCHEMA)
            _CONN.commit()
            _migrate(_CONN)
    return _CONN


def _migrate(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(chats)").fetchall()}
    if "lang" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN lang TEXT DEFAULT 'en'")
        conn.commit()
    if "timezone" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN timezone TEXT")
        conn.commit()
    pending_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(param_pending)").fetchall()
    }
    if pending_cols and "payload" not in pending_cols:
        conn.execute("ALTER TABLE param_pending ADD COLUMN payload TEXT")
        conn.commit()
    known_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(known_users)").fetchall()
    }
    if known_cols and "username" not in known_cols:
        conn.execute("ALTER TABLE known_users ADD COLUMN username TEXT")
        conn.commit()
    lesson_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()
    }
    if lesson_cols and "header_text" not in lesson_cols:
        conn.execute("ALTER TABLE lessons ADD COLUMN header_text TEXT")
        conn.commit()
    if lesson_cols and "answer_timer_sec" not in lesson_cols:
        conn.execute("ALTER TABLE lessons ADD COLUMN answer_timer_sec INTEGER NOT NULL DEFAULT 420")
        conn.commit()
        # ensure existing rows get new default
        try:
            conn.execute("UPDATE lessons SET answer_timer_sec = 420 WHERE answer_timer_sec IS NULL OR answer_timer_sec IN (60, 300)")
            conn.commit()
        except Exception:
            pass
    else:
        # migrate existing defaults from 60/300 to 420 (one-time, 7 min)
        try:
            conn.execute("UPDATE lessons SET answer_timer_sec = 420 WHERE answer_timer_sec IN (60, 300)")
            conn.commit()
        except Exception:
            pass
    conn.execute(
        "DELETE FROM queue_entries WHERE entry_id NOT IN "
        "(SELECT MIN(entry_id) FROM queue_entries "
        "GROUP BY chat_id, lesson_id, user_id, session_date)"
    )
    conn.commit()
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_queue_entry "
        "ON queue_entries (chat_id, lesson_id, user_id, session_date)"
    )
    conn.commit()


def close():
    global _CONN
    with _LOCK:
        if _CONN is not None:
            _CONN.close()
            _CONN = None


def init_db():
    _connect()


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- chats

def add_chat(chat_id, title=None):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO chats (chat_id, title, lang, timezone) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title = COALESCE(excluded.title, chats.title)",
            (chat_id, title, DEFAULT_LANG, DEFAULT_TIMEZONE),
        )
        conn.commit()


def get_chat_lang(chat_id):
    with _LOCK:
        row = _connect().execute(
            "SELECT lang FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if row is None or not row["lang"]:
        return DEFAULT_LANG
    return row["lang"]


def set_chat_lang(chat_id, lang, title=None):
    add_chat(chat_id, title)
    with _LOCK:
        conn = _connect()
        conn.execute("UPDATE chats SET lang = ? WHERE chat_id = ?", (lang, chat_id))
        conn.commit()


def get_all_chat_ids():
    with _LOCK:
        rows = _connect().execute("SELECT chat_id FROM chats ORDER BY chat_id").fetchall()
        return [r["chat_id"] for r in rows]


def get_chat_timezone(chat_id):
    """IANA timezone name for a chat (defaults to Asia/Almaty)."""
    with _LOCK:
        row = _connect().execute(
            "SELECT timezone FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if row is None or not row["timezone"]:
        return DEFAULT_TIMEZONE
    return row["timezone"]


def set_chat_timezone(chat_id, tz_name, title=None):
    """Store an IANA timezone name for a chat. None clears it (server-local)."""
    add_chat(chat_id, title)
    with _LOCK:
        conn = _connect()
        conn.execute(
            "UPDATE chats SET timezone = ? WHERE chat_id = ?", (tz_name, chat_id)
        )
        conn.commit()


# -------------------------------------------------------------- lessons

def add_lesson(chat_id, day_of_week, lesson_time, open_before_min=30, lifetime_min=120, title=None):
    """Insert or update the lesson for (chat, day_of_week). Returns the lesson row.

    On update (same day already exists), only the time is changed — open_before
    and lifetime are preserved so /setlesson does not wipe /before and /duration.
    """
    add_chat(chat_id, title)
    with _LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO lessons (chat_id, day_of_week, lesson_time, open_before_min, lifetime_min) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, day_of_week) DO UPDATE SET "
            "lesson_time = excluded.lesson_time",
            (chat_id, day_of_week, lesson_time, open_before_min, lifetime_min),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM lessons WHERE chat_id = ? AND day_of_week = ?",
            (chat_id, day_of_week),
        ).fetchone()
        return dict(row)


def get_all_lessons():
    with _LOCK:
        rows = _connect().execute(
            "SELECT * FROM lessons ORDER BY chat_id, day_of_week"
        ).fetchall()
        return [dict(r) for r in rows]


def get_lessons(chat_id):
    with _LOCK:
        rows = _connect().execute(
            "SELECT * FROM lessons WHERE chat_id = ? ORDER BY day_of_week", (chat_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_lesson_by_id(lesson_id):
    with _LOCK:
        row = _connect().execute(
            "SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()
        return dict(row) if row else None


def remove_lesson(chat_id, day_of_week):
    """Delete the (chat, day) lesson. Returns the deleted lesson_id or None."""
    with _LOCK:
        conn = _connect()
        row = conn.execute(
            "SELECT lesson_id FROM lessons WHERE chat_id = ? AND day_of_week = ?",
            (chat_id, day_of_week),
        ).fetchone()
        if row is None:
            return None
        lesson_id = row["lesson_id"]
        conn.execute("DELETE FROM lessons WHERE lesson_id = ?", (lesson_id,))
        conn.execute("DELETE FROM queue_entries WHERE lesson_id = ?", (lesson_id,))
        conn.execute("DELETE FROM active_messages WHERE lesson_id = ?", (lesson_id,))
        conn.execute("DELETE FROM active_timers WHERE lesson_id = ?", (lesson_id,))
        conn.commit()
        return lesson_id


def update_lesson_window(lesson_id, open_before_min=None, lifetime_min=None):
    sets, params = [], []
    if open_before_min is not None:
        sets.append("open_before_min = ?")
        params.append(open_before_min)
    if lifetime_min is not None:
        sets.append("lifetime_min = ?")
        params.append(lifetime_min)
    if not sets:
        return get_lesson_by_id(lesson_id)
    params.append(lesson_id)
    with _LOCK:
        conn = _connect()
        conn.execute(f"UPDATE lessons SET {', '.join(sets)} WHERE lesson_id = ?", params)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()
        return dict(row) if row else None


def update_lesson_header(lesson_id, header_text):
    """Set or clear the custom text under the lesson line on the queue message."""
    value = (header_text or "").strip() or None
    with _LOCK:
        conn = _connect()
        conn.execute(
            "UPDATE lessons SET header_text = ? WHERE lesson_id = ?",
            (value, lesson_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)
        ).fetchone()
        return dict(row) if row else None


def set_answer_timer(chat_id, day_of_week, seconds):
    """Set timer duration for a lesson day. Returns the updated lesson row or None."""
    with _LOCK:
        conn = _connect()
        row = conn.execute(
            "SELECT lesson_id FROM lessons WHERE chat_id = ? AND day_of_week = ?",
            (chat_id, day_of_week),
        ).fetchone()
        if row is None:
            return None
        lesson_id = row["lesson_id"]
        conn.execute(
            "UPDATE lessons SET answer_timer_sec = ? WHERE lesson_id = ?",
            (seconds, lesson_id),
        )
        conn.commit()
        r = conn.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
        return dict(r) if r else None


def update_answer_timer(lesson_id, seconds):
    """Set timer duration by lesson_id. Returns updated row."""
    with _LOCK:
        conn = _connect()
        conn.execute("UPDATE lessons SET answer_timer_sec = ? WHERE lesson_id = ?", (seconds, lesson_id))
        conn.commit()
        r = conn.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
        return dict(r) if r else None


# ----------------------------------------------------------- chat state

def set_last_lesson(chat_id, lesson_id):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO chat_state (chat_id, last_lesson_id) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET last_lesson_id = excluded.last_lesson_id",
            (chat_id, lesson_id),
        )
        conn.commit()


def get_last_lesson(chat_id):
    with _LOCK:
        row = _connect().execute(
            "SELECT last_lesson_id FROM chat_state WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if row is None:
        return None
    return get_lesson_by_id(row["last_lesson_id"])


# ------------------------------------------------------------ queue rows

def position_of(chat_id, lesson_id, session_date, user_id):
    """1-based position of user in a queue, or None."""
    entries = get_queue(chat_id, lesson_id, session_date)
    for i, e in enumerate(entries, start=1):
        if e["user_id"] == user_id:
            return i
    return None


def add_queue_entry(chat_id, lesson_id, user_id, display_name, session_date):
    """Add a user. Returns the entry row, or None if already queued.

    The UNIQUE(chat_id, lesson_id, user_id, session_date) constraint is the
    source of truth: the insert itself rejects a duplicate, so there is no
    check-then-insert race window.
    """
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO queue_entries "
                "(chat_id, lesson_id, user_id, display_name, joined_at, session_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, lesson_id, user_id, display_name, _now(), session_date),
            )
        except sqlite3.IntegrityError:
            return None
        conn.commit()
        row = conn.execute(
            "SELECT * FROM queue_entries WHERE entry_id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def remove_queue_entry(chat_id, lesson_id, user_id, session_date):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "DELETE FROM queue_entries WHERE chat_id = ? AND lesson_id = ? AND user_id = ? AND session_date = ?",
            (chat_id, lesson_id, user_id, session_date),
        )
        conn.commit()


def get_queue(chat_id, lesson_id, session_date):
    with _LOCK:
        rows = _connect().execute(
            "SELECT * FROM queue_entries "
            "WHERE chat_id = ? AND lesson_id = ? AND session_date = ? "
            "ORDER BY entry_id",
            (chat_id, lesson_id, session_date),
        ).fetchall()
        return [dict(r) for r in rows]


def clear_queue(chat_id, lesson_id, session_date):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "DELETE FROM queue_entries WHERE chat_id = ? AND lesson_id = ? AND session_date = ?",
            (chat_id, lesson_id, session_date),
        )
        conn.commit()


def get_last_queue(chat_id, before_session_date=None):
    """Return previous queue session with entries before given date."""
    with _LOCK:
        conn = _connect()
        if before_session_date:
            rows = conn.execute(
                "SELECT lesson_id, session_date FROM queue_entries "
                "WHERE chat_id = ? AND session_date < ? "
                "GROUP BY lesson_id, session_date "
                "ORDER BY session_date DESC, lesson_id DESC LIMIT 1",
                (chat_id, before_session_date),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT lesson_id, session_date FROM queue_entries "
                "WHERE chat_id = ? GROUP BY lesson_id, session_date "
                "ORDER BY session_date DESC, lesson_id DESC LIMIT 1",
                (chat_id,),
            ).fetchall()
        if not rows:
            return None
        lesson_id = rows[0]["lesson_id"]
        session_date = rows[0]["session_date"]
        entries = get_queue(chat_id, lesson_id, session_date)
        if not entries:
            return None
        return {"lesson_id": lesson_id, "session_date": session_date, "entries": entries}


def copy_queue(chat_id, from_lesson_id, from_session_date, to_lesson_id, to_session_date):
    """Replace to-queue with copy of from-queue. Returns number of copied entries."""
    src = get_queue(chat_id, from_lesson_id, from_session_date)
    if not src:
        return 0
    with _LOCK:
        conn = _connect()
        conn.execute(
            "DELETE FROM queue_entries WHERE chat_id = ? AND lesson_id = ? AND session_date = ?",
            (chat_id, to_lesson_id, to_session_date),
        )
        for e in src:
            try:
                conn.execute(
                    "INSERT INTO queue_entries (chat_id, lesson_id, user_id, display_name, joined_at, session_date) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (chat_id, to_lesson_id, e["user_id"], e["display_name"], _now(), to_session_date),
                )
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        return len(src)


# ------------------------------------------------------------ user names

def set_user_display_name(chat_id, user_id, display_name):
    """Store a custom display name for a user in a chat (used in the queue).

    Also renames any existing queue entries so the change shows immediately.
    """
    with _LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO user_names (chat_id, user_id, display_name) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET display_name = excluded.display_name",
            (chat_id, user_id, display_name),
        )
        conn.execute(
            "UPDATE queue_entries SET display_name = ? WHERE chat_id = ? AND user_id = ?",
            (display_name, chat_id, user_id),
        )
        conn.commit()


def get_user_display_name(chat_id, user_id):
    """Custom display name for a user in a chat, or None."""
    with _LOCK:
        row = _connect().execute(
            "SELECT display_name FROM user_names WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        ).fetchone()
        return row["display_name"] if row else None


def touch_known_user(chat_id, user_id, display_name=None, username=None):
    """Remember a user we have seen in this chat (for /all mentions)."""
    if user_id is None:
        return
    username = (username or "").lstrip("@") or None
    with _LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO known_users (chat_id, user_id, display_name, username, last_seen) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
            "display_name = COALESCE(excluded.display_name, known_users.display_name), "
            "username = COALESCE(excluded.username, known_users.username), "
            "last_seen = excluded.last_seen",
            (chat_id, user_id, display_name, username, _now()),
        )
        conn.commit()


def get_known_users(chat_id):
    """Users the bot has seen in this chat (known_users + queue history + setnames)."""
    with _LOCK:
        conn = _connect()
        rows = conn.execute(
            "SELECT user_id, "
            "MAX(display_name) AS display_name, "
            "MAX(username) AS username "
            "FROM ("
            "  SELECT user_id, display_name, username FROM known_users WHERE chat_id = ? "
            "  UNION ALL "
            "  SELECT user_id, display_name, NULL AS username FROM user_names WHERE chat_id = ? "
            "  UNION ALL "
            "  SELECT user_id, display_name, NULL AS username FROM queue_entries WHERE chat_id = ?"
            ") GROUP BY user_id ORDER BY user_id",
            (chat_id, chat_id, chat_id),
        ).fetchall()
        out = []
        for r in rows:
            uid = r["user_id"]
            custom = conn.execute(
                "SELECT display_name FROM user_names WHERE chat_id = ? AND user_id = ?",
                (chat_id, uid),
            ).fetchone()
            known = conn.execute(
                "SELECT username FROM known_users WHERE chat_id = ? AND user_id = ?",
                (chat_id, uid),
            ).fetchone()
            out.append(
                {
                    "user_id": uid,
                    "display_name": (
                        custom["display_name"] if custom else r["display_name"]
                    )
                    or str(uid),
                    "username": (known["username"] if known else None)
                    or r["username"]
                    or None,
                }
            )
        return out


# -------------------------------------------------------- active messages

def save_active_message(chat_id, lesson_id, session_date, message_id, status="open"):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO active_messages (chat_id, lesson_id, session_date, message_id, status) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, lesson_id, session_date) DO UPDATE SET "
            "message_id = excluded.message_id, status = excluded.status",
            (chat_id, lesson_id, session_date, message_id, status),
        )
        conn.commit()


def get_active_message(chat_id, lesson_id, session_date):
    with _LOCK:
        row = _connect().execute(
            "SELECT * FROM active_messages WHERE chat_id = ? AND lesson_id = ? AND session_date = ?",
            (chat_id, lesson_id, session_date),
        ).fetchone()
        return dict(row) if row else None


def get_active_messages(chat_id=None, session_date=None, status=None):
    query = "SELECT * FROM active_messages"
    conds, params = [], []
    if chat_id is not None:
        conds.append("chat_id = ?")
        params.append(chat_id)
    if session_date is not None:
        conds.append("session_date = ?")
        params.append(session_date)
    if status is not None:
        conds.append("status = ?")
        params.append(status)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY session_date, lesson_id"
    with _LOCK:
        rows = _connect().execute(query, params).fetchall()
        return [dict(r) for r in rows]


def mark_active_closed(chat_id, lesson_id, session_date):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "UPDATE active_messages SET status = 'closed' "
            "WHERE chat_id = ? AND lesson_id = ? AND session_date = ?",
            (chat_id, lesson_id, session_date),
        )
        conn.commit()


def delete_active_message(chat_id, lesson_id, session_date):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "DELETE FROM active_messages WHERE chat_id = ? AND lesson_id = ? AND session_date = ?",
            (chat_id, lesson_id, session_date),
        )
        conn.commit()


# -------------------------------------------------------- active timers

def save_active_timer(chat_id, lesson_id, session_date, message_id, current_index=0, remaining_seconds=420, running=0, started_at=None):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO active_timers (chat_id, lesson_id, session_date, message_id, current_index, remaining_seconds, running, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, lesson_id, session_date) DO UPDATE SET "
            "message_id = excluded.message_id, current_index = excluded.current_index, "
            "remaining_seconds = excluded.remaining_seconds, running = excluded.running, started_at = excluded.started_at",
            (chat_id, lesson_id, session_date, message_id, current_index, remaining_seconds, running, started_at),
        )
        conn.commit()


def get_active_timer(chat_id, lesson_id, session_date):
    with _LOCK:
        row = _connect().execute(
            "SELECT * FROM active_timers WHERE chat_id = ? AND lesson_id = ? AND session_date = ?",
            (chat_id, lesson_id, session_date),
        ).fetchone()
        return dict(row) if row else None


def get_active_timers(chat_id=None, lesson_id=None, session_date=None):
    query = "SELECT * FROM active_timers"
    conds, params = [], []
    if chat_id is not None:
        conds.append("chat_id = ?")
        params.append(chat_id)
    if lesson_id is not None:
        conds.append("lesson_id = ?")
        params.append(lesson_id)
    if session_date is not None:
        conds.append("session_date = ?")
        params.append(session_date)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY session_date, lesson_id"
    with _LOCK:
        rows = _connect().execute(query, params).fetchall()
        return [dict(r) for r in rows]


def update_active_timer(chat_id, lesson_id, session_date, **fields):
    allowed = {"message_id", "current_index", "remaining_seconds", "running", "started_at"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return get_active_timer(chat_id, lesson_id, session_date)
    params.extend([chat_id, lesson_id, session_date])
    with _LOCK:
        conn = _connect()
        conn.execute(f"UPDATE active_timers SET {', '.join(sets)} WHERE chat_id = ? AND lesson_id = ? AND session_date = ?", params)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM active_timers WHERE chat_id = ? AND lesson_id = ? AND session_date = ?",
            (chat_id, lesson_id, session_date),
        ).fetchone()
        return dict(row) if row else None


def delete_active_timer(chat_id, lesson_id, session_date):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "DELETE FROM active_timers WHERE chat_id = ? AND lesson_id = ? AND session_date = ?",
            (chat_id, lesson_id, session_date),
        )
        conn.commit()


def delete_active_timers_for_lesson(lesson_id):
    with _LOCK:
        conn = _connect()
        conn.execute("DELETE FROM active_timers WHERE lesson_id = ?", (lesson_id,))
        conn.commit()


def set_param_pending(chat_id, user_id, command, prompt_message_id, created_at, payload=None):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO param_pending "
            "(chat_id, user_id, command, prompt_message_id, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
            "command = excluded.command, "
            "prompt_message_id = excluded.prompt_message_id, "
            "created_at = excluded.created_at, "
            "payload = excluded.payload",
            (chat_id, user_id, command, prompt_message_id, created_at, payload),
        )
        conn.commit()


def get_param_pending(chat_id, user_id):
    with _LOCK:
        row = _connect().execute(
            "SELECT * FROM param_pending WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def clear_param_pending(chat_id, user_id):
    with _LOCK:
        conn = _connect()
        conn.execute(
            "DELETE FROM param_pending WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        conn.commit()


def purge_expired_param_pending(older_than):
    """Delete pending prompts with created_at older than the given monotonic/unix cutoff."""
    with _LOCK:
        conn = _connect()
        conn.execute(
            "DELETE FROM param_pending WHERE created_at < ?",
            (older_than,),
        )
        conn.commit()