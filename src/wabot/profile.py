"""Per-chat profile built from stored messages. Pure functions, no model calls."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from wabot.tone import tone_for

MIN_SAMPLES = 5
_WORD = re.compile(r"[a-zA-Z']+")

ID_WORDS = frozenset(
    "yang dan gak nggak ga aku saya kamu anda ini itu ya nih dong deh sih udah sudah makasih "
    "terima kasih tidak bisa mau apa kapan gimana bagaimana dengan untuk tolong lagi aja saja "
    "banget bro sis wkwk wkwkwk gue lu".split()
)
EN_WORDS = frozenset(
    "the and is are you please thanks thank regards will can could would for with this that we "
    "i it have has been our your meeting update let know".split()
)
FORMAL_WORDS = frozenset(
    "dear regards sincerely bapak ibu pak bu mohon terima kasih please kindly anda".split()
)
CASUAL_WORDS = frozenset(
    "gak nggak ga wkwk wkwkwk haha bro sis dong deh sih nih lu gue udah banget lol".split()
)
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")

_TRIVIAL = re.compile(
    r"(?:ok+|oke+|okay|okey|siap+|sip+|thanks?|thx|makasih|terima kasih|noted|sama[- ]sama"
    r"|mantap|nice|[\U0001f44d\U0001f64f\U0001f44c\s.!])+",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ChatProfile:
    language: str  # "id" | "en" | "mixed" | "unknown"
    avg_words: int
    formality: str  # "formal" | "casual" | "neutral"
    relationship: str  # "work" | "friend" | "unknown"
    samples: int


def is_trivial(text: str) -> bool:
    """A bare acknowledgement that needs no answer."""
    return bool(_TRIVIAL.fullmatch(text.strip()))


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _language(words: Sequence[str]) -> str:
    id_hits = sum(w in ID_WORDS for w in words)
    en_hits = sum(w in EN_WORDS for w in words)
    if id_hits + en_hits < 3:
        return "unknown"
    share = id_hits / (id_hits + en_hits)
    if share >= 0.65:
        return "id"
    if share <= 0.35:
        return "en"
    return "mixed"


def _formality(words: Sequence[str], texts: Sequence[str]) -> str:
    formal = sum(w in FORMAL_WORDS for w in words)
    casual = sum(w in CASUAL_WORDS for w in words) + sum(bool(_EMOJI.search(t)) for t in texts)
    if formal > casual:
        return "formal"
    if casual > formal:
        return "casual"
    return "neutral"


def build_profile(incoming: Sequence[str], relationship_tag: str | None = None) -> ChatProfile:
    texts = [t for t in incoming if t and t != "[media]"]
    words = [w for t in texts for w in _words(t)]
    formality = _formality(words, texts)
    relationship = relationship_tag or {"formal": "work", "casual": "friend"}.get(
        formality, "unknown"
    )
    if not relationship_tag and len(texts) < MIN_SAMPLES:
        relationship = "unknown"
    avg = round(sum(len(_words(t)) for t in texts) / len(texts)) if texts else 0
    return ChatProfile(_language(words), avg, formality, relationship, len(texts))


def prompt_block(profile: ChatProfile, own_examples: Sequence[str]) -> str:
    """Short per-chat addition to the system instruction. Empty if nothing is known."""
    lines: list[str] = []
    ready = profile.samples >= MIN_SAMPLES
    if ready or profile.relationship != "unknown":
        parts = [f"{profile.relationship} contact"] if profile.relationship != "unknown" else []
        if ready and profile.language != "unknown":
            parts.append(
                {"id": "mostly Indonesian", "en": "mostly English", "mixed": "mixed ID/EN"}[
                    profile.language
                ]
            )
        if ready and profile.formality != "neutral":
            parts.append(profile.formality)
        if ready and profile.avg_words:
            parts.append(f"they write about {profile.avg_words} words per message")
        if parts:
            lines.append("Chat context: " + ", ".join(parts) + ".")
        if ready and profile.avg_words and tone_for(profile.relationship) is None:
            lines.append(
                f"Keep your reply near {max(profile.avg_words, 3)} words "
                "unless a question needs more."
            )
    if own_examples:
        quoted = " / ".join(f'"{e}"' for e in own_examples)
        lines.append(f"Your own recent messages in this chat, copy this voice: {quoted}")
    return "\n".join(lines)
