"""Per-chat timezone handling for lesson scheduling.

A chat may store an IANA timezone name (e.g. "Asia/Almaty") or a fixed
"UTC±HH(:MM)" string. If none is set, the bot uses server-local time.
"""

import re
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import db

UTC_RE = re.compile(r"^UTC([+-])(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)

CURATED_ZONES = [
    "Europe/London",
    "Europe/Paris",
    "Europe/Moscow",
    "Asia/Tashkent",
    "Asia/Almaty",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Dhaka",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Tokyo",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "America/Sao_Paulo",
]


def resolve_tz(value):
    """Resolve an IANA name or 'UTC±HH(:MM)' string to a tzinfo, else None."""
    name = (value or "").strip()
    if not name:
        return None
    m = UTC_RE.match(name)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        hours = int(m.group(2))
        minutes = int(m.group(3) or 0)
        if hours > 23 or minutes > 59:
            return None
        delta = sign * timedelta(hours=hours, minutes=minutes)
        total = int(delta.total_seconds())
        hours_total = total // 3600
        minutes_remain = abs(total) % 3600 // 60
        display = f"UTC{hours_total:+03d}:{minutes_remain:02d}"
        return timezone(delta, name=display)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None


def chat_tz(chat_id):
    """tzinfo for a chat, or None meaning server-local time."""
    name = db.get_chat_timezone(chat_id)
    if not name:
        return None
    return resolve_tz(name)


def chat_now(chat_id):
    """Aware 'now' in the chat's timezone (server-local if unset)."""
    tz = chat_tz(chat_id)
    if tz is None:
        return datetime.now().astimezone()
    return datetime.now(tz)


def chat_today(chat_id):
    """ISO date string (YYYY-MM-DD) in the chat's timezone."""
    return chat_now(chat_id).date().isoformat()


def offset_label(tz):
    """Human-readable UTC offset label, e.g. '+05:00' or 'UTC'."""
    offset = tz.utcoffset(datetime.now(tz))
    if offset is None:
        return "UTC"
    total = offset.total_seconds()
    sign = "+" if total >= 0 else "-"
    total = abs(int(total))
    return f"UTC{sign}{total // 3600:02d}:{total % 3600 // 60:02d}"