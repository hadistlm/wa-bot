"""Playwright driver for WhatsApp Web."""

from __future__ import annotations

import logging
from pathlib import Path
from types import TracebackType
from typing import Self

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from wabot.models import ChatRow, Message
from wabot.whatsapp import selectors as sel
from wabot.whatsapp.parser import parse_message

log = logging.getLogger(__name__)
URL = "https://web.whatsapp.com"


class SessionExpiredError(RuntimeError):
    pass


class WhatsAppClient:
    def __init__(self, profile_dir: Path, channel: str = "", headless: bool = False) -> None:
        self._profile_dir = profile_dir
        self._channel = channel or None
        self._headless = headless
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None
        self.page: Page | None = None

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
            badge = row.locator(sel.ROW_UNREAD).first
            unread = 0
            if badge.count() > 0:
                digits = "".join(
                    c for c in (badge.get_attribute("aria-label") or "") if c.isdigit()
                )
                unread = int(digits) if digits else 1
            preview_loc = row.locator(sel.ROW_PREVIEW).first
            preview = preview_loc.inner_text().strip() if preview_loc.count() > 0 else ""
            if title:
                out.append(ChatRow(title, unread, preview))
        return out

    def open_chat(self, title: str) -> bool:
        """Click the chat list row with this title. False if it is not rendered."""
        page = self._page()
        rows = page.locator(sel.ROW)
        for i in range(rows.count()):
            title_loc = rows.nth(i).locator(sel.ROW_TITLE).first
            if title_loc.count() == 0:
                continue
            if (title_loc.get_attribute("title") or title_loc.inner_text()).strip() != title:
                continue
            rows.nth(i).click()
            try:
                page.wait_for_selector(sel.CHAT_HEADER, timeout=5000)
            except PlaywrightTimeoutError:
                return False
            return True
        return False

    def close_chat(self) -> None:
        """Return to the chat list view."""
        self._page().keyboard.press("Escape")

    def active_chat(self) -> tuple[str, bool] | None:
        page = self._page()
        if page.locator(sel.CHAT_HEADER).count() == 0:
            return None
        title_loc = page.locator(sel.CHAT_TITLE).first
        if title_loc.count() == 0:
            return None
        title = (title_loc.get_attribute("title") or title_loc.inner_text()).strip()
        is_group = page.locator(sel.GROUP_HINT).count() > 0
        return (title, is_group) if title else None

    def read_messages(self) -> list[Message]:
        rows = self._page().locator(sel.MESSAGE_ROW)
        out: list[Message] = []
        for i in range(rows.count()):
            row = rows.nth(i)
            wa_id = row.get_attribute("data-id") or ""
            holder = row.locator(sel.PRE_PLAIN_HOLDER).first
            if not wa_id or holder.count() == 0:
                continue
            text_loc = row.locator(sel.MESSAGE_TEXT)
            text = "\n".join(text_loc.all_inner_texts())
            msg = parse_message(
                holder.get_attribute(sel.PRE_PLAIN_ATTR),
                text,
                wa_id,
                outgoing=wa_id.startswith("true_"),
            )
            if msg:
                out.append(msg)
        return out

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
