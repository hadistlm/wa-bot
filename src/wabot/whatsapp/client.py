"""Playwright driver for WhatsApp Web."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Self

from playwright.sync_api import BrowserContext, Locator, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from wabot.models import ChatRow, Message
from wabot.whatsapp import selectors as sel
from wabot.whatsapp.parser import parse_message

log = logging.getLogger(__name__)
URL = "https://web.whatsapp.com"
YOU_LABELS = frozenset({"you", "anda", "kamu"})
_READ_JS = """
els => els.map(el => {
  const pre = el.querySelector('[data-pre-plain-text]');
  const texts = [...el.querySelectorAll('span.selectable-text')]
    .filter(e => !e.closest('[data-testid="quoted-message"]'))
    .map(e => e.innerText);
  const label = el.querySelector('span[aria-label$=":"]');
  return {
    id: el.getAttribute('data-id'),
    pre: pre ? pre.getAttribute('data-pre-plain-text') : null,
    text: texts.join('\\n'),
    tailOut: !!el.querySelector('[data-icon="tail-out"]'),
    tailIn: !!el.querySelector('[data-icon="tail-in"]'),
    label: label ? label.getAttribute('aria-label') : '',
  };
})
"""


class SessionExpiredError(RuntimeError):
    pass


class WhatsAppClient:
    def __init__(
        self,
        profile_dir: Path,
        channel: str = "",
        headless: bool = False,
        own_names: Iterable[str] = (),
    ) -> None:
        self._profile_dir = profile_dir
        self._channel = channel or None
        self._headless = headless
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None
        self.page: Page | None = None
        self.open_error = ""
        self.own_names: set[str] = {n.casefold() for n in own_names}
        self.on_own_name: Callable[[str], None] | None = None

    def __enter__(self) -> Self:
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(self._profile_dir),
            headless=self._headless,
            channel=self._channel,
            viewport={"width": 1366, "height": 900},
        )
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self.page.goto(URL)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._ctx:
            self._ctx.close()
        if self._pw:
            self._pw.stop()

    def _page(self) -> Page:
        if self.page is None:
            raise RuntimeError("client not started")
        return self.page

    def wait_logged_in(self, timeout_s: float = 30) -> None:
        """Return once the chat list shows. Raise if a QR code shows instead."""
        page = self._page()
        page.wait_for_selector(f"{sel.PANE_SIDE}, {sel.QR_CANVAS}", timeout=timeout_s * 1000)
        if page.locator(sel.PANE_SIDE).count() == 0:
            raise SessionExpiredError("session expired, run `python -m wabot --login`")

    def login(self, timeout_s: float = 180) -> None:
        """Wait for the user to scan the QR code."""
        self._page().wait_for_selector(sel.PANE_SIDE, timeout=timeout_s * 1000)

    def chat_rows(self) -> list[ChatRow]:
        """Rows currently rendered in the chat list. The list is virtualized."""
        rows = self._page().locator(sel.ROW)
        out: list[ChatRow] = []
        for i in range(rows.count()):
            row = rows.nth(i)
            title_loc = row.locator(sel.ROW_TITLE).first
            if title_loc.count() == 0:
                continue
            title = (title_loc.get_attribute("title") or title_loc.inner_text()).strip()
            if title:
                out.append(ChatRow(title, self._unread(row), self._preview(row)))
        return out

    @staticmethod
    def _unread(row: Locator) -> int:
        """Unread count from the badge, or 1 for a chat marked unread without a number."""
        badge = row.locator(sel.ROW_UNREAD).first
        if badge.count() > 0:
            digits = "".join(c for c in (badge.get_attribute("aria-label") or "") if c.isdigit())
            return int(digits) if digits else 1
        cell = row.locator(sel.ROW_TITLE_CELL).first
        if cell.count() > 0 and "unread" in cell.inner_text().lower():
            return 1
        return 0

    @staticmethod
    def _preview(row: Locator) -> str:
        loc = row.locator(sel.ROW_PREVIEW).first
        return loc.inner_text().strip() if loc.count() > 0 else ""

    def open_chat(self, title: str) -> bool:
        """Click the chat list row with this title. False if it is not rendered.

        On failure, `open_error` says whether the row was missing or the chat never opened.
        """
        page = self._page()
        self.open_error = ""
        rows = page.locator(sel.ROW)
        for i in range(rows.count()):
            row = rows.nth(i)
            title_loc = row.locator(sel.ROW_TITLE).first
            if title_loc.count() == 0:
                continue
            if (title_loc.get_attribute("title") or title_loc.inner_text()).strip() != title:
                continue
            target = row.locator(sel.ROW_CLICK_TARGET).first
            (target if target.count() > 0 else row).click()
            try:
                page.wait_for_selector(sel.CHAT_OPEN, timeout=5000)
            except PlaywrightTimeoutError:
                self.open_error = "clicked the row but no open chat appeared"
                return False
            return True
        self.open_error = "no row with that title is rendered"
        return False

    def close_chat(self) -> None:
        """Return to the chat list view."""
        self._page().keyboard.press("Escape")

    def active_chat(self) -> tuple[str, bool] | None:
        page = self._page()
        if page.locator(sel.CHAT_OPEN).count() == 0:
            return None
        title_loc = page.locator(sel.CHAT_TITLE).first
        if title_loc.count() == 0:
            title_loc = page.locator(sel.ACTIVE_ROW_TITLE).first
        if title_loc.count() == 0:
            return None
        title = (title_loc.get_attribute("title") or title_loc.inner_text()).strip()
        is_group = page.locator(sel.GROUP_HINT).count() > 0
        return (title, is_group) if title else None

    def read_messages(self) -> list[Message]:
        """Messages in the open chat, oldest first, with direction worked out.

        Direction: the bubble's tail icon decides when present (the first bubble of a run).
        Later bubbles in a run have no tail, so they fall back to the sender name, which the
        client learns from tail-out bubbles, then to the "You:" label.
        """
        raw = self._page().locator(sel.MESSAGE_ROW).evaluate_all(_READ_JS)
        parsed: list[tuple[Message, dict[str, object]]] = []
        for item in raw:
            wa_id = str(item.get("id") or "")
            msg = parse_message(item.get("pre"), str(item.get("text") or ""), wa_id, outgoing=False)
            if wa_id and msg is not None:
                parsed.append((msg, item))
        for msg, item in parsed:
            if item.get("tailOut"):
                self.learn_own_name(msg.sender)
        return [replace(msg, outgoing=self._is_outgoing(msg, item)) for msg, item in parsed]

    def learn_own_name(self, name: str) -> None:
        folded = name.strip().casefold()
        if folded and folded not in self.own_names:
            self.own_names.add(folded)
            if self.on_own_name is not None:
                self.on_own_name(folded)

    def _is_outgoing(self, msg: Message, item: dict[str, object]) -> bool:
        if item.get("tailOut") or msg.wa_id.startswith("true_"):
            return True
        if item.get("tailIn") or msg.wa_id.startswith("false_"):
            return False
        label = str(item.get("label") or "").rstrip(":").strip().casefold()
        return label in YOU_LABELS or msg.sender.casefold() in self.own_names

    def send(self, text: str, char_delay_ms: float = 0.0) -> None:
        """Type the reply key by key so WhatsApp shows "typing...", then press Enter."""
        page = self._page()
        box = page.locator(sel.COMPOSE_BOX).last
        box.click()
        for i, line in enumerate(text.split("\n")):
            if i:
                page.keyboard.press("Shift+Enter")
            if char_delay_ms > 0:
                box.press_sequentially(line, delay=char_delay_ms)
            elif i == 0:
                box.fill(line)
            else:
                page.keyboard.insert_text(line)
        page.keyboard.press("Enter")
