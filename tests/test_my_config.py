"""Checks your own .env.local. Reads names at run time, so no name lives in the repo.

Skipped when there is no .env.local (for example on a fresh clone or in CI).
"""

from pathlib import Path

import pytest

from wabot.config import Settings
from wabot.matching import TAGS, match_rule

pytestmark = pytest.mark.skipif(not Path(".env.local").exists(), reason="no .env.local here")


@pytest.fixture(scope="module")
def mine() -> Settings:
    return Settings(_env_file=".env.local")  # type: ignore[call-arg]


def test_allowlist_is_not_empty(mine):
    assert mine.allowlist, "ALLOWED_CHATS is empty in .env.local: the bot answers nobody"


def test_every_entry_matches_itself(mine):
    for entry in mine.allowlist:
        assert match_rule(entry, mine.allowlist, mine.match_threshold), (
            f"{entry!r} does not even match a chat titled exactly like it"
        )


def test_no_entry_has_a_mistyped_relationship_tag(mine):
    """`Sari:lovr` is read as a chat literally named "Sari:lovr", so it would never match."""
    for part in mine.allowed_chats.split(","):
        name, _, suffix = part.strip().rpartition(":")
        suffix = suffix.strip()
        if name and suffix.isalpha() and suffix.lower() not in TAGS:
            pytest.fail(f"unknown tag {suffix!r} in {part.strip()!r}; valid tags: {sorted(TAGS)}")


def test_tagged_entries_are_stored_without_their_tag(mine):
    for entry, tag in mine.chat_tags.items():
        if tag:
            assert not entry.lower().endswith(f":{tag}")


def test_a_chat_outside_the_list_is_not_matched(mine):
    assert match_rule("zzzz no such person qqqq", mine.allowlist, mine.match_threshold) is None


def test_persona_is_available(mine):
    assert mine.persona_file.is_file() or mine.persona_prompt, (
        "no persona: create persona.md (cp persona.example.md persona.md) or set PERSONA_PROMPT"
    )
