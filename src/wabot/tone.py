"""Fixed tone for the people closest to you.

Deliberately not configurable. These rules go above the persona in the system prompt and
say they win, so a line such as "keep replies to one or two lines" in persona.md cannot
shorten a lover or family reply. Lover is stronger than family.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PRIORITY_HEAD = (
    "PRIORITY RULES FOR THIS CHAT\n"
    "These outrank everything below, including any length, style or message-count rule in "
    "the persona. Keep the persona's name, language and identity. Only the tone, the length "
    "and the number of messages change here."
)
SEPARATOR_RULE = (
    "Write the whole reply in one go. Put each separate chat message on its own, divided "
    "from the next by a line containing only --- . That separator line is the one exception "
    "to the output rules and is never shown to the reader."
)
LOVER_TONE = (
    "This is your partner. Be warm, affectionate and playful. React to what they said, show "
    "you care, ask one follow-up question and use a few fitting emoji. Never answer with a "
    "flat 'ok' or 'iya'. Write 2 to 4 messages, 40 to 90 words in total."
)
FAMILY_TONE = (
    "This is a family member. Be warm, respectful and caring. Show interest in how they are "
    "and react to what they said, without sounding stiff or formal. Never answer with a flat "
    "'ok' or 'iya'. Write 1 to 3 messages, 25 to 60 words in total."
)
REMINDER = (
    "Reminder: follow the priority rules at the top, especially the warmth, the length and "
    "the --- separators."
)


@dataclass(frozen=True, slots=True)
class Tone:
    name: str
    rules: str
    reminder: str
    max_parts: int
    max_output_tokens: int


LOVER = Tone(
    "lover",
    f"{PRIORITY_HEAD}\n{LOVER_TONE}\n{SEPARATOR_RULE}",
    REMINDER,
    max_parts=4,
    max_output_tokens=900,
)
FAMILY = Tone(
    "family",
    f"{PRIORITY_HEAD}\n{FAMILY_TONE}\n{SEPARATOR_RULE}",
    REMINDER,
    max_parts=3,
    max_output_tokens=700,
)
TONES = {"lover": LOVER, "family": FAMILY}
RANK = {"lover": 0, "family": 1}  # who is answered first when several chats wait
DEFAULT_RANK = 2

_MARKER = re.compile(r"^[ \t]*-{3,}[ \t]*$", re.MULTILINE)
_BLANK_LINE = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
LONG_BLOCK = 180
CHUNK = 140


def tone_for(relationship: str | None) -> Tone | None:
    return TONES.get(relationship or "")


def rank_for(relationship: str | None) -> int:
    return RANK.get(relationship or "", DEFAULT_RANK)


def _chunk_sentences(text: str) -> list[str]:
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + 1 + len(sentence) > CHUNK:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def split_reply(text: str, tone: Tone | None) -> list[str]:
    """Split one Gemini answer into the chat messages to send.

    Without a tone the answer stays one message. With one, split on the --- marker, then on
    blank lines, then on sentences for a long block, and merge anything past the tone's cap
    into the last message.
    """
    text = text.strip()
    if tone is None or not text:
        return [text] if text else []
    parts = [p.strip() for p in _MARKER.split(text) if p.strip()]
    if len(parts) == 1:
        parts = [p.strip() for p in _BLANK_LINE.split(parts[0]) if p.strip()]
    if len(parts) == 1 and len(parts[0]) > LONG_BLOCK:
        parts = _chunk_sentences(parts[0])
    if len(parts) > tone.max_parts:
        head, tail = parts[: tone.max_parts - 1], parts[tone.max_parts - 1 :]
        parts = [*head, " ".join(tail)]
    return parts
