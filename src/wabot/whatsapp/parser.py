"""Pure parsing of WhatsApp Web message attributes."""

from __future__ import annotations

import re

from wabot.models import Message

_PRE_PLAIN = re.compile(r"^\[(?P<ts>[^\]]+)\]\s*(?P<sender>.*?):\s*$", re.DOTALL)
MEDIA_PLACEHOLDER = "[media]"


def parse_message(pre_plain: str | None, text: str, wa_id: str, outgoing: bool) -> Message | None:
    """Build a Message from `data-pre-plain-text` ("[10:32, 29/10/2026] Name: ")."""
    if not pre_plain:
        return None
    match = _PRE_PLAIN.match(pre_plain.strip())
    if match is None:
        return None
    return Message(
        wa_id=wa_id,
        sender=match["sender"].strip(),
        text=text.strip() or MEDIA_PLACEHOLDER,
        sent_at=match["ts"].strip(),
        outgoing=outgoing,
    )
