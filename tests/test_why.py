import logging

from test_bot import ListClient, chat, inc, list_bot

from wabot.matching import allow_label
from wabot.models import Message


def info(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]


def test_allow_label_names_the_rule_and_tag():
    tags = {"Sari": "lover"}
    assert allow_label("Sari ♥", ["Sari"], tags) == "allowed (name), lover"
    assert allow_label("Rudi", ["Sari"], tags) == "not allowed"
    assert allow_label("Anyone", [], {}) == "not allowed"
    assert allow_label("Pak Santoso", ["*santoso*"], {}) == "allowed (glob)"


def test_not_allowed_unread_chat_is_explained_once(caplog):
    c = ListClient({"Eve": chat(2, inc(1))})
    bot = list_bot(c)
    with caplog.at_level(logging.INFO):
        for _ in range(4):
            bot.step()
    lines = [line for line in info(caplog) if "Eve" in line]
    assert lines == ["Eve: unread, not in ALLOWED_CHATS, ignoring"]


def test_every_poll_is_logged_in_debug(caplog):
    c = ListClient({"Eve": chat(2, inc(1))})
    bot = list_bot(c)
    with caplog.at_level(logging.DEBUG):
        bot.step()
        bot.step()
    assert sum("Eve: unread, not in ALLOWED_CHATS" in r.getMessage() for r in caplog.records) == 2
    assert any("poll: 1 chats, 1 unread, 0 allowed" in r.getMessage() for r in caplog.records)


def test_backlog_and_debounce_reasons(caplog):
    c = ListClient({"Budi": chat(2, inc(1))})
    bot = list_bot(c, skip_backlog=True, debounce=True)
    with caplog.at_level(logging.INFO):
        bot.step()
        c.chats["Budi"] = chat(3, inc(1), inc(2))
        bot.step()
    messages = info(caplog)
    assert "Budi: was waiting before start, ignoring until a new message (SKIP_BACKLOG)" in messages
    assert "Budi: new messages, waiting one poll to see if more arrive" in messages


def test_opening_is_logged_with_the_unread_count(caplog):
    c = ListClient({"Budi": chat(3, inc(1))})
    with caplog.at_level(logging.INFO):
        list_bot(c).step()
    assert "Budi: opening chat (3 unread)" in info(caplog)


def test_reply_gap_is_explained(caplog):
    now = [0.0]
    c = ListClient({"Budi": chat(1, inc(1)), "Ani": chat(1, inc(2))})
    bot = list_bot(c, allow=("Budi", "Ani"), reply_gap=(30, 30), clock=lambda: now[0])
    bot.step()
    with caplog.at_level(logging.INFO):
        now[0] = 5
        bot.step()
    assert "Ani: waiting for the reply gap so two chats are not answered together" in info(caplog)


def test_reason_is_logged_again_after_the_chat_is_read(caplog):
    c = ListClient({"Eve": chat(2, inc(1))})
    bot = list_bot(c)
    with caplog.at_level(logging.INFO):
        bot.step()
        c.chats["Eve"]["unread"] = 0
        bot.step()
        c.chats["Eve"]["unread"] = 1
        bot.step()
    assert len([line for line in info(caplog) if line.startswith("Eve:")]) == 2


def test_afk_pause_and_end_are_logged(caplog):
    from datetime import datetime, timedelta

    from test_bot import FixedRng

    t0 = datetime(2026, 10, 29, 12, 0)
    now = [t0]
    c = ListClient({"Budi": chat(1, inc(1))})
    bot = list_bot(c, afk_chance=0.5, rng=FixedRng(0.1, 10), now=lambda: now[0])
    with caplog.at_level(logging.INFO):
        bot.step()  # rolls AFK
        bot.step()  # now paused
        now[0] = t0 + timedelta(minutes=11)
        bot.step()
    messages = info(caplog)
    assert any(m.startswith("paused until 12:10") for m in messages)
    assert "AFK spell ended, watching again" in messages


def test_heartbeat_appears_after_the_interval_not_before(caplog):
    now = [0.0]
    c = ListClient({"Budi": chat(0, inc(1)), "Eve": chat(2, inc(2))})
    bot = list_bot(c, heartbeat_minutes=5, clock=lambda: now[0])
    with caplog.at_level(logging.INFO):
        now[0] = 200
        bot.step()
        assert not [m for m in info(caplog) if m.startswith("still watching")]
        now[0] = 301
        bot.step()
        now[0] = 400
        bot.step()
    beats = [m for m in info(caplog) if m.startswith("still watching")]
    assert beats == ["still watching: 2 chats visible, 1 unread, 1 allowed"]


def test_heartbeat_off_by_default_in_tests(caplog):
    c = ListClient({"Budi": chat(0, inc(1))})
    bot = list_bot(c)
    with caplog.at_level(logging.INFO):
        bot.step()
    assert not [m for m in info(caplog) if m.startswith("still watching")]


def test_describe_chats_lists_unread_and_allowed_only():
    c = ListClient(
        {
            "Sari": chat(5, inc(1)),
            "Rudi": chat(2, inc(2)),
            "Bu Tini": chat(0, inc(3)),
            "Dewi": chat(0, Message("o", "Me", "x", "ts", True)),
        }
    )
    bot = list_bot(c, allow=("Sari", "Dewi"), tags={"Sari": "lover"})
    lines = bot.describe_chats(c.chat_rows())
    assert lines == [
        "Sari  [unread 5]  allowed (name), lover",
        "Rudi  [unread 2]  not allowed",
        "Dewi  [read]  allowed (name)",
    ]


def test_list_chats_command_prints_the_verdict(capsys, tmp_path):
    from argparse import Namespace

    from wabot.__main__ import _diagnose
    from wabot.config import Settings

    settings = Settings(_env_file=None, allowed_chats="Sari:lover", persona_file=tmp_path / "p.md")
    client = ListClient({"Sari": chat(5, inc(1)), "Rudi": chat(0, inc(2))})
    args = Namespace(list_chats=True, dump_dom=False, send_test=None, out="data/dom")
    assert _diagnose(client, args, settings) == 0
    out = capsys.readouterr().out
    assert "1. Sari  [unread 5]  -> allowed (name), lover" in out
    assert "2. Rudi  -> not allowed" in out


# ---------------- what they sent, reading time and the reply timeline
import random  # noqa: E402

from test_bot import FakeClient, FakeGen, make  # noqa: E402

from wabot.llm import ReplyError  # noqa: E402


def words_msg(i, text):
    return Message(f"id{i}", "Dewi", text, "14:05, 29/10/2026", False)


def test_incoming_messages_are_logged_once_with_time_and_sender(caplog):
    c = FakeClient(msgs=[words_msg(1, "kamu udah makan belum?"), words_msg(2, "jangan lupa yaa")])
    bot = make(c, FakeGen(ReplyError("boom")))  # stays pending: step twice, log once
    with caplog.at_level(logging.INFO):
        bot.step()
        bot.step()
    lines = info(caplog)
    assert lines.count("Budi: 2 new message(s) from them:") == 1
    assert "  [14:05, 29/10/2026] Dewi: kamu udah makan belum?" in lines
    assert "  [14:05, 29/10/2026] Dewi: jangan lupa yaa" in lines


def test_long_messages_are_cut_in_the_log(caplog):
    c = FakeClient(msgs=[words_msg(1, "x" * 500)])
    with caplog.at_level(logging.INFO):
        make(c, FakeGen()).step()
    line = next(m for m in info(caplog) if m.startswith("  ["))
    assert line.endswith("x" * 200 + "...") and len(line) < 260


def test_message_text_can_be_left_out_of_the_log(caplog):
    c = FakeClient(msgs=[words_msg(1, "rahasia banget")])
    with caplog.at_level(logging.INFO):
        make(c, FakeGen(), log_messages=False).step()
    text = "\n".join(info(caplog))
    assert "rahasia" not in text
    assert "Budi: 1 new message(s) from them, 14 characters" in text


def test_chat_opened_is_logged_in_list_mode(caplog):
    from test_bot import ListClient, chat, list_bot

    c = ListClient({"Budi": chat(1, inc(1))})
    with caplog.at_level(logging.INFO):
        list_bot(c).step()
    lines = info(caplog)
    assert lines.index("Budi: opening chat (1 unread)") < lines.index("Budi: chat opened")


def paced_bot(msgs, tag=None, **kw):
    slept = []
    c = FakeClient(msgs=msgs)
    kw.setdefault("delay", (5.0, 5.0))
    kw.setdefault("read_seconds_per_word", 1.0)
    bot = make(
        c,
        FakeGen(),
        tags={"Budi": tag} if tag else None,
        rng=random.Random(7),
        sleep=slept.append,
        **kw,
    )
    return bot, c, slept


def test_reply_waits_for_reading_and_thinking_before_typing(caplog):
    bot, c, slept = paced_bot([words_msg(1, "satu dua tiga")])
    with caplog.at_level(logging.INFO):
        bot.step()
    # reading: (1 + 3 words) s with 0.8 to 1.3 spread, thinking exactly 5 s
    assert 3.2 + 5 <= slept[0] <= 5.2 + 5
    assert any("reading" in m and "thinking 5.0 s" in m for m in info(caplog))
    assert "Budi: sent" in info(caplog)
    assert c.sent == ["ok"]


def test_longer_message_means_longer_reading():
    short, _, s1 = paced_bot([words_msg(1, "ya")])
    long, _, s2 = paced_bot([words_msg(1, " ".join(["kata"] * 30))])
    short.step()
    long.step()
    assert s2[0] > s1[0]


def test_friend_chats_get_the_same_delay_as_everyone():
    plain, _, s1 = paced_bot([words_msg(1, "halo kamu")])
    friend, _, s2 = paced_bot([words_msg(1, "halo kamu")], tag="friend")
    plain.step()
    friend.step()
    assert s1 == s2


def test_dry_run_logs_the_timeline_but_never_waits(caplog):
    bot, c, slept = paced_bot([words_msg(1, "halo")], dry_run=True, char_delay_ms=200)
    with caplog.at_level(logging.INFO):
        assert bot.step() == "ok"
    assert slept == [] and c.sent == []
    lines = info(caplog)
    assert any("then typing 2 characters" in m for m in lines)
    assert "Budi: dry run, nothing sent" in lines
