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


SIDEBAR = """
<div id="pane-side">
  <div role="listitem" id="r1"><span dir="auto" title="Budi Santoso">Budi Santoso</span>
    <span dir="ltr">halo bro</span><span aria-label="3 unread messages">3</span></div>
  <div role="listitem" id="r2"><span dir="auto" title="Ani">Ani</span>
    <span dir="ltr">ok</span></div>
</div>
<script>
  document.querySelectorAll('[role=listitem]').forEach(r => r.addEventListener('click', () => {
    const t = r.querySelector('span').title;
    const m = document.createElement('div'); m.id = 'main';
    m.innerHTML = '<header><span dir="auto" title="' + t + '">' + t + '</span></header>';
    document.getElementById('main')?.remove(); document.body.appendChild(m);
  }));
</script>
"""


def test_reads_chat_list_and_opens_a_row():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:
            pytest.skip("no chromium")
        page = browser.new_page()
        page.set_content(SIDEBAR)
        client = WhatsAppClient.__new__(WhatsAppClient)
        client.page = page
        rows = client.chat_rows()
        assert [(r.title, r.unread, r.preview) for r in rows] == [
            ("Budi Santoso", 3, "halo bro"),
            ("Ani", 0, "ok"),
        ]
        assert client.open_chat("Ani") is True
        assert client.active_chat() == ("Ani", False)
        assert client.open_chat("Nobody") is False
        browser.close()


REAL_LIST = """
<div id="pane-side"><div role="grid" aria-label="Chat list">
  <div role="row" data-testid="list-item-0"><div role="gridcell"><div aria-selected="false">
    <div data-testid="cell-frame-container">
      <div data-testid="cell-frame-title"><span>1 unread message</span>
        <span dir="auto" title="Vira">Vira</span></div>
      <span data-testid="chat-list-timestamp">13:42</span>
      <div data-testid="cell-frame-secondary"><span data-testid="last-msg-status"
        title="let see ya">let see ya</span>
        <span data-testid="icon-unread-count" aria-label="1 unread message">1</span></div>
    </div></div></div></div>
  <div role="row" data-testid="list-item-1"><div role="gridcell"><div aria-selected="true">
    <div data-testid="cell-frame-container">
      <div data-testid="cell-frame-title"><span>unread</span>
        <span dir="auto" title="Masday">Masday</span></div>
      <div data-testid="cell-frame-secondary"><span>uyy</span></div>
    </div></div></div></div>
  <div role="row" data-testid="list-item-2"><div role="gridcell"><div aria-selected="false">
    <div data-testid="cell-frame-container">
      <div data-testid="cell-frame-title"><span dir="auto" title="Wa Eti">Wa Eti</span></div>
      <div data-testid="cell-frame-secondary"><span>ok</span></div>
    </div></div></div></div>
</div></div>
"""


def test_reads_the_real_chat_list_structure():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:
            pytest.skip("no chromium")
        page = browser.new_page()
        page.set_content(REAL_LIST)
        client = WhatsAppClient.__new__(WhatsAppClient)
        client.page = page
        rows = client.chat_rows()
        assert [(r.title, r.unread) for r in rows] == [("Vira", 1), ("Masday", 1), ("Wa Eti", 0)]
        assert "uyy" in rows[1].preview and "let see ya" in rows[0].preview
        browser.close()


def test_active_chat_falls_back_to_the_selected_row():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:
            pytest.skip("no chromium")
        page = browser.new_page()
        page.set_content(REAL_LIST + '<div id="main"></div>')
        client = WhatsAppClient.__new__(WhatsAppClient)
        client.page = page
        assert client.active_chat() == ("Masday", False)
        browser.close()
