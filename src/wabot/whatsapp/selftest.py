"""Read-only checks of every selector against the live page, plus one explicit send test.

Reports counts and PASS/FAIL only. Chat names and message text never appear in the output.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from wabot.human import typing_plan
from wabot.matching import match_rule
from wabot.whatsapp import selectors as sel
from wabot.whatsapp.client import WhatsAppClient
from wabot.whatsapp.dump import dump_dom

TYPING_PROBE = "wabot selftest"
SEND_TEST_TEXT = "wabot send test, please ignore"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


def format_report(checks: Sequence[Check]) -> str:
    lines = []
    for c in checks:
        status = "PASS" if c.ok else ("FAIL" if c.required else "INFO")
        lines.append(f"{status}  {c.name}" + (f"  ({c.detail})" if c.detail else ""))
    failed = sum(1 for c in checks if not c.ok and c.required)
    lines.append(f"{len(checks) - failed} of {len(checks)} checks fine, {failed} failed")
    return "\n".join(lines)


def passed(checks: Sequence[Check]) -> bool:
    return all(c.ok or not c.required for c in checks)


def _page(client: WhatsAppClient) -> Page:
    if client.page is None:
        raise RuntimeError("client not started")
    return client.page


def check_list(client: WhatsAppClient) -> list[Check]:
    page = _page(client)
    raw = page.locator(sel.ROW).count()
    rows = client.chat_rows()
    with_preview = sum(1 for r in rows if r.preview)
    badges = sum(1 for r in rows if r.unread)
    chip = page.get_by_role("button", name=re.compile("unread", re.IGNORECASE)).count()
    return [
        Check("chat list found", page.locator(sel.PANE_SIDE).count() > 0),
        Check("chat list rows found", raw > 0, f"{raw} rows"),
        Check("rows with a title", bool(rows) and len(rows) == raw, f"{len(rows)} of {raw}"),
        Check(
            "rows with preview text",
            with_preview > 0,
            f"{with_preview} of {len(rows)}",
            required=False,
        ),
        Check(
            "unread badges detected",
            True,
            f"{badges} rows: compare with the Unread filter count on screen",
            required=False,
        ),
        Check("Unread filter chip found", chip > 0, required=False),
    ]


def _typing_probe(page: Page) -> list[Check]:
    box = page.locator(sel.COMPOSE_BOX).last
    box.click()
    box.press_sequentially(TYPING_PROBE, delay=5)
    typed = TYPING_PROBE in box.inner_text()
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.press("Backspace")
    cleared = box.inner_text().strip() == ""
    return [
        Check("typing into the compose box", typed),
        Check("compose box cleared again", cleared, "" if cleared else "clear it by hand"),
    ]


def _closes(client: WhatsAppClient) -> Check:
    page = _page(client)
    client.close_chat()
    try:
        page.wait_for_selector(sel.CHAT_HEADER, state="detached", timeout=3000)
        return Check("Esc returns to the chat list", True)
    except PlaywrightError:
        return Check(
            "Esc returns to the chat list", False, "chat stays open; the bot still works", False
        )


def resolve_chat(client: WhatsAppClient, name: str | None, index: int | None) -> str | None:
    """Row title for a typed name (loose match) or a 1-based position in the list."""
    rows = client.chat_rows()
    if index is not None:
        return rows[index - 1].title if 1 <= index <= len(rows) else None
    if name:
        return next((r.title for r in rows if match_rule(r.title, [name], 0.85)), None)
    return None


def check_chat(client: WhatsAppClient, title: str, out_dir: Path | None) -> list[Check]:
    page = _page(client)
    resolved = resolve_chat(client, title, None)
    if resolved is None:
        rows = len(client.chat_rows())
        hint = "run --list-chats to see the exact names, or use --chat-index N"
        return [
            Check("chat found in the list", False, f"no row matches the name ({rows} rows); {hint}")
        ]
    title = resolved
    checks = [Check("chat found in the list", True)]
    if not client.open_chat(title):
        if out_dir is not None:
            dump_dom(client, out_dir, with_chat=True, whole_page=True)
        detail = client.open_error + (f", page structure saved in {out_dir}" if out_dir else "")
        return [*checks, Check("chat opens from the list", False, detail)]
    checks.append(Check("chat opens from the list", True))
    header = client.active_chat()
    checks.append(Check("header title read", header is not None))
    checks.append(
        Check("header title equals list title", header is not None and header[0] == title)
    )
    bubbles = page.locator(sel.MESSAGE_ROW).count()
    with_attr = page.locator(f"{sel.MESSAGE_ROW} {sel.PRE_PLAIN_HOLDER}").count()
    messages = client.read_messages()
    incoming = sum(1 for m in messages if not m.outgoing)
    checks.append(Check("message bubbles found", bubbles > 0, f"{bubbles} bubbles"))
    checks.append(Check("bubbles with sender and time", with_attr > 0, f"{with_attr} of {bubbles}"))
    checks.append(
        Check(
            "messages parsed",
            len(messages) > 0,
            f"{len(messages)} parsed: {incoming} incoming, {len(messages) - incoming} outgoing",
        )
    )
    checks.append(
        Check(
            "own messages recognised",
            len(messages) > incoming,
            f"{len(messages) - incoming} outgoing; 0 is fine only if you never wrote here",
            required=False,
        )
    )
    checks.append(Check("compose box found", page.locator(sel.COMPOSE_BOX).count() > 0))
    if page.locator(sel.COMPOSE_BOX).count() > 0:
        checks.extend(_typing_probe(page))
    if out_dir is not None:
        dump_dom(client, out_dir, with_chat=True)
    checks.append(_closes(client))
    return checks


def run_selftest(client: WhatsAppClient, chat_title: str | None, out_dir: Path) -> list[Check]:
    """Read-only. Types a probe into the compose box but never presses Enter."""
    checks = check_list(client)
    written = dump_dom(client, out_dir, with_chat=False)
    checks.append(Check("redacted list dump written", bool(written), str(out_dir), required=False))
    if chat_title:
        checks.extend(check_chat(client, chat_title, out_dir))
    return checks


def _outgoing_count(client: WhatsAppClient, text: str) -> int:
    return sum(1 for m in client.read_messages() if m.outgoing and m.text == text)


def send_test(
    client: WhatsAppClient,
    title: str,
    char_delay_ms: float = 0.0,
    jitter: float = 0.4,
    max_typing_seconds: float = 20.0,
    timeout_s: float = 8.0,
) -> list[Check]:
    """Send exactly one short message to the named chat and confirm it shows up.

    It types with the same human schedule as a real reply, so the other person sees
    "typing..." for a few seconds."""
    if not client.open_chat(title):
        return [Check("chat opens from the list", False)]
    checks = [Check("chat opens from the list", True)]
    before = _outgoing_count(client, SEND_TEST_TEXT)
    plan = typing_plan(SEND_TEST_TEXT, char_delay_ms, jitter, max_typing_seconds)
    client.send(SEND_TEST_TEXT, plan)
    deadline = time.monotonic() + timeout_s
    seen = False
    while time.monotonic() < deadline:
        if _outgoing_count(client, SEND_TEST_TEXT) > before:
            seen = True
            break
        time.sleep(0.5)
    checks.append(Check("sent message appears as an outgoing bubble", seen))
    checks.append(_closes(client))
    return checks
