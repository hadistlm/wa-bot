import pytest

from wabot.matching import match_rule, parse_allowlist


def test_parse_allowlist_with_tags():
    parsed = parse_allowlist(" Budi:work, *Santoso* ,,+62 812, Ani:Friend, Eve:boss")
    assert parsed == {
        "Budi": "work",
        "*Santoso*": None,
        "+62 812": None,
        "Ani": "friend",
        "Eve:boss": None,
    }


@pytest.mark.parametrize(
    "title",
    ["+62 812-3456-7890", "0812 3456 7890", "6281234567890"],
)
def test_phone_formats_match(title):
    assert match_rule(title, ["+62 812-3456-7890"]).startswith("phone")


def test_phone_does_not_match_other_number():
    assert match_rule("+62 811 111 1111", ["+62 812-3456-7890"]) is None


def test_name_substring_case_and_accent():
    assert match_rule("Budi Santoso", ["budi"]).startswith("name")
    assert match_rule("José", ["jose"]).startswith("name")


def test_glob():
    assert match_rule("Pak Santoso Jr", ["*santoso*"]).startswith("glob")


def test_fuzzy_typo():
    assert match_rule("Budi", ["Budy"], 0.7).startswith("fuzzy")
    assert match_rule("Andi", ["Budy"], 0.85) is None


def test_empty_allowlist_fails_closed():
    assert match_rule("Budi", []) is None
    assert match_rule("", ["Budi"]) is None
