import pytest

from wabot.profile import MIN_SAMPLES, build_profile, is_trivial, prompt_block


@pytest.mark.parametrize("text", ["ok", "Oke!", "siap", "thanks", "makasih", "👍", "terima kasih"])
def test_trivial(text):
    assert is_trivial(text)


@pytest.mark.parametrize("text", ["ok bisa kirim filenya?", "thanks, one question", "[media]", "?"])
def test_not_trivial(text):
    assert not is_trivial(text)


def test_indonesian_casual_friend():
    texts = [
        "gak bisa bro wkwk",
        "udah makan belum sih",
        "gue mau ke sana nih",
        "ini apa ya dong",
        "aku gak tau deh",
    ]
    p = build_profile(texts)
    assert (p.language, p.formality, p.relationship) == ("id", "casual", "friend")


def test_english_formal_work():
    texts = ["Dear team, please send the update", "Regards, the meeting is at 3"] * 3
    p = build_profile(texts)
    assert (p.language, p.formality, p.relationship) == ("en", "formal", "work")


def test_tag_overrides_inference():
    texts = ["gak bisa bro wkwk"] * MIN_SAMPLES
    assert build_profile(texts, "work").relationship == "work"


def test_cold_start_unknown_and_empty_block():
    p = build_profile(["halo"])
    assert p.relationship == "unknown"
    assert prompt_block(p, []) == ""


def test_tag_without_history_still_in_block():
    assert "work contact" in prompt_block(build_profile([], "work"), [])


def test_avg_words_and_block_length_hint():
    p = build_profile(["satu dua tiga empat"] * MIN_SAMPLES)
    assert p.avg_words == 4
    assert "about 4 words" in prompt_block(p, ["Siap"])
