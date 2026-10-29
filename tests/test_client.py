import pytest

from wabot.whatsapp.client import WhatsAppClient

pytestmark = pytest.mark.browser

HTML = """
<div id="main"><header><span dir="auto" title="Budi Santoso">Budi Santoso</span></header>
<div data-id="false_1@c.us_AAA"><div data-pre-plain-text="[10:32, 29/10/2026] Budi Santoso: ">
<span class="selectable-text">halo</span></div></div>
<div data-id="true_1@c.us_BBB"><div data-pre-plain-text="[10:33, 29/10/2026] Me: ">
<span class="selectable-text">hi</span></div></div>
<div data-id="false_1@c.us_CCC"><div>no text attr</div></div>
<footer><div contenteditable="true"></div></footer></div>
"""


def test_reads_fixture():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:
            pytest.skip("no chromium")
        page = browser.new_page()
        page.set_content(HTML)
        client = WhatsAppClient.__new__(WhatsAppClient)
        client.page = page
        assert client.active_chat() == ("Budi Santoso", False)
        msgs = client.read_messages()
        assert [(m.sender, m.text, m.outgoing) for m in msgs] == [
            ("Budi Santoso", "halo", False),
            ("Me", "hi", True),
        ]
        browser.close()


def test_send_types_into_compose_box():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:
            pytest.skip("no chromium")
        page = browser.new_page()
        page.set_content(HTML)
        client = WhatsAppClient.__new__(WhatsAppClient)
        client.page = page
        client.send("halo bro", char_delay_ms=1)
        assert page.locator("footer div[contenteditable]").inner_text().startswith("halo bro")
        browser.close()
