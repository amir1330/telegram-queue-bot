"""HTML message builders and inline keyboards for the queue bot."""

import html
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from i18n import tr
from queue_view import DAY_INDEX, DAYS_EN, DAYS_RU
from timezone import CURATED_ZONES, offset_label, resolve_tz

# Markdown-style mentions copied from Telegram clients, e.g.
# [Name](tg://user?id=123) or [Name](tg://resolve?domain=user)
_HEADER_MD_LINK = re.compile(
    r"\[([^\]]+)\]\("
    r"(?:"
    r"tg://user\?id=(\d+)"
    r"|tg://resolve\?domain=([A-Za-z0-9_]{4,32})"
    r"|https?://t\.me/([A-Za-z0-9_]{4,32})"
    r")"
    r"\)"
)
_FENCE_RE = re.compile(r"^```(?:\w+\r?\n)?([\s\S]*?)```$", re.MULTILINE)


def _utf16_slice(text: str, offset: int, length: int) -> str:
    raw = text.encode("utf-16-le")
    return raw[offset * 2 : (offset + length) * 2].decode("utf-16-le")


def serialize_header_from_message(message) -> str:
    """Rebuild header text so mentions survive Telegram's client rewriting.

    Clients often turn [Name](tg://user?id=…) into plain text + entities.
    We turn entities back into markdown links. Code/pre blocks keep literal text
    (useful if the user wraps the markdown in ``` … ```).
    """
    text = message.text or message.caption or ""
    entities = list(message.entities or message.caption_entities or [])

    # Whole message is a code/pre block → keep raw markdown inside.
    if len(entities) == 1 and entities[0].type in ("pre", "code"):
        try:
            return message.parse_entity(entities[0]).strip()
        except Exception:
            pass

    fenced = _FENCE_RE.match(text.strip())
    if fenced:
        return fenced.group(1).strip()

    mention_ents = [
        e
        for e in entities
        if e.type in ("text_mention", "text_link", "mention", "url")
    ]
    if not mention_ents:
        return text.strip()

    mention_ents.sort(key=lambda e: e.offset)
    parts = []
    cursor = 0
    utf16_len = len(text.encode("utf-16-le")) // 2
    for ent in mention_ents:
        if ent.offset > cursor:
            parts.append(_utf16_slice(text, cursor, ent.offset - cursor))
        try:
            span = message.parse_entity(ent)
        except Exception:
            span = _utf16_slice(text, ent.offset, ent.length)
        if ent.type == "text_mention" and getattr(ent, "user", None):
            parts.append(f"[{span}](tg://user?id={ent.user.id})")
        elif ent.type == "text_link" and ent.url:
            parts.append(f"[{span}]({ent.url})")
        else:
            parts.append(span)
        cursor = ent.offset + ent.length
    if cursor < utf16_len:
        parts.append(_utf16_slice(text, cursor, utf16_len - cursor))
    return "".join(parts).strip()


def format_header_html(text: str) -> str:
    """Escape header text but keep Telegram mention links clickable/pinging."""
    if not text:
        return ""
    parts = []
    last = 0
    for match in _HEADER_MD_LINK.finditer(text):
        parts.append(html.escape(text[last : match.start()]))
        label = html.escape(match.group(1))
        user_id, domain, tme = match.group(2), match.group(3), match.group(4)
        if user_id:
            parts.append(f'<a href="tg://user?id={user_id}">{label}</a>')
        else:
            username = domain or tme
            # https://t.me/... is a URL, not a mention. @username notifies.
            parts.append(f"@{username}")
        last = match.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)


def day_long(lang, key):
    return DAYS_RU[key] if lang == "ru" else DAYS_EN[key]


def queue_markup(lang="en"):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(tr(lang, "btn_join"), callback_data="join"),
                InlineKeyboardButton(tr(lang, "btn_leave"), callback_data="leave"),
            ]
        ]
    )


def timer_markup(lang="en", running=False):
    label_toggle = tr(lang, "btn_timer_stop") if running else tr(lang, "btn_timer_start")
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("<< " + tr(lang, "btn_prev"), callback_data="timer_prev"),
                InlineKeyboardButton(label_toggle, callback_data="timer_toggle"),
                InlineKeyboardButton(tr(lang, "btn_next") + " >>", callback_data="timer_next"),
            ]
        ]
    )


def lang_markup(lang="en"):
    """Language selector buttons (shown by /lang and on the welcome)."""
    buttons = []
    for code in ("en", "ru"):
        label = "English" if code == "en" else "Русский"
        if code == lang:
            label += " [selected]"
        buttons.append(InlineKeyboardButton(label, callback_data=f"lang_{code}"))
    return InlineKeyboardMarkup([buttons])


def tz_markup():
    """Timezone picker buttons: curated zones, one per row."""
    rows = []
    for zone in CURATED_ZONES:
        tz = resolve_tz(zone)
        label = zone.replace("_", " ")
        if tz is not None:
            label += f" ({offset_label(tz)})"
        rows.append([InlineKeyboardButton(label, callback_data=f"tz_{zone}")])
    return InlineKeyboardMarkup(rows)


def setlesson_day_markup(lang="en"):
    """Weekday picker for /setlesson (two buttons per row)."""
    keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    rows = []
    row = []
    for key in keys:
        row.append(
            InlineKeyboardButton(
                day_long(lang, key), callback_data=f"setlesson_day_{key}"
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def lesson_days_markup(lang, lessons, prefix):
    """Day buttons only for configured lessons (e.g. before_day / duration_day)."""
    ordered = sorted(lessons, key=lambda l: DAY_INDEX.get(l["day_of_week"], 99))
    rows = []
    row = []
    for lesson in ordered:
        key = lesson["day_of_week"]
        label = f"{day_long(lang, key)} {lesson['lesson_time']}"
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}_{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def format_lesson_line(lesson, lang="en"):
    """One-line lesson summary, e.g. 'Monday 23:00 — opens 30 min before, accepts joins for 60 min'."""
    return (
        f"{day_long(lang, lesson['day_of_week'])} {lesson['lesson_time']} — "
        + tr(
            lang, "lesson_desc",
            ob=lesson["open_before_min"], lt=lesson["lifetime_min"],
        )
    )


def build_queue_text(lesson, session_date, entries, lang="en", closed=False):
    """HTML body: optional header note, then title/time, then the joined list with current marker <<."""
    title = tr(lang, "queue_title_closed" if closed else "queue_title")
    when = tr(lang, "queue_when", day=day_long(lang, lesson["day_of_week"]), time=lesson["lesson_time"])

    lines = []
    header = (lesson.get("header_text") or "").strip()
    if header:
        lines.append(format_header_html(header))
        lines.append("")
    lines.extend([title, when])
    if entries:
        lines.append("")
        # current speaker from active timer, if any
        current_index = None
        try:
            import db as _db
            t = _db.get_active_timer(lesson["chat_id"], lesson["lesson_id"], session_date)
            if t is not None:
                current_index = t.get("current_index")
        except Exception:
            current_index = None
        parts = []
        for i, e in enumerate(entries, 1):
            suffix = " &lt;&lt;" if current_index is not None and i - 1 == current_index else ""
            parts.append(f"<b>{i}.</b> {html.escape(e['display_name'])}{suffix}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


def build_timer_text(lesson, entries, current_index, remaining_seconds, running, lang="en"):
    """HTML body for timer message: only title and time left (no queue, no date, no status)."""
    title = tr(lang, "timer_title")
    mm = remaining_seconds // 60
    ss = remaining_seconds % 60
    # Lesson/date/queue/status explicitly removed per user request:
    # timer is standalone, queue is above, current marker is in queue message as <<.
    return f"{title}\n\n{tr(lang, 'timer_time_left', time=f'{mm:02d}:{ss:02d}')}"


def student_commands(lang="en"):
    return "\n".join(
        [
            "/queue - " + tr(lang, "student_queue"),
            "/leave - " + tr(lang, "student_leave"),
            "/setname - " + tr(lang, "student_setname"),
        ]
    )


def admin_commands(lang="en"):
    return "\n".join(
        [
            "/info - " + tr(lang, "student_info"),
            "/lang - " + tr(lang, "student_lang"),
            "/setlesson &lt;Day&gt; &lt;HH:MM&gt; - " + tr(lang, "admin_setlesson"),
            "/before &lt;min&gt; - " + tr(lang, "admin_before"),
            "/duration &lt;min&gt; - " + tr(lang, "admin_duration"),
            "/timer &lt;sec&gt; - " + tr(lang, "admin_timer"),
            "/delete &lt;Day&gt; - " + tr(lang, "admin_delete"),
            "/header - " + tr(lang, "admin_header"),
            "/tz - " + tr(lang, "admin_tz"),
            "/all - " + tr(lang, "admin_all"),
        ]
    )


def _lesson_block(lessons, lang="en"):
    if not lessons:
        return None
    lines = []
    for lesson in sorted(lessons, key=lambda x: (DAY_INDEX[x["day_of_week"]], x["lesson_time"])):
        lines.append(format_lesson_line(lesson, lang))
    return "\n".join(lines)


def build_info_text(lessons, is_admin=False, lang="en", zone=None, zone_label=""):
    """Language-aware /info: current settings + commands; admin section only for admins."""
    parts = []
    block = _lesson_block(lessons, lang=lang)
    header = tr(lang, "config_header")
    if zone:
        header += f" ({zone} {zone_label})"
    if block:
        parts.append(header + "\n" + block)
    else:
        parts.append(header + "\n" + tr(lang, "config_empty") + "\n\n" + tr(lang, "config_empty_hint"))
    parts.append(tr(lang, "commands_header") + "\n" + student_commands(lang))
    if is_admin:
        parts.append(tr(lang, "admin_header") + "\n" + admin_commands(lang))
    return "\n\n".join(parts)


def welcome_text(lang="en"):
    return tr(lang, "welcome_body")