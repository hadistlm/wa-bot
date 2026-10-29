from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Message:
    wa_id: str
    sender: str
    text: str
    sent_at: str
    outgoing: bool
