"""Wizard + single-line /setask simulation. No Telegram required.

Drives the real handlers with fake updates two ways:
  privacy ON  -> every free-text answer is a REPLY to the bot prompt
                (the only shape a privacy-mode bot ever sees);
  privacy OFF -> bare typed answers (no reply_to).
Asserts the draft confirm, Save/Cancel, DB rows, cron registration,
per-step cleanup, and the new poll card render (12+ names, escaping).

Run: venv/bin/python tests/test_ask_wizard.py
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = ""

import db

_MID = [1000]


def _next_mid():
    _MID[0] += 1
    return _MID[0]


class FakeChat:
    id = -100555
    title = "Wizard Group"
    type = "supergroup"


class FakeUser:
    def __init__(self, uid=724167515, admin=True):
        self.id = uid
        self.first_name = "Amir"
        self.username = "amir"
        self.is_admin = admin


ADMIN = FakeUser()


class FakeBot:
    def __init__(self):
        self.deleted = []

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)

    async def send_message(self, **kwargs):
        m = FakeMessage(text=kwargs.get("text", ""))
        return m


class FakeMessage:
    def __init__(self, text="", reply_to=None):
        self.text = text
        self.message_id = _next_mid()
        self.chat_id = FakeChat.id
        self.reply_to_message = reply_to
        self.chat = FakeChat()
        self.deleted = False

    async def reply_text(self, text, **kwargs):
        m = FakeMessage(text=text)
        SENT.append(text)
        return m

    async def delete(self):
        self.deleted = True

    async def edit_message_text(self, text, **kwargs):
        self.text = text

    async def edit_message_reply_markup(self, reply_markup=None):
        pass


class FakeQuery:
    def __init__(self, data, message, user=ADMIN):
        self.data = data
        self.message = message
        self.from_user = user
        self.answered = None

    async def answer(self, text=None, **kwargs):
        self.answered = text

    async def edit_message_text(self, text, **kwargs):
        self.message.text = text

    async def edit_message_reply_markup(self, reply_markup=None):
        pass


class FakeUpdate:
    def __init__(self, message=None, query=None, user=ADMIN):
        self.effective_chat = FakeChat()
        self.effective_user = user
        self.callback_query = query
        self.effective_message = message if message is not None else (
            query.message if query is not None else None)

    def get_bot(self):
        return FakeBot()


class FakeCtx:
    def __init__(self, sched, args=None):
        self.args = args or []
        self.bot = FakeBot()
        self.bot_data = {"scheduler": sched}


class FakeScheduler:
    def __init__(self):
        self.asks = []

    def schedule_ask(self, ask):
        self.asks.append(ask["id"])


SENT = []


def check(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"ok: {label}")


def _patch_admin():
    import handlers.ask_handlers as askh
    import handlers.helpers as helpers

    async def fake_is_admin(update, chat_id, user_id):
        u = update.effective_user
        return bool(getattr(u, "is_admin", True))

    async def fake_require_group(update, context):
        return True

    async def fake_cleanup(update, context, seconds=5):
        return None

    async def fake_schedule_delete(bot, chat_id, message_id, seconds=30):
        return None

    helpers.is_admin = fake_is_admin
    helpers.cleanup_trigger = fake_cleanup
    helpers.schedule_delete = fake_schedule_delete
    askh.is_admin = fake_is_admin
    askh.require_group = fake_require_group
    askh.schedule_delete = fake_schedule_delete
    import handlers.param_prompt as pp
    pp.cleanup_trigger = fake_cleanup
    return askh


async def _run_wizard(askh, sched, reply_mode):
    """reply_mode='reply' (privacy ON) or 'bare' (privacy OFF). Returns ask id."""
    from handlers.param_reply import on_param_reply

    day_msg = FakeMessage(text="day buttons")
    q = FakeQuery("setask_day_mon", day_msg)
    await askh.cb_setask_day(FakeUpdate(query=q), FakeCtx(sched))
    pending = db.get_param_pending(FakeChat.id, ADMIN.id)
    check(f"[{reply_mode}] time prompt pending", pending and pending["command"] == "setask_time")
    prompt_id = pending["prompt_message_id"]

    async def answer(text, to_prompt=True):
        parent = FakeMessage(text="prompt")
        parent.message_id = to_prompt and prompt_id or 1
        msg = FakeMessage(text=text, reply_to=parent if to_prompt else None)
        await on_param_reply(FakeUpdate(message=msg), FakeCtx(sched))
        p = db.get_param_pending(FakeChat.id, ADMIN.id)
        return p["prompt_message_id"] if p else None, p

    to_prompt = reply_mode == "reply"
    prompt_id, p = await answer("18:00", to_prompt)
    check(f"[{reply_mode}] question prompt pending", p and p["command"] == "setask_question")
    prompt_id, p = await answer("Ты придёшь?", to_prompt)
    check(f"[{reply_mode}] options prompt pending", p and p["command"] == "setask_options")
    prompt_id, p = await answer("Да\nНет\n?Есть причина", to_prompt)
    check(f"[{reply_mode}] confirm pending", p and p["command"] == "setask_confirm")
    draft = json.loads(p["payload"])
    check(f"[{reply_mode}] draft has 3 options", len(draft["options"]) == 3)
    check(f"[{reply_mode}] draft reason flag", draft["options"][2] == ["Есть причина", True])

    confirm_msg = FakeMessage(text="confirm")
    confirm_msg.message_id = p["prompt_message_id"]
    q2 = FakeQuery("ask_save", confirm_msg)
    await askh.cb_ask_confirm(FakeUpdate(query=q2), FakeCtx(sched))
    check(f"[{reply_mode}] pending cleared after save",
          db.get_param_pending(FakeChat.id, ADMIN.id) is None)
    asks = db.get_asks(FakeChat.id)
    check(f"[{reply_mode}] ask saved", len(asks) == 1)
    return asks[0]["id"]


async def main():
    askh = _patch_admin()
    tmp = tempfile.mkdtemp()
    db._DB_PATH = os.path.join(tmp, "wiz.db")
    db.close()
    db.init_db()

    # 1. privacy ON: replies only
    sched = FakeScheduler()
    ask_id = await _run_wizard(askh, sched, "reply")
    check("privacy-ON wizard scheduled cron", sched.asks == [ask_id])

    # 2. cancel path
    from handlers.param_reply import on_param_reply
    day_msg = FakeMessage(text="day buttons")
    await askh.cb_setask_day(FakeUpdate(query=FakeQuery("setask_day_tue", day_msg)),
                             FakeCtx(sched))
    p = db.get_param_pending(FakeChat.id, ADMIN.id)
    parent = FakeMessage(text="prompt")
    parent.message_id = p["prompt_message_id"]
    await on_param_reply(
        FakeUpdate(message=FakeMessage(text="19:00", reply_to=parent)), FakeCtx(sched))
    p = db.get_param_pending(FakeChat.id, ADMIN.id)
    parent.message_id = p["prompt_message_id"]
    await on_param_reply(
        FakeUpdate(message=FakeMessage(text="Q?", reply_to=parent)), FakeCtx(sched))
    p = db.get_param_pending(FakeChat.id, ADMIN.id)
    parent.message_id = p["prompt_message_id"]
    await on_param_reply(
        FakeUpdate(message=FakeMessage(text="A\nB", reply_to=parent)), FakeCtx(sched))
    p = db.get_param_pending(FakeChat.id, ADMIN.id)
    cm = FakeMessage(text="confirm")
    cm.message_id = p["prompt_message_id"]
    await askh.cb_ask_confirm(FakeUpdate(query=FakeQuery("ask_cancel", cm)), FakeCtx(sched))
    check("cancel saves nothing", len(db.get_asks(FakeChat.id)) == 1)

    # 3. privacy OFF: bare typed answers
    db.clear_param_pending(FakeChat.id, ADMIN.id)
    for a in db.get_asks(FakeChat.id):
        db.delete_ask(FakeChat.id, a["id"])
    sched2 = FakeScheduler()
    ask_id2 = await _run_wizard(askh, sched2, "bare")
    check("privacy-OFF wizard works too", sched2.asks == [ask_id2])

    # 4. single-line form untouched
    ctx = FakeCtx(sched2)
    ctx.args = ["Wednesday", "12:00", "|", "Q2?", "|", "Y", "|", "N"]
    upd = FakeUpdate(message=FakeMessage(text="/setask ..."))
    await askh.cmd_setask(upd, ctx)
    check("single-line still works", len(db.get_asks(FakeChat.id)) == 2)

    # 5. render demo: 12+ names, reasons, escaping, closed variant
    from message_builder import build_ask_text
    opts = [{"position": 0, "label": "Да", "needs_reason": 0},
            {"position": 1, "label": "Нет", "needs_reason": 0},
            {"position": 2, "label": "Есть причина", "needs_reason": 1}]
    names = {i: f"Student{i}" for i in range(1, 14)}
    names[99] = "<b>Alice & Bob</b>"
    resp = [{"option_id": 0, "user_id": i, "reason": None} for i in range(1, 13)]
    resp += [{"option_id": 2, "user_id": 99, "reason": "<script>x</script>"}]
    import time as _t
    card = build_ask_text("Ты придёшь?", opts, resp, names, closed=False,
                          closes_at=_t.time() + 3600, chat_id=FakeChat.id, lang="ru")
    print("---- RENDER (open) ----")
    print(card)
    print("-----------------------")
    check("12 names truncated", "+2 ещё" in card)
    check("names escaped", "&lt;b&gt;Alice &amp; Bob&lt;/b&gt;" in card)
    check("reason escaped+italic", "<i>&lt;script&gt;x&lt;/script&gt;</i>" in card)
    check("zero-total option steady", "Нет</b> — 0" in card and "—\n" in card)
    check("open-until line", "Открыто до" in card)
    closed_card = build_ask_text("Q?", opts, resp[:1], names, closed=True, lang="en")
    check("closed line + no buttons text", "Closed" in closed_card and "Total answered: 1" in closed_card)

    print("\nAll wizard/render checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
