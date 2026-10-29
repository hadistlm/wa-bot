from types import SimpleNamespace

import pytest

from wabot.llm import GeminiReplyGenerator
from wabot.models import Message
from wabot.profile import build_profile, prompt_block
from wabot.tone import FAMILY, LOVER, rank_for, split_reply, tone_for

CTX = [Message("1", "Dewi", "halo", "ts", False)]
PERSONA_RULE = "Keep replies to one or two lines."


def test_only_lover_and_family_have_a_tone():
    assert tone_for("lover") is LOVER and tone_for("family") is FAMILY
    for other in ("work", "friend", "unknown", None, ""):
        assert tone_for(other) is None


def test_lover_is_stronger_than_family():
    assert LOVER.max_parts > FAMILY.max_parts
    assert LOVER.max_output_tokens > FAMILY.max_output_tokens
    assert "2 to 4 messages" in LOVER.rules and "1 to 3 messages" in FAMILY.rules
    assert "40 to 90 words" in LOVER.rules and "25 to 60 words" in FAMILY.rules
    assert "partner" in LOVER.rules and "family" in FAMILY.rules


def test_rules_state_that_they_outrank_the_persona_and_define_the_separator():
    for tone in (LOVER, FAMILY):
        assert "outrank everything below" in tone.rules
        assert "persona" in tone.rules and "message-count rule" in tone.rules
        assert "line containing only ---" in tone.rules
        assert "priority rules at the top" in tone.reminder


def test_queue_rank_puts_lover_before_family_before_the_rest():
    assert rank_for("lover") < rank_for("family") < rank_for("friend") == rank_for(None)


# ---------------- splitting


def test_no_tone_means_one_message_untouched():
    text = "satu\n\ndua\n---\ntiga"
    assert split_reply(text, None) == [text]
    assert split_reply("   ", LOVER) == []


def test_splits_on_the_marker_line():
    text = "Halo sayang 😘\n---\nUdah makan belum?\n---\nJangan lupa istirahat ya"
    assert split_reply(text, LOVER) == [
        "Halo sayang 😘",
        "Udah makan belum?",
        "Jangan lupa istirahat ya",
    ]


def test_falls_back_to_blank_lines_when_there_is_no_marker():
    assert split_reply("Satu\n\nDua\n\nTiga", FAMILY) == ["Satu", "Dua", "Tiga"]


def test_falls_back_to_sentences_for_one_long_block():
    sentence = "Aku kangen banget sama kamu hari ini."
    text = " ".join([sentence] * 8)  # about 300 characters, no breaks
    parts = split_reply(text, LOVER)
    assert 2 <= len(parts) <= LOVER.max_parts
    assert all(len(p) <= 180 for p in parts)
    assert " ".join(parts) == text


def test_short_single_block_stays_one_message():
    assert split_reply("Iya sayang, nanti aku kabarin ya", LOVER) == [
        "Iya sayang, nanti aku kabarin ya"
    ]


def test_extra_parts_are_merged_into_the_last_message():
    text = "\n---\n".join(["a", "b", "c", "d", "e", "f"])
    parts = split_reply(text, LOVER)
    assert parts == ["a", "b", "c", "d e f"]
    assert split_reply(text, FAMILY) == ["a", "b", "c d e f"]


def test_empty_pieces_are_dropped():
    assert split_reply("a\n---\n\n---\nb", LOVER) == ["a", "b"]


# ---------------- prompt order


def gen_with_capture(persona=f"You are Andra.\n{PERSONA_RULE}"):
    seen = {}

    def fake(**kw):
        seen["config"] = kw["config"]
        return SimpleNamespace(text="ok")

    g = GeminiReplyGenerator("k", "m", persona, max_output_tokens=300, sleep=lambda _: None)
    g._client = SimpleNamespace(models=SimpleNamespace(generate_content=fake))
    return g, seen


def test_tone_rules_sit_above_the_persona_even_when_the_persona_says_short():
    g, seen = gen_with_capture()
    g.generate(CTX, "Chat context: lover contact.", LOVER)
    prompt = seen["config"].system_instruction
    order = [
        prompt.index("PRIORITY RULES FOR THIS CHAT"),
        prompt.index("PERSONA"),
        prompt.index(PERSONA_RULE),
        prompt.index("CHAT NOTES"),
        prompt.index(LOVER.reminder),
    ]
    assert order == sorted(order)
    assert prompt.index("outrank everything below") < prompt.index(PERSONA_RULE)
    assert prompt.rstrip().endswith(LOVER.reminder)


def test_engaged_chats_get_a_bigger_token_budget_others_keep_theirs():
    g, seen = gen_with_capture()
    g.generate(CTX, "", LOVER)
    assert seen["config"].max_output_tokens == 900
    g.generate(CTX, "", FAMILY)
    assert seen["config"].max_output_tokens == 700
    g.generate(CTX, "")
    assert seen["config"].max_output_tokens == 300


def test_other_chats_get_the_old_prompt_without_priority_rules():
    g, seen = gen_with_capture()
    g.generate(CTX, "Chat context: friend contact.")
    prompt = seen["config"].system_instruction
    assert "PRIORITY" not in prompt and "PERSONA" not in prompt
    assert prompt.startswith("You are Andra.") and prompt.endswith("friend contact.")


def test_a_bigger_configured_budget_is_not_lowered():
    g = GeminiReplyGenerator("k", "m", "p", max_output_tokens=2000, sleep=lambda _: None)
    seen = {}
    g._client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kw: seen.update(kw) or SimpleNamespace(text="ok")
        )
    )
    g.generate(CTX, "", LOVER)
    assert seen["config"].max_output_tokens == 2000


# ---------------- chat notes


@pytest.mark.parametrize("tag", ["lover", "family"])
def test_no_short_reply_hint_for_lover_or_family(tag):
    profile = build_profile(["halo ya"] * 6, tag)
    assert "Keep your reply near" not in prompt_block(profile, [])


def test_other_relationships_keep_the_length_hint():
    profile = build_profile(["halo ya"] * 6, "friend")
    assert "Keep your reply near" in prompt_block(profile, [])
