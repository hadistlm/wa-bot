import random

import pytest

from wabot.human import (
    BEAT_MS,
    ENTER_PAUSE_MS,
    START_PAUSE_MS,
    typing_plan,
)

TEXT = "Siap, saya cek dulu ya. Nanti saya kabari!"


def plan(text=TEXT, base=140, jitter=0.4, cap=20, seed=1):
    return typing_plan(text, base, jitter, cap, random.Random(seed))


def test_disabled_or_empty_means_paste_instantly():
    assert typing_plan(TEXT, 0, 0.4, 20) is None
    assert typing_plan("", 140, 0.4, 20) is None


def test_one_delay_per_character():
    assert len(plan().char_delays_ms) == len(TEXT)


def test_same_seed_same_plan_different_seed_differs():
    assert plan(seed=3) == plan(seed=3)
    assert plan(seed=3) != plan(seed=4)


def test_keys_are_uneven_not_a_fixed_cadence():
    delays = plan().char_delays_ms
    assert len(set(round(d) for d in delays)) > len(delays) // 2


def test_delays_stay_within_jitter_except_for_beats():
    p = plan(text="abcdefghij" * 5, base=100, jitter=0.4)  # no spaces or punctuation
    assert all(60 <= d <= 140 for d in p.char_delays_ms)


def test_zero_jitter_gives_the_base_delay_for_plain_letters():
    p = plan(text="abcdef", base=100, jitter=0.0)
    assert set(p.char_delays_ms) == {100.0}


def test_beats_only_follow_spaces_and_punctuation():
    longest = 100 * 1.4 + BEAT_MS[1]
    p = plan(text="a b, c. d! " * 30, base=100, jitter=0.4, seed=7)
    assert max(p.char_delays_ms) > 140  # at least one beat happened
    assert max(p.char_delays_ms) <= longest + 0.001


def test_total_typing_time_is_capped_but_pauses_are_not_part_of_it():
    p = plan(text="x" * 1000, base=140, cap=20)
    assert p.typing_ms == pytest.approx(20_000, rel=1e-6)
    assert START_PAUSE_MS[0] <= p.start_pause_ms <= START_PAUSE_MS[1]
    assert ENTER_PAUSE_MS[0] <= p.enter_pause_ms <= ENTER_PAUSE_MS[1]


def test_short_reply_is_not_stretched_to_the_cap():
    assert plan(text="ok", cap=20).typing_ms < 1000


def test_realistic_speed_for_a_typical_reply():
    seconds = plan().typing_ms / 1000
    assert 3 < seconds < 12  # 41 characters, roughly 7 characters per second
