import pytest

from wabot.whatsapp.client import WhatsAppClient
from wabot.whatsapp.selftest import (
    SEND_TEST_TEXT,
    Check,
    format_report,
    passed,
    run_selftest,
    send_test,
)

pytestmark = pytest.mark.browser

PAGE = """
<div id="pane-side">
  <div role="listitem"><span dir="auto" title="Budi">Budi</span>
    <span dir="ltr">halo</span><span aria-label="1 unread message">1</span></div>
  <div role="listitem"><span dir="auto" title="Me (You)">Me (You)</span>
    <span dir="ltr">catatan</span></div>
</div>
<button>Unread</button>
<script>
const openChat = (t) => {
  document.getElementById('main')?.remove();
  const m = document.createElement('div'); m.id = 'main';
  m.innerHTML = '<header><span dir="auto" title="' + t + '">' + t + '</span></header>'
    + '<div data-id="false_1@c.us_A"><div data-pre-plain-text="[10:00, 1/1/2026] ' + t + ': ">'
    + '<span class="selectable-text">halo</span></div></div>'
    + '<footer><div contenteditable="true"></div></footer>';
  document.body.appendChild(m);
  const box = m.querySelector('[contenteditable]');
  box.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const text = box.innerText.trim();
    if (!text) return;
    box.innerText = '';
    (window.__sent = window.__sent || []).push(text);
    const d = document.createElement('div');
    d.setAttribute('data-id', 'true_1@c.us_' + Date.now());
    d.innerHTML = '<div data-pre-plain-text="[10:01, 1/1/2026] Me: ">'
      + '<span class="selectable-text"></span></div>';
    d.querySelector('.selectable-text').textContent = text;
    m.insertBefore(d, m.querySelector('footer'));
  });
};
document.querySelectorAll('[role=listitem]').forEach((r) =>
  r.addEventListener('click', () => openChat(r.querySelector('span').title)));
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') document.getElementById('main')?.remove();
});
</script>
"""


@pytest.fixture
def client():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:
            pytest.skip("no chromium")
        page = browser.new_page()
        page.set_content(PAGE)
        c = WhatsAppClient.__new__(WhatsAppClient)
        c.page = page
        yield c
        browser.close()


def by_name(checks):
    return {c.name: c for c in checks}


def test_selftest_passes_on_a_page_shaped_like_whatsapp(client, tmp_path):
    checks = run_selftest(client, "Budi", tmp_path)
    failed = [c for c in checks if not c.ok and c.required]
    assert failed == [], format_report(checks)
    named = by_name(checks)
    assert named["chat list rows found"].detail == "2 rows"
    assert "1 incoming" in named["messages parsed"].detail
    assert (tmp_path / "list.html").exists() and (tmp_path / "chat.html").exists()


def test_report_and_dumps_contain_no_chat_text(client, tmp_path):
    checks = run_selftest(client, "Budi", tmp_path)
    everything = format_report(checks) + "".join(p.read_text() for p in tmp_path.iterdir())
    assert "Budi" not in everything and "halo" not in everything


def test_selftest_fails_loudly_when_the_chat_is_missing(client, tmp_path):
    checks = run_selftest(client, "Nobody", tmp_path)
    assert not passed(checks)
    assert by_name(checks)["chat found in the list"].ok is False


def test_selftest_never_sends(client, tmp_path):
    run_selftest(client, "Budi", tmp_path)
    client.open_chat("Budi")
    assert [m for m in client.read_messages() if m.outgoing] == []


def test_send_test_sends_exactly_one_message(client):
    checks = send_test(client, "Me (You)", timeout_s=3)
    assert passed(checks), format_report(checks)
    assert client.page.evaluate("window.__sent") == [SEND_TEST_TEXT]


def test_format_report_marks_optional_failures_as_info():
    report = format_report(
        [Check("a", True), Check("b", False, "why"), Check("c", False, "", False)]
    )
    assert "PASS  a" in report and "FAIL  b  (why)" in report and "INFO  c" in report
    assert report.endswith("2 of 3 checks fine, 1 failed")


def test_resolve_chat_by_name_and_position(client):
    from wabot.whatsapp.selftest import resolve_chat

    assert resolve_chat(client, "budi", None) == "Budi"
    assert resolve_chat(client, None, 2) == "Me (You)"
    assert resolve_chat(client, None, 3) is None
    assert resolve_chat(client, "Nobody", None) is None
