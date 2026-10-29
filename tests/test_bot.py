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

    def send(self, text, char_delay_ms=0.0):
        self.sent.append(text)
        self.delays = getattr(self, "delays", []) + [char_delay_ms]


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


def test_quiet_hours_silent_then_resumes():
    from datetime import datetime

    from wabot.quiet import parse_quiet_hours

    clock = [datetime(2026, 10, 29, 2, 0)]
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, quiet=parse_quiet_hours("23:00-07:00"), now=lambda: clock[0])
    assert bot.step() is None and g.calls == []
    clock[0] = datetime(2026, 10, 29, 8, 0)
    assert bot.step() == "ok"


def test_typing_delay_passed_and_capped():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    make(c, g, char_delay_ms=70, max_typing_seconds=20).step()
    assert c.delays == [70]
    long = FakeGen()
    long.generate = lambda context, extra="": "x" * 1000
    c2 = FakeClient(msgs=[inc(1)])
    make(c2, long, char_delay_ms=70, max_typing_seconds=20).step()
    assert c2.delays == [20.0]


def test_no_typing_delay_by_default():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    make(c, g).step()
    assert c.delays == [0.0]


class FixedRng:
    def __init__(self, roll, minutes=10.0):
        self.roll, self.minutes = roll, minutes

    def random(self):
        return self.roll

    def uniform(self, a, b):
        return self.minutes


def at(seconds):
    from datetime import datetime, timedelta

    return datetime(2026, 10, 29, 12, 0) + timedelta(seconds=seconds)


def test_afk_blocks_replies_then_answers_without_rerolling():
    now = [0.0]
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, afk_chance=0.5, rng=FixedRng(0.1), now=lambda: at(now[0]))
    assert bot.step() is None  # rolled a hit: away for 10 minutes
    now[0] = 599
    assert bot.step() is None and g.calls == []
    now[0] = 601
    bot._rng = FixedRng(0.1)  # a new roll would hit again, but the same message is not re-rolled
    assert bot.step() == "ok"


def test_afk_new_message_rolls_again():
    now = [0.0]
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, afk_chance=0.5, rng=FixedRng(0.9), now=lambda: at(now[0]))
    assert bot.step() == "ok"
    c.msgs = [inc(1), Message("o", "Me", "ok", "ts", True), inc(2)]
    bot._rng = FixedRng(0.1)
    assert bot.step() is None
    assert bot._afk_until > at(now[0]).timestamp()


def test_afk_survives_restart(tmp_path):
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    path = tmp_path / "bot.db"
    with Store(path) as store:
        Bot(c, g, store, ("Budi",), afk_chance=0.5, rng=FixedRng(0.1), now=lambda: at(0)).step()
    with Store(path) as store:  # restart: new Bot, same database
        again = Bot(c, g, store, ("Budi",), afk_chance=0.5, rng=FixedRng(0.1), now=lambda: at(300))
        assert again.step() is None and g.calls == []  # still away at minute 5
        later = Bot(c, g, store, ("Budi",), afk_chance=0.5, rng=FixedRng(0.1), now=lambda: at(700))
        assert later.step() == "ok"  # spell over, same message not re-rolled


def test_afk_off_by_default():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    assert make(c, g, rng=FixedRng(0.0)).step() == "ok"


def test_no_chained_spell_after_message_sent_during_afk():
    now = [0.0]
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, afk_chance=0.5, rng=FixedRng(0.1, 10), now=lambda: at(now[0]))
    assert bot.step() is None  # spell starts
    c.msgs = [inc(1), inc(2)]  # sender writes again while we are away
    now[0] = 601
    assert bot.step() == "ok"  # the same rng would hit again, but the grace skips the roll
    assert len(g.calls) == 1


def test_roll_returns_after_grace_is_used():
    now = [0.0]
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, afk_chance=0.5, rng=FixedRng(0.1, 10), now=lambda: at(now[0]))
    bot.step()
    now[0] = 601
    assert bot.step() == "ok"  # grace
    c.msgs = [inc(1), Message("o", "Me", "ok", "ts", True), inc(3)]
    assert bot.step() is None  # the next message rolls normally and hits again


def ack_bot(minutes, **kw):
    now = [0.0]
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(
        c,
        g,
        afk_chance=0.5,
        rng=FixedRng(0.1, minutes),
        now=lambda: at(now[0]),
        afk_ack_min_minutes=5,
        **kw,
    )
    bot.step()
    now[0] = minutes * 60 + 1
    bot.step()
    return g


def test_acknowledgement_added_after_long_spell():
    g = ack_bot(12, afk_acknowledge=True)
    assert "about 12 minutes" in g.extras[0]


def test_no_acknowledgement_when_off_or_short():
    assert "away" not in ack_bot(12).extras[0]
    assert "away" not in ack_bot(3, afk_acknowledge=True).extras[0]


def test_hand_reply_during_spell_clears_flag():
    now = [0.0]
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, afk_chance=0.5, rng=FixedRng(0.1, 10), now=lambda: at(now[0]))
    bot.step()
    c.msgs = [inc(1), Message("mine", "Me", "bentar ya", "ts", True)]
    now[0] = 601
    assert bot.step() is None
    assert bot._store.get_state("afk_back") == ""
    assert g.calls == []


def test_backlog_skipped_on_start_but_new_messages_answered():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g, skip_backlog=True)
    assert bot.step() is None and g.calls == []  # waiting before start
    c.msgs = [inc(1), inc(2)]
    assert bot.step() == "ok"


def test_backlog_kept_when_spell_carried_over_restart(tmp_path):
    path = tmp_path / "bot.db"
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    with Store(path) as store:
        spell = Bot(c, g, store, ("Budi",), afk_chance=0.5, rng=FixedRng(0.1, 10))
        spell._now = lambda: at(0)
        spell.step()
    with Store(path) as store:
        bot = Bot(c, g, store, ("Budi",), skip_backlog=True, now=lambda: at(700))
        assert bot.step() == "ok"  # the waiting message belongs to the spell


def test_backlog_skip_off_answers_waiting_message():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    assert make(c, g, skip_backlog=False).step() == "ok"
