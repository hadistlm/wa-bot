"""Quiet hours: a daily window in which the bot stays silent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

_RANGE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


@dataclass(frozen=True, slots=True)
class QuietHours:
    start: time
    end: time

    def contains(self, now: time) -> bool:
        """True inside the window. A window like 23:00-07:00 crosses midnight."""
        if self.start == self.end:
            return False
        if self.start < self.end:
            return self.start <= now < self.end
        return now >= self.start or now < self.end


def parse_quiet_hours(raw: str) -> QuietHours | None:
    """Parse "23:00-07:00". Empty string disables quiet hours."""
    if not raw.strip():
        return None
    match = _RANGE.match(raw)
    if match is None:
        raise ValueError(f"QUIET_HOURS must look like 23:00-07:00, got {raw!r}")
    h1, m1, h2, m2 = (int(g) for g in match.groups())
    try:
        return QuietHours(time(h1, m1), time(h2, m2))
    except ValueError as exc:
        raise ValueError(f"QUIET_HOURS has an invalid time: {raw!r}") from exc
