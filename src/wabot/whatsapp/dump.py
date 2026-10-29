"""Redacted dumps of the WhatsApp Web page structure.

The dump keeps tags, classes, roles and attribute names so selectors can be fixed from it.
Text, names, phone numbers, ids and URLs are masked, so the files hold no chat content.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

from wabot.whatsapp import selectors as sel
from wabot.whatsapp.client import WhatsAppClient

# Interface words that stay readable. Everything else is masked letter by letter.
KEEP_WORDS = frozenset(
    "all unread favorites groups search chat chats list message messages photo video audio "
    "document sticker gif read delivered sent pinned muted archived new type you status "
    "menu button tab row grid cell".split()
)
# Attributes whose value is structure, not content.
KEEP_ATTRS = frozenset(
    "class role dir id data-icon data-testid type contenteditable tabindex aria-hidden "
    "aria-selected aria-checked aria-live aria-pressed data-tab spellcheck translate lang "
    "data-lexical-editor".split()
)
URL_ATTRS = frozenset({"src", "href", "srcset", "poster"})
SKIP_TAGS = frozenset({"script", "style", "svg"})
VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_WORD = re.compile(r"[^\W_]+")
_DATA_ID_PREFIX = re.compile(r"^(true|false)_")
MAX_DUMP_BYTES = 400_000


def mask_text(text: str) -> str:
    """Mask letters as x and digits as 9. Keep punctuation, spacing and interface words."""

    def mask_word(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.lower() in KEEP_WORDS:
            return word
        return "".join("9" if c.isdigit() else "x" for c in word)

    return _WORD.sub(mask_word, text)


def _mask_attr(name: str, value: str) -> str:
    if name in KEEP_ATTRS:
        return value
    if name == "style" or name in URL_ATTRS:
        return ""
    if name == "data-id":
        prefix = _DATA_ID_PREFIX.match(value)
        head = prefix.group(0) if prefix else ""
        return head + mask_text(value[len(head) :])
    return mask_text(value)


class _Redactor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def _open(self, tag: str, attrs: list[tuple[str, str | None]], *, closing: bool) -> str:
        parts = [tag]
        for name, value in attrs:
            if value is None:
                parts.append(name)
            else:
                masked = html.escape(_mask_attr(name, value), quote=True)
                parts.append(f'{name}="{masked}"')
        return "<" + " ".join(parts) + (" />" if closing else ">") + "\n"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip:
            if tag in SKIP_TAGS:
                self._skip += 1
            return
        self.out.append(self._open(tag, attrs, closing=False))
        if tag in SKIP_TAGS:
            self._skip = 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self._skip:
            self.out.append(self._open(tag, attrs, closing=True))

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            if tag in SKIP_TAGS:
                self._skip -= 1
                if self._skip == 0:
                    self.out.append(f"</{tag}>\n")
            return
        if tag not in VOID_TAGS:
            self.out.append(f"</{tag}>\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.out.append(html.escape(mask_text(data.strip()), quote=False) + "\n")


def redact_html(markup: str) -> str:
    parser = _Redactor()
    parser.feed(markup)
    parser.close()
    return "".join(parser.out)


_ARIA_LINE = re.compile(r"^(\s*-\s+)([/\w-]+)(.*)$")
_ARIA_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_ARIA_FLAG = re.compile(r"(\[[a-z-]+(?:=[\w.-]+)?\])")


def redact_aria(snapshot: str) -> str:
    """Mask names and text in an accessibility snapshot. Roles and [flags] stay readable."""
    lines = []
    for line in snapshot.splitlines():
        match = _ARIA_LINE.match(line)
        if match is None:
            lines.append(mask_text(line))
            continue
        head, role, rest = match.groups()
        rest = _ARIA_QUOTED.sub(lambda m: '"' + mask_text(m.group(1)) + '"', rest)
        parts = _ARIA_FLAG.split(rest)
        rest = "".join(p if _ARIA_FLAG.fullmatch(p) else mask_text(p) for p in parts)
        lines.append(head + role + rest)
    return "\n".join(lines)


def _outer_html(client: WhatsAppClient, selector: str) -> str:
    page = client.page
    if page is None:
        raise RuntimeError("client not started")
    return str(page.evaluate("s => document.querySelector(s)?.outerHTML ?? ''", selector))


def dump_dom(
    client: WhatsAppClient, out_dir: Path, with_chat: bool, whole_page: bool = False
) -> list[Path]:
    """Write redacted list and (optionally open-chat) structure into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    targets = [("list.html", sel.PANE_SIDE)]
    if with_chat:
        targets.append(("chat.html", "#main"))
    if whole_page:
        targets.append(("page.html", "body"))
    for filename, selector in targets:
        raw = _outer_html(client, selector)
        if not raw:
            continue
        path = out_dir / filename
        path.write_text(redact_html(raw)[:MAX_DUMP_BYTES], encoding="utf-8")
        written.append(path)
    page = client.page
    if page is not None and page.locator(sel.PANE_SIDE).count() > 0:
        aria = out_dir / "list.aria.txt"
        aria.write_text(
            redact_aria(page.locator(sel.PANE_SIDE).aria_snapshot())[:MAX_DUMP_BYTES],
            encoding="utf-8",
        )
        written.append(aria)
    return written
