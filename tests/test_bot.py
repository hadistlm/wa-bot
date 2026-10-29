import pytest

from wabot.bot import Bot
from wabot.llm import FatalReplyError, ReplyError
from wabot.models import Message
from wabot.store import Store


class FakeClient:
    def __init__(self, title="Budi", group=False, msgs=()):
        self.title, self.group, self.msgs, self.sent = title, group, list(msgs), []

    def active_chat(self):
        return (self.title, self.group)

    def read_messages(self):
        return self.msgs

    def send(self, text):
        self.sent.append(text)


class FakeGen:
    def __init__(self, exc=None):
        self.exc, self.calls = exc, []

    def generate(self, context, extra=""):
        self.calls.append(list(context))
        self.extras = getattr(self, "extras", []) + [extra]
        if self.exc:
            raise self.exc
        return "ok"


def inc(i):
    return Message(f"id{i}", "Budi", f"m{i}", "ts", False)


def make(client, gen, allow=("Budi",), **kw):
    return Bot(client, gen, Store(":memory:"), allow, **kw)


def test_replies_once():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g)
    assert bot.step() == "ok"
    assert bot.step() is None
    assert c.sent == ["ok"] and len(g.calls) == 1


def test_context_limited():
    c, g = FakeClient(msgs=[inc(i) for i in range(8)]), FakeGen()
    make(c, g, context_messages=5).step()
    assert [m.wa_id for m in g.calls[0]] == [f"id{i}" for i in range(3, 8)]


def test_not_allowed_and_groups_skipped():
    g = FakeGen()
    assert make(FakeClient(title="Eve", msgs=[inc(1)]), g).step() is None
    assert make(FakeClient(group=True, msgs=[inc(1)]), g).step() is None
    assert make(FakeClient(msgs=[inc(1)]), g, allow=()).step() is None
    assert g.calls == []


def test_outgoing_last_no_reply():
    out = Message("id9", "Me", "yo", "ts", True)
    assert make(FakeClient(msgs=[inc(1), out]), FakeGen()).step() is None


def test_dry_run_sends_nothing_and_not_repeated():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, dry_run=True)
    assert bot.step() == "ok"
    assert bot.step() is None
    assert c.sent == [] and len(g.calls) == 1


def test_retryable_error_recorded_then_retried():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen(ReplyError("boom"))
    bot = make(c, g)
    assert bot.step() is None
    assert bot.step() is None
    assert len(g.calls) == 2 and c.sent == []


def test_fatal_propagates():
    with pytest.raises(FatalReplyError):
        make(FakeClient(msgs=[inc(1)]), FakeGen(FatalReplyError("x"))).step()


def test_trivial_message_skipped_and_not_repeated():
    c, g = FakeClient(msgs=[Message("id1", "Budi", "ok 👍", "ts", False)]), FakeGen()
    bot = make(c, g, skip_trivial=True)
    assert bot.step() is None
    assert bot.step() is None
    assert g.calls == [] and c.sent == []


def test_debounce_waits_one_poll_and_restarts_on_new_message():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, debounce=True)
    assert bot.step() is None
    c.msgs = [inc(1), inc(2)]
    assert bot.step() is None
    assert bot.step() == "ok"
    assert len(g.calls) == 1


def test_rate_cap():
    now = [0.0]
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, max_replies_per_hour=1, clock=lambda: now[0])
    assert bot.step() == "ok"
    c.msgs = [inc(1), inc(2)]
    assert bot.step() is None
    now[0] = 3601
    assert bot.step() == "ok"


def test_profile_block_and_own_examples_reach_model():
    work = [
        Message(f"w{i}", "Budi", "Dear team, please update the meeting. Regards", "ts", False)
        for i in range(5)
    ]
    mine = Message("m1", "Me", "Siap, saya cek dulu ya", "ts", True)
    c, g = FakeClient(msgs=[*work[:2], mine, *work[2:]]), FakeGen()
    bot = make(c, g, tags={"Budi": "work"})
    bot.step()
    extra = g.extras[0]
    assert "work contact" in extra and "mostly English" in extra
    assert "Siap, saya cek dulu ya" in extra


def test_bot_reply_not_used_as_own_example():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    store = Store(":memory:")
    bot = Bot(c, g, store, ("Budi",))
    bot.step()
    chat_id = store.chat_id("Budi")
    c.msgs = [inc(1), Message("out1", "Me", "ok", "ts", True)]
    store.upsert_messages(chat_id, c.msgs)
    assert store.own_examples(chat_id) == []
