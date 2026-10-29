from wabot.whatsapp.parser import parse_message


def test_parses_sender_and_time():
    m = parse_message("[10:32, 29/10/2026] Budi Santoso: ", "hi", "id1", False)
    assert (m.sender, m.sent_at, m.text, m.outgoing) == (
        "Budi Santoso",
        "10:32, 29/10/2026",
        "hi",
        False,
    )


def test_sender_with_colon_in_text_is_safe():
    m = parse_message("[10:32 AM, 10/29/2026] Ann: ", "a: b", "id2", True)
    assert m.sender == "Ann" and m.text == "a: b" and m.outgoing


def test_empty_text_becomes_media():
    assert parse_message("[1:00, 1/1/2026] X: ", "", "i", False).text == "[media]"


def test_bad_or_missing_attr():
    assert parse_message(None, "x", "i", False) is None
    assert parse_message("garbage", "x", "i", False) is None
