from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Message:
    wa_id: str
    sender: str
    text: str
    sent_at: str
    outgoing: bool


@dataclass(frozen=True, slots=True)
class ChatRow:
    """One row of the chat list."""

    title: str
    unread: int
    preview: str

    @property
    def signature(self) -> tuple[int, str]:
        return (self.unread, self.preview)
