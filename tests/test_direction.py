import pytest

from wabot.whatsapp.client import WhatsAppClient

pytestmark = pytest.mark.browser


def bubble(msg_id, sender, text, tail=None, label=None, quoted=None):
    """A message shaped like the 2026 page: hash id, no true_/false_ prefix."""
    tail_html = f'<span data-icon="{tail}"></span>' if tail else ""
    label_html = f'<span aria-label="{label}"></span>' if label else ""
    quote_html = (
        f'<div data-testid="quoted-message"><span class="selectable-text">{quoted}</span></div>'
        if quoted
        else ""
    )
    return (
        f'<div role="row"><div data-testid="conv-msg-{msg_id}" data-id="{msg_id}">'
        f'<div data-testid="msg-container">{tail_html}{label_html}'
        f'<div class="copyable-text" data-pre-plain-text="[10:00, 29/10/2026] {sender}: ">'
        f'{quote_html}<span class="selectable-text">{text}</span></div></div></div></div>'
    )


def page_html(*bubbles):
    return '<div id="main">' + "".join(bubbles) + "</div>"


@pytest.fixture
def make_client():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:
            pytest.skip("no chromium")
        page = browser.new_page()

        def build(html, **kw):
            page.set_content(html)
            c = WhatsAppClient.__new__(WhatsAppClient)
            c.page = page
            c.own_names = set()
            c.on_own_name = None
            c.__dict__.update(kw)
            return c

        yield build
        browser.close()


def directions(client):
    return [(m.text, m.outgoing) for m in client.read_messages()]


def test_tail_icons_decide_direction_without_id_prefixes(make_client):
    c = make_client(
        page_html(
            bubble("AAA1", "Budi", "halo", tail="tail-in", label="Budi:"),
            bubble("BBB2", "Andra", "hai", tail="tail-out", label="You:"),
        )
    )
    assert directions(c) == [("halo", False), ("hai", True)]


def test_untailed_run_follows_the_learned_own_name(make_client):
    c = make_client(
        page_html(
            bubble("A1", "Andra", "satu", tail="tail-out"),
            bubble("A2", "Andra", "dua"),  # same run, no tail
            bubble("A3", "Budi", "tiga", tail="tail-in"),
            bubble("A4", "Budi", "empat"),
        )
    )
    assert directions(c) == [("satu", True), ("dua", True), ("tiga", False), ("empat", False)]


def test_own_name_is_remembered_across_chats_and_reported(make_client):
    learned = []
    c = make_client(page_html(bubble("A1", "Andra", "satu", tail="tail-out")))
    c.on_own_name = learned.append
    c.read_messages()
    assert learned == ["andra"]
    c.read_messages()
    assert learned == ["andra"]  # reported once
    c.page.set_content(page_html(bubble("B1", "Andra", "tanpa tail")))  # another chat, no tail
    assert directions(c) == [("tanpa tail", True)]


def test_you_label_marks_outgoing_when_no_tail_and_name_unknown(make_client):
    c = make_client(page_html(bubble("A1", "Andra", "sendiri", label="You:")))
    assert directions(c) == [("sendiri", True)]


def test_configured_own_name_works_from_the_first_read(make_client):
    c = make_client(page_html(bubble("A1", "Andra", "tanpa tail")), own_names={"andra"})
    assert directions(c) == [("tanpa tail", True)]


def test_quoted_text_is_not_part_of_the_reply_text(make_client):
    c = make_client(
        page_html(bubble("A1", "Budi", "jawaban saya", tail="tail-in", quoted="pesan lama"))
    )
    assert directions(c) == [("jawaban saya", False)]


def test_stranger_without_any_signal_counts_as_incoming(make_client):
    c = make_client(page_html(bubble("A1", "Budi", "halo")))
    assert directions(c) == [("halo", False)]
