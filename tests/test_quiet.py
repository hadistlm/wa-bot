from datetime import time

import pytest

from wabot.quiet import parse_quiet_hours


def test_disabled_when_empty():
    assert parse_quiet_hours("") is None
    assert parse_quiet_hours("  ") is None


def test_overnight_window():
    q = parse_quiet_hours("23:00-07:00")
    assert q.contains(time(23, 0)) and q.contains(time(2, 30)) and q.contains(time(6, 59))
    assert (
        not q.contains(time(7, 0)) and not q.contains(time(12, 0)) and not q.contains(time(22, 59))
    )


def test_same_day_window():
    q = parse_quiet_hours("13:00 - 14:00")
    assert q.contains(time(13, 30)) and not q.contains(time(14, 0))


def test_equal_times_never_quiet():
    assert not parse_quiet_hours("08:00-08:00").contains(time(8, 0))


@pytest.mark.parametrize("raw", ["23-07", "25:00-07:00", "abc", "23:00-07:61"])
def test_invalid_raises(raw):
    with pytest.raises(ValueError):
        parse_quiet_hours(raw)
