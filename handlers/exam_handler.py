"""Exam result message generator (/exam)."""

import json
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db
from handlers.helpers import is_admin, reply_ephemeral, require_group
from handlers.param_prompt import start_param_prompt
from i18n import tr
from timezone import chat_now

logger = logging.getLogger(__name__)

EXAM_TYPE_JUZ = "juz"
EXAM_TYPE_HIZB = "hizb"

EXAM_SECTIONS = {
    EXAM_TYPE_JUZ: [
        "جزء عم",
        "جزء تبارك",
        "جزء قد سمع الله",
    ],
    EXAM_TYPE_HIZB: [
        "حزب الأعلى",
        "حزب عم",
        "حزب الجن",
        "حزب تبارك",
        "حزب جمعة",
        "حزب قد سمع الله",
        "حزب الرحمن",
    ],
}

_EASTERN_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def to_eastern_digits(text: str) -> str:
    """Convert Western digits to Eastern Arabic digits."""
    return text.translate(_EASTERN_DIGITS)


def grade_text(score: int):
    """Return (arabic_grade, russian_grade) for a 0-100 score.

    Below 70 the grade text is intentionally empty.
    """
    if score >= 95:
        return "ممتاز جداً", "Отлично"
    if score >= 90:
        return "ممتاز", "Отлично"
    if score >= 80:
        return "جيد جداً", "очень хорошо"
    if score >= 70:
        return "جيد", "хорошо"
    return "", ""


def build_exam_text(section: str, name: str, score: int, date_str: str) -> str:
    """Build the exam result card exactly in the requested mixed format."""
    arabic_score = to_eastern_digits(str(score))
    arabic_total = to_eastern_digits("100")
    grade_ar, grade_ru = grade_text(score)
    lines = [
        "🛑🛑🛑Результат экзамена:",
        "",
        f"التريخ: Дата {date_str}",
        "",
        "نتيجة الإختبار",
        "",
        " Имя студента ",
        "",
        f"إسم الطالب: {name} ",
        "",
        " Промежуток الكمية:",
        "",
        f"{section} ",
        "",
        "Оценка",
        "",
        "التقدير:",
        "",
        f"{arabic_score} من {arabic_total} ٪؜ {grade_ar} ",
        "",
        f" {grade_ru}",
        "",
        name,
    ]
    return "\n".join(lines)


def exam_type_markup():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("джуз", callback_data="exam_type_juz"),
                InlineKeyboardButton("хизб", callback_data="exam_type_hizb"),
            ]
        ]
    )


def exam_section_markup(section_type: str):
    sections = EXAM_SECTIONS.get(section_type, [])
    rows = [
        [InlineKeyboardButton(s, callback_data=f"exam_section_{s}")]
        for s in sections
    ]
    return InlineKeyboardMarkup(rows)


async def cmd_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin starts the exam-result wizard."""
    chat = update.effective_chat
    user = update.effective_user
    if not await require_group(update, context):
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await reply_ephemeral(update, context, tr(lang, "admin_only"))
        return
    await update.effective_message.reply_text(
        "Выберите тип экзамена:",
        reply_markup=exam_type_markup(),
    )


async def cb_exam_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin picked جُزْء / حزب."""
    query = update.callback_query
    chat = query.message.chat if query.message else None
    user = query.from_user
    if not chat or not user:
        await query.answer()
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await query.answer(text=tr(lang, "toast_admins_only"), show_alert=True)
        return
    section_type = (query.data or "").removeprefix("exam_type_")
    if section_type not in EXAM_SECTIONS:
        await query.answer()
        return
    await query.answer()
    try:
        await query.edit_message_text(
            "Выберите раздел:",
            reply_markup=exam_section_markup(section_type),
        )
    except Exception as exc:
        logger.debug("cb_exam_type: edit failed: %s", exc)


async def cb_exam_section(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin picked the specific section; prompt for student name."""
    query = update.callback_query
    chat = query.message.chat if query.message else None
    user = query.from_user
    if not chat or not user:
        await query.answer()
        return
    lang = db.get_chat_lang(chat.id)
    if not await is_admin(update, chat.id, user.id):
        await query.answer(text=tr(lang, "toast_admins_only"), show_alert=True)
        return
    section = (query.data or "").removeprefix("exam_section_")
    if not section:
        await query.answer()
        return
    await query.answer()
    try:
        await query.edit_message_text(f"Выбран раздел: {section}")
    except Exception as exc:
        logger.debug("cb_exam_section: edit failed: %s", exc)
    payload = json.dumps({"section": section, "step": "name"})
    await start_param_prompt(
        update,
        context,
        "exam_name",
        "Напишите имя студента:",
        payload=payload,
    )


async def apply_exam_name(update: Update, context: ContextTypes.DEFAULT_TYPE, payload_raw=None) -> bool:
    """Store the student name and ask for the numeric grade."""
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if not chat or not user or not message:
        return False
    data = _wizard_payload(payload_raw)
    if not data.get("section"):
        return False
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        await reply_ephemeral(update, context, "Имя не может быть пустым или слишком длинным.")
        return False
    data["name"] = name
    data["step"] = "grade"
    await start_param_prompt(
        update,
        context,
        "exam_grade",
        "Напишите оценку цифрами (0-100):",
        payload=json.dumps(data),
    )
    return True


async def apply_exam_grade(update: Update, context: ContextTypes.DEFAULT_TYPE, payload_raw=None) -> bool:
    """Validate grade, build and post the exam result card."""
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if not chat or not user or not message:
        return False
    data = _wizard_payload(payload_raw)
    section = data.get("section")
    name = data.get("name")
    if not section or not name:
        return False
    text = (message.text or "").strip()
    if not text.isdigit():
        await reply_ephemeral(update, context, "Введите оценку цифрами.")
        return False
    score = int(text)
    if not (0 <= score <= 100):
        await reply_ephemeral(update, context, "Оценка должна быть от 0 до 100.")
        return False
    date_str = chat_now(chat.id).strftime("%d.%m.%Y")
    result_text = build_exam_text(section, name, score, date_str)
    await context.bot.send_message(chat_id=chat.id, text=result_text)
    return True


def _wizard_payload(raw):
    try:
        data = json.loads(raw or "")
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}
