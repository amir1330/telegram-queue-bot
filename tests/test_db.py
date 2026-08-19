"""Standalone smoke test for the db layer. No Telegram required.

Run: python tests/test_db.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = ""

import db

DAY = "mon"
TIME = "23:00"
SDATE = "2026-08-13"


def check(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"ok: {label}")


def main():
    tmp = tempfile.mkdtemp()
    db._DB_PATH = os.path.join(tmp, "test.db")
    db.close()
    db.init_db()

    chat_id = 12345
    db.add_chat(chat_id, "Test Group")
    check("lang defaults to ru", db.get_chat_lang(chat_id) == "ru")
    check("timezone defaults to Almaty", db.get_chat_timezone(chat_id) == "Asia/Almaty")
    check("get_all_chat_ids", db.get_all_chat_ids() == [chat_id])
    db.set_chat_lang(chat_id, "en")
    check("lang set to en", db.get_chat_lang(chat_id) == "en")
    check("lang default for unknown chat", db.get_chat_lang(999) == "ru")

    lesson = db.add_lesson(chat_id, DAY, TIME, open_before_min=30, lifetime_min=120)
    check("add_lesson returns lesson", lesson and lesson["chat_id"] == chat_id)
    check("defaults applied", lesson["open_before_min"] == 30 and lesson["lifetime_min"] == 120)

    db.add_lesson(chat_id, DAY, "10:00", open_before_min=15, lifetime_min=45)
    lessons = db.get_lessons(chat_id)
    check("get_lessons returns all", len(lessons) == 1 and lessons[0]["lesson_time"] == "10:00")
    check("upsert updated time", lessons[0]["lesson_time"] == "10:00")
    check(
        "upsert preserves windows",
        lessons[0]["open_before_min"] == 30 and lessons[0]["lifetime_min"] == 120,
    )

    updated = db.update_lesson_window(lesson["lesson_id"], open_before_min=45)
    check("update_lesson_window", updated["open_before_min"] == 45)

    db.set_last_lesson(chat_id, lesson["lesson_id"])
    check("get_last_lesson", db.get_last_lesson(chat_id)["lesson_id"] == lesson["lesson_id"])

    e1 = db.add_queue_entry(chat_id, lesson["lesson_id"], 111, "Amir", SDATE)
    e2 = db.add_queue_entry(chat_id, lesson["lesson_id"], 222, "Damir", SDATE)
    check("two entries added", e1 and e2)
    check("duplicate rejected", db.add_queue_entry(chat_id, lesson["lesson_id"], 111, "Amir", SDATE) is None)
    check("position_of", db.position_of(chat_id, lesson["lesson_id"], SDATE, 222) == 2)

    q = db.get_queue(chat_id, lesson["lesson_id"], SDATE)
    check("queue order", [x["display_name"] for x in q] == ["Amir", "Damir"])

    db.remove_queue_entry(chat_id, lesson["lesson_id"], 111, SDATE)
    q = db.get_queue(chat_id, lesson["lesson_id"], SDATE)
    check("leave shifts up", [x["display_name"] for x in q] == ["Damir"])

    db.save_active_message(chat_id, lesson["lesson_id"], SDATE, 777, "open")
    check("active message saved", db.get_active_message(chat_id, lesson["lesson_id"], SDATE)["message_id"] == 777)
    db.mark_active_closed(chat_id, lesson["lesson_id"], SDATE)
    check("mark closed", db.get_active_message(chat_id, lesson["lesson_id"], SDATE)["status"] == "closed")
    db.delete_active_message(chat_id, lesson["lesson_id"], SDATE)
    check("active message deleted", db.get_active_message(chat_id, lesson["lesson_id"], SDATE) is None)

    db.clear_queue(chat_id, lesson["lesson_id"], SDATE)
    check("clear_queue", db.get_queue(chat_id, lesson["lesson_id"], SDATE) == [])

    removed = db.remove_lesson(chat_id, DAY)
    check("remove_lesson", removed == lesson["lesson_id"])
    check("get_lessons empty", db.get_lessons(chat_id) == [])

    check("get_all_lessons", db.get_all_lessons() == [])

    db.close()
    print("\nAll db smoke tests passed.")


if __name__ == "__main__":
    main()