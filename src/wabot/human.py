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
) -> TypingPlan | None:
    """Plan how to type `text`. None means paste instantly (typing disabled).

    Each key waits `base_ms` give or take `jitter` (0.4 means 40 percent). A space or
    punctuation mark sometimes adds a longer beat. The key delays together never exceed
    `max_seconds`; the start and Enter pauses sit outside that cap.
    """
    if base_ms <= 0 or not text:
        return None
    rng = rng or random.Random()
    delays: list[float] = []
    for char in text:
        delay = base_ms * (1.0 + rng.uniform(-jitter, jitter))
        if char in BEAT_AFTER and rng.random() < BEAT_CHANCE:
            delay += rng.uniform(*BEAT_MS)
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
