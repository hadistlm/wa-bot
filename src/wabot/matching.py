"""Allowlist matching for chat titles: names, phone numbers, globs, typos."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from difflib import SequenceMatcher
from fnmatch import fnmatchcase

PHONE_MIN_DIGITS = 7
PHONE_TAIL = 9


TAGS = frozenset({"work", "friend", "lover", "family"})


def parse_allowlist(raw: str) -> dict[str, str | None]:
    """Parse "Budi:work, +62 812 3456 7890, *Santoso*" into {pattern: tag or None}."""
    entries: dict[str, str | None] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        pattern, _, tag = part.rpartition(":")
        if pattern and tag.strip().lower() in TAGS:
            entries[pattern.strip()] = tag.strip().lower()
        else:
            entries[part] = None
    return entries


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _is_phone(text: str) -> bool:
    return len(_digits(text)) >= PHONE_MIN_DIGITS and not re.search(r"[^\d\s+\-().]", text)


def _phone_match(entry: str, title: str) -> bool:
    a, b = _digits(entry), _digits(title)
    if len(b) < PHONE_MIN_DIGITS:
        return False
    return a[-PHONE_TAIL:] == b[-PHONE_TAIL:]


def match_rule(title: str, allowlist: Iterable[str], threshold: float = 0.85) -> str | None:
    """Return a description of the rule that matched, or None.

    Order: phone, glob, exact/substring, fuzzy. Empty allowlist matches nothing.
    """
    entries = [e for e in allowlist if e]
    if not title or not entries:
        return None
    folded_title = _fold(title)

    for entry in entries:
        if _is_phone(entry) and _phone_match(entry, title):
            return f"phone:{entry}"
    for entry in entries:
        if _is_phone(entry):
            continue
        folded = _fold(entry)
        if any(ch in folded for ch in "*?") and fnmatchcase(folded_title, folded):
            return f"glob:{entry}"
    for entry in entries:
        if _is_phone(entry):
            continue
        folded = _fold(entry)
        if "*" in folded or "?" in folded:
            continue
        if folded == folded_title or folded in folded_title:
            return f"name:{entry}"
    for entry in entries:
        if _is_phone(entry):
            continue
        folded = _fold(entry)
        if "*" in folded or "?" in folded:
            continue
        if SequenceMatcher(None, folded, folded_title).ratio() >= threshold:
            return f"fuzzy:{entry}"
    return None


def allow_label(
    title: str,
    allowlist: Iterable[str],
    tags: Mapping[str, str | None],
    threshold: float = 0.85,
) -> str:
    """Say whether a chat is allowed and by which rule, for example "allowed (name), lover"."""
    rule = match_rule(title, allowlist, threshold)
    if rule is None:
        return "not allowed"
    kind, _, entry = rule.partition(":")
    tag = tags.get(entry)
    return f"allowed ({kind})" + (f", {tag}" if tag else "")
