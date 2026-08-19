"""HTML message builders and inline keyboards for the queue bot."""

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from i18n import tr
from queue_view import DAY_INDEX, DAYS_EN, DAYS_RU
from timezone import CURATED_ZONES, offset_label, resolve_tz


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
    """HTML body for the pinned queue message: title, time, and the joined list."""
    title = tr(lang, "queue_title_closed" if closed else "queue_title")
    when = tr(lang, "queue_when", day=day_long(lang, lesson["day_of_week"]), time=lesson["lesson_time"])

    lines = [
        title,
        when,
    ]
    if entries:
        lines.append("")
        lines.append(
            "\n".join(
                f"<b>{i}.</b> {html.escape(e['display_name'])}"
                for i, e in enumerate(entries, 1)
            )
        )
    return "\n".join(lines)


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
            "/delete &lt;Day&gt; - " + tr(lang, "admin_delete"),
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