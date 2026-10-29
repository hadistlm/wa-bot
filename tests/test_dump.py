from wabot.whatsapp.dump import mask_text, redact_aria, redact_html

RAW = """
<div id="pane-side" role="grid" style="background:url(http://secret/x.png)">
  <div role="listitem" class="row" data-id="true_628123456789@c.us_3EB0ABCDEF">
    <img src="https://pps.whatsapp.net/private.jpg" alt="Budi Santoso">
    <span dir="auto" title="Budi Santoso">Budi Santoso</span>
    <span dir="ltr">transfer 500000 ke rekening</span>
    <span aria-label="3 unread messages">3</span>
    <a href="https://wa.me/628123456789">link</a>
    <svg viewBox="0 0 1 1"><path d="M0 0"/><g><title>hidden</title></g></svg>
  </div>
  <div data-pre-plain-text="[10:32, 29/10/2026] Budi Santoso: ">x</div>
  <script>var token = "abc123";</script>
</div>
"""


def test_names_text_and_numbers_are_masked():
    out = redact_html(RAW)
    for secret in ["Budi", "Santoso", "transfer", "500000", "628123456789", "secret", "abc123"]:
        assert secret not in out
    assert "xxxx xxxxxxx" in out


def test_structure_is_kept():
    out = redact_html(RAW)
    assert 'id="pane-side"' in out
    assert 'role="grid"' in out and 'role="listitem"' in out
    assert 'class="row"' in out and 'dir="auto"' in out
    assert "<span" in out and "</span>" in out


def test_data_id_keeps_direction_prefix_only():
    out = redact_html(RAW)
    assert 'data-id="true_999999999999@x.xx_9xx9xxxxxx"' in out


def test_pre_plain_text_keeps_its_shape():
    assert "[99:99, 99/99/9999] xxxx xxxxxxx: " in redact_html(RAW)


def test_unread_label_stays_readable_but_the_count_is_masked():
    assert 'aria-label="9 unread messages"' in redact_html(RAW)


def test_urls_styles_and_svg_children_are_dropped():
    out = redact_html(RAW)
    assert 'src=""' in out and 'href=""' in out and 'style=""' in out
    assert "<path" not in out and "hidden" not in out and "<script" in out
    assert "var token" not in out


def test_mask_text_keeps_interface_words_and_symbols():
    assert mask_text("Unread 12 from Ani ❤️") == "Unread 99 xxxx xxx ❤️"


def test_aria_snapshot_masks_names_and_text_but_keeps_roles_and_flags():
    snapshot = (
        '- row "Budi Santoso, 3 unread messages" [selected]:\n'
        "  - listitem: Budi halo1\n"
        '  - button "Unread"\n'
        "  - /url: https://wa.me/628123"
    )
    out = redact_aria(snapshot)
    for secret in ["Budi", "Santoso", "halo", "wa.me", "628123"]:
        assert secret not in out
    assert "- row" in out and "[selected]" in out and "unread messages" in out
    assert 'button "Unread"' in out and "- /url:" in out and "listitem:" in out
