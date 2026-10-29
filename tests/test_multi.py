import logging
import random

from test_bot import FakeClient, FakeGen, ListClient, chat, inc, list_bot, make

from wabot.models import Message
from wabot.tone import FAMILY, LOVER

THREE = "Halo sayang 😘\n---\nUdah makan belum?\n---\nJangan lupa istirahat ya"


class RecordingClient(FakeClient):
    """Remembers every message sent and the typing plan used for each."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.sent_plans = []

    def send(self, text, plan=None):
        super().send(text, plan)
        self.sent_plans.append(plan)


def lover_bot(reply=THREE, tag="lover", msgs=None, **kw):
    slept = []
    gen = FakeGen()
    gen.reply = reply
    client = RecordingClient(msgs=msgs or [inc(1)])
    bot = make(
        client,
        gen,
        tags={"Budi": tag} if tag else None,
        rng=random.Random(3),
        sleep=slept.append,
        **kw,
    )
    return bot, client, gen, slept


def test_a_lover_reply_is_sent_as_several_messages_in_order():
    bot, client, gen, _ = lover_bot()
    assert bot.step() == THREE  # the full answer is still what step returns
    assert client.sent == ["Halo sayang 😘", "Udah makan belum?", "Jangan lupa istirahat ya"]
    assert len(gen.calls) == 1  # one API call for all three messages


def test_gemini_gets_the_tone_for_lover_and_family_only():
    for tag, tone in (("lover", LOVER), ("family", FAMILY)):
        bot, _, gen, _ = lover_bot(tag=tag)
        bot.step()
        assert gen.tones == [tone]
    bot, _, gen, _ = lover_bot(tag="friend")
    bot.step()
    assert gen.tones == [None]


def test_other_relationships_stay_one_message_even_if_gemini_adds_markers():
    bot, client, _, _ = lover_bot(tag="friend")
    bot.step()
    assert client.sent == [THREE]


def test_pause_between_messages_and_each_message_gets_its_own_typing_plan():
    bot, client, _, slept = lover_bot(char_delay_ms=200)
    bot.step()
    assert len(client.sent_plans) == 3 and all(p is not None for p in client.sent_plans)
    assert [len(p.char_delays_ms) for p in client.sent_plans] == [len(t) for t in client.sent]
    between = slept[1:]  # first sleep is reading plus thinking
    assert len(between) == 2 and all(1.2 <= s <= 3.5 for s in between)


def test_every_part_is_recorded_as_the_bots_own_so_voice_examples_stay_clean():
    bot, client, _, _ = lover_bot()
    bot.step()
    store = bot._store
    chat_id = store.chat_id("Budi")
    mine = [Message(f"out{i}", "Me", t, "ts", True) for i, t in enumerate(client.sent)]
    store.upsert_messages(chat_id, mine)
    assert store.own_examples(chat_id) == []


def test_marked_answered_after_the_first_part_so_a_failure_never_repeats_the_reply():
    bot, client, gen, _ = lover_bot()
    original = client.send
    calls = []

    def flaky(text, plan=None):
        calls.append(text)
        if len(calls) == 2:
            raise RuntimeError("browser died")
        original(text, plan)

    client.send = flaky
    try:
        bot.step()
    except RuntimeError:
        pass
    chat_id = bot._store.chat_id("Budi")
    assert bot._store.pending_incoming(chat_id) is None  # not answered twice later
    assert len(gen.calls) == 1


def test_hourly_cap_counts_the_reply_once_not_each_message():
    now = [0.0]
    bot, client, _, _ = lover_bot(max_replies_per_hour=1, clock=lambda: now[0])
    bot.step()
    assert len(client.sent) == 3
    assert len(bot._sent_at[bot._store.chat_id("Budi")]) == 1


def test_timeline_and_sent_lines_report_the_message_count(caplog):
    bot, _, _, _ = lover_bot()
    with caplog.at_level(logging.INFO):
        bot.step()
    lines = [r.getMessage() for r in caplog.records]
    assert any("in 3 message(s)" in m for m in lines)
    assert "Budi: sent 3 messages" in lines


def test_dry_run_lists_the_messages_without_sending(caplog):
    bot, client, _, slept = lover_bot(dry_run=True)
    with caplog.at_level(logging.INFO):
        bot.step()
    lines = [r.getMessage() for r in caplog.records]
    assert client.sent == [] and slept == []
    assert "  message 2 of 3: Udah makan belum?" in lines
    assert "Budi: dry run, nothing sent" in lines


def test_a_single_message_reply_still_logs_plain_sent(caplog):
    bot, client, _, _ = lover_bot(reply="Iya sayang, aku kabarin ya")
    with caplog.at_level(logging.INFO):
        bot.step()
    assert client.sent == ["Iya sayang, aku kabarin ya"]
    assert "Budi: sent" in [r.getMessage() for r in caplog.records]


# ---------------- queue priority


def waiting(tags):
    clients = ListClient(
        {
            "Teman": chat(1, inc(1)),
            "Ibu": chat(1, inc(2)),
            "Sayang": chat(1, inc(3)),
        }
    )
    bot = list_bot(
        clients, allow=("Teman", "Ibu", "Sayang"), tags=tags, reply_gap=(0, 0), debounce=False
    )
    return clients, bot


def test_lover_chat_is_answered_before_family_before_others():
    c, bot = waiting({"Ibu": "family", "Sayang": "lover", "Teman": "friend"})
    order = []
    for _ in range(3):
        bot.step()
    order = [title for title, _ in c.sent]
    assert order == ["Sayang", "Ibu", "Teman"]


def test_without_tags_the_oldest_waiting_chat_still_goes_first():
    c, bot = waiting({})
    bot.step()
    assert c.opened == ["Teman"]  # first seen, same rank for everyone
