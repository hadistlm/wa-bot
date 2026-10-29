"""Starting and stopping: telling a closed browser from a real bug, and the goodbye line."""

from __future__ import annotations

import logging

# Words Playwright and its driver use when the browser, window or helper process is gone.
_GONE_MARKERS = (
    "has been closed",
    "target closed",
    "browser closed",
    "connection closed",
    "browser has disconnected",
    "from the driver",
)


def browser_gone(exc: BaseException) -> bool:
    """True when the error means the browser window or its helper process went away."""
    if type(exc).__name__ == "TargetClosedError":
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _GONE_MARKERS)


def short_error(exc: BaseException, limit: int = 200) -> str:
    """One readable line: the exception type and the first line of its message."""
    lines = str(exc).strip().splitlines()
    message = lines[0].strip() if lines else ""
    text = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return text if len(text) <= limit else text[: limit - 3] + "..."


def format_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def summary_line(chats: int, messages: int, seconds: float, dry_run: bool = False) -> str:
    ran = format_duration(seconds)
    if dry_run:
        return f"Session summary: dry run, nothing was sent, ran {ran}."
    if not messages:
        return f"Session summary: no replies sent, ran {ran}."
    return (
        f"Session summary: replied to {chats} chat{'s' if chats != 1 else ''} "
        f"({messages} message{'s' if messages != 1 else ''}), ran {ran}."
    )


class QuietShutdownNoise(logging.Filter):
    """Hide asyncio's "Future exception was never retrieved" for a dead browser pipe.

    When the browser helper dies (Ctrl+C, closed window) Playwright's last write to it fails
    and asyncio prints a traceback at exit. It tells the user nothing the bot has not said.
    Only broken-pipe style errors are hidden; anything else still shows.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.getMessage().startswith("Future exception was never retrieved"):
            return True
        error = record.exc_info[1] if record.exc_info else None
        return not isinstance(error, (BrokenPipeError, ConnectionResetError, EOFError))
