"""Human-like typing schedule. Pure: no browser, no clock, easy to test."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

START_PAUSE_MS = (400.0, 1500.0)  # before the first key
ENTER_PAUSE_MS = (300.0, 1200.0)  # between the last key and Enter
BEAT_MS = (120.0, 400.0)  # occasional longer beat after a space or punctuation
BEAT_CHANCE = 0.2
BEAT_AFTER = frozenset(" ,.!?;:\n")
STALL_CHANCE = 0.02  # per key: the typist stops to think mid-sentence
STALL_MS = (700.0, 2200.0)
STALL_AFTER = 8  # no stall in the first few keys
READ_BASE_S = 1.0
READ_CAP_S = 12.0
READ_SPREAD = (0.8, 1.3)


class _Rng(Protocol):
    def uniform(self, a: float, b: float) -> float: ...

    def random(self) -> float: ...


@dataclass(frozen=True, slots=True)
class TypingPlan:
    """When to press each key. `char_delays_ms[i]` is the wait after typing character i."""

    start_pause_ms: float
    char_delays_ms: tuple[float, ...]
    enter_pause_ms: float

    @property
    def typing_ms(self) -> float:
        return sum(self.char_delays_ms)


def typing_plan(
    text: str,
    base_ms: float,
    jitter: float,
    max_seconds: float,
    rng: _Rng | None = None,
    stall_chance: float = STALL_CHANCE,
) -> TypingPlan | None:
    """Plan how to type `text`. None means paste instantly (typing disabled).

    Each key waits `base_ms` give or take `jitter` (0.4 means 40 percent). A space or
    punctuation mark sometimes adds a longer beat, and now and then the typist stalls for a
    second or two mid-sentence. The key delays together never exceed
    `max_seconds`; the start and Enter pauses sit outside that cap.
    """
    if base_ms <= 0 or not text:
        return None
    rng = rng or random.Random()
    delays: list[float] = []
    for index, char in enumerate(text):
        delay = base_ms * (1.0 + rng.uniform(-jitter, jitter))
        if char in BEAT_AFTER and rng.random() < BEAT_CHANCE:
            delay += rng.uniform(*BEAT_MS)
        if index >= STALL_AFTER and stall_chance > 0 and rng.random() < stall_chance:
            delay += rng.uniform(*STALL_MS)
        delays.append(max(delay, 1.0))
    cap_ms = max_seconds * 1000.0
    total = sum(delays)
    if total > cap_ms:
        delays = [d * cap_ms / total for d in delays]
    return TypingPlan(
        start_pause_ms=rng.uniform(*START_PAUSE_MS),
        char_delays_ms=tuple(delays),
        enter_pause_ms=rng.uniform(*ENTER_PAUSE_MS),
    )


def reading_seconds(words: int, per_word: float, rng: _Rng | None = None) -> float:
    """Time to read the other person's message before answering. 0 when disabled."""
    if per_word <= 0 or words <= 0:
        return 0.0
    rng = rng or random.Random()
    seconds = min(READ_BASE_S + per_word * words, READ_CAP_S)
    return seconds * rng.uniform(*READ_SPREAD)
