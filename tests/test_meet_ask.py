"""Smoke tests for meet sessions, asks, JWT shape, and parsers. No Telegram needed.

Run: venv/bin/python tests/test_meet_ask.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = ""
os.environ["JITSI_DOMAIN"] = "meet.example.com"
os.environ["JITSI_JWT_SECRET"] = "test-secret-for-smoke-only"

import db
import jitsi
from handlers.ask_handlers import parse_ask_options, parse_setask_full


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
    chat_id = 777

    # --- meet sessions: one blocking session per chat ---
    check("no blocking session at first", db.get_blocking_meet_session(chat_id) is None)
    s1 = db.create_meet_session(chat_id, "lesson-abcdef12", 111, time.time() + 300)
    check("create returns open session", s1["state"] == "open" and s1["room"] == "lesson-abcdef12")
    check("lookup by id", db.get_meet_session(s1["id"])["chat_id"] == chat_id)
    check("second /meet blocked", db.get_blocking_meet_session(chat_id)["id"] == s1["id"])
    db.set_meet_session_message(s1["id"], 4242)
    check("message stored", db.get_meet_session(s1["id"])["message_id"] == 4242)
    db.set_meet_session_state(s1["id"], "closed")
    check("/meet free again after close", db.get_blocking_meet_session(chat_id) is None)
    s2 = db.create_meet_session(chat_id, "lesson-xyz", 111, time.time() + 300)
    check("restore sees open sessions", any(r["id"] == s2["id"] for r in db.get_open_meet_sessions()))
    db.set_meet_session_state(s2["id"], "active")
    check("active still blocks /meet", db.get_blocking_meet_session(chat_id)["id"] == s2["id"])
    db.set_meet_session_state(s2["id"], "closed")

    # --- room names ---
    room = jitsi.new_room_name("lesson-")
    check("room prefix", room.startswith("lesson-"))
    check("room charset", all(c.islower() or c.isdigit() or c in "-_." for c in room))
    check("sanitize keeps safe names", jitsi.sanitize_room_name("My Lesson 1") == "my-lesson-1")
    check("sanitize falls back", jitsi.sanitize_room_name("!!!").startswith("room-"))

    # --- JWT shape (HS256, aud/iss/sub/room/exp/context) ---
    token = jitsi.make_jwt("lesson-abc", 42, "Ali", True, time.time() + 300)
    import jwt as pyjwt
    payload = pyjwt.decode(
        token, "test-secret-for-smoke-only", algorithms=["HS256"], audience="jitsi",
        options={"require": ["aud", "iss", "sub", "room", "exp"]},
    )
    check("jwt aud", payload["aud"] == "jitsi")
    check("jwt iss", payload["iss"] == "lessons")
    check("jwt sub is XMPP domain", payload["sub"] == "meet.jitsi")
    check("jwt room bound", payload["room"] == "lesson-abc")
    check("jwt moderator", payload["context"]["user"]["moderator"] is True)
    check("jwt user", payload["context"]["user"]["id"] == "42")
    guest = jitsi.make_jwt("lesson-abc", 43, "Dana", False, time.time() + 300)
    guest_payload = pyjwt.decode(guest, "test-secret-for-smoke-only", algorithms=["HS256"], audience="jitsi")
    check("guest not moderator", guest_payload["context"]["user"]["moderator"] is False)

    # --- ask option syntax ---
    opts = parse_ask_options("Yes | No | ?I have a reason")
    check("options parsed", [o[0] for o in opts] == ["Yes", "No", "I have a reason"])
    check("needs_reason flag", [o[1] for o in opts] == [False, False, True])

    # --- full /setask form ---
    parsed = parse_setask_full("Monday 12:00 | Are you coming Mon 18:00? | Yes | No | ?Why not")
    check("setask parsed", parsed is not None)
    day, tm, question, options = parsed
    check("setask day/time", day == "mon" and tm == "12:00")
    check("setask question", question.startswith("Are you coming"))
    check("setask options", len(options) == 3 and options[2][1] is True)
    check("setask rejects one option", parse_setask_full("Monday 12:00 | Q? | Only") is None)
    check("setask rejects bad day", parse_setask_full("Funday 12:00 | Q? | A | B") is None)

    # --- asks CRUD + responses ---
    ask = db.create_ask(chat_id, "mon", "12:00", "Are you coming?")
    db.set_ask_options(ask["id"], [("Yes", False), ("No", False), ("Why not", True)])
    check("ask created", ask["duration_min"] == db.ASK_DEFAULT_DURATION_MIN)
    check("options stored", len(db.get_ask_options(ask["id"])) == 3)
    check("asks listed", len(db.get_asks(chat_id)) == 1)
    updated = db.set_ask_duration(chat_id, ask["id"], 60)
    check("duration updated", updated["duration_min"] == 60)
    sess = db.create_ask_session(ask["id"], chat_id, "2026-09-22", time.time() + 3600)
    check("session open", sess["state"] == "open")
    db.save_ask_response(sess["id"], 111, 0, None)
    db.save_ask_response(sess["id"], 222, 2, "dentist")
    check("responses saved", len(db.get_ask_responses(sess["id"])) == 2)
    check("reason stored", db.get_ask_response(sess["id"], 222)["reason"] == "dentist")
    db.save_ask_response(sess["id"], 111, 1, None)  # change answer
    check("answer changed", db.get_ask_response(sess["id"], 111)["option_id"] == 1)
    db.delete_ask_response(sess["id"], 111)  # retract
    check("answer retracted", db.get_ask_response(sess["id"], 111) is None)
    db.set_ask_session_state(sess["id"], "closed")
    check("restore skips closed", all(r["id"] != sess["id"] for r in db.get_open_ask_sessions()))
    check("delete ask", db.delete_ask(chat_id, ask["id"]) is True)
    check("asks empty", db.get_asks(chat_id) == [])

    db.close()
    print("\nAll meet/ask smoke tests passed.")


if __name__ == "__main__":
    main()
