"""Decision loop: read chat, store, ask the model, send."""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from wabot.llm import FatalReplyError, ReplyError, ReplyGenerator
from wabot.matching import match_rule
from wabot.models import Message
from wabot.profile import build_profile, is_trivial, prompt_block
from wabot.quiet import QuietHours
from wabot.store import Store

log = logging.getLogger(__name__)
FRIEND_DELAY_SCALE = 0.5


class ChatClient(Protocol):
    def active_chat(self) -> tuple[str, bool] | None:
        """(title, is_group) of the open chat, or None."""
        ...

    def read_messages(self) -> Sequence[Message]: ...

    def send(self, text: str, char_delay_ms: float = 0.0) -> None: ...


class Bot:
    def __init__(
        self,
        client: ChatClient,
        generator: ReplyGenerator,
        store: Store,
        allowlist: Sequence[str],
        *,
        tags: Mapping[str, str | None] | None = None,
        allow_groups: bool = False,
        threshold: float = 0.85,
        context_messages: int = 5,
        dry_run: bool = False,
        delay: tuple[float, float] = (0.0, 0.0),
        skip_trivial: bool = False,
        debounce: bool = False,
        max_replies_per_hour: int = 1000,
        quiet: QuietHours | None = None,
        char_delay_ms: float = 0.0,
        max_typing_seconds: float = 20.0,
        now: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._generator = generator
        self._store = store
        self._allowlist = allowlist
        self._tags = tags or {}
        self._allow_groups = allow_groups
        self._threshold = threshold
        self._n = context_messages
        self._dry_run = dry_run
        self._delay = delay
        self._skip_trivial = skip_trivial
        self._debounce = debounce
        self._max_per_hour = max_replies_per_hour
        self._quiet = quiet
        self._char_delay_ms = char_delay_ms
        self._max_typing_seconds = max_typing_seconds
        self._now = now
        self._was_quiet = False
        self._sleep = sleep
        self._clock = clock
        self._warned_empty = False
        self._dry_seen: set[tuple[int, str]] = set()
        self._last_pending: dict[int, str] = {}
        self._sent_at: defaultdict[int, deque[float]] = defaultdict(deque)

    def _rate_limited(self, chat_id: int) -> bool:
        window = self._sent_at[chat_id]
        now = self._clock()
        while window and now - window[0] > 3600:
            window.popleft()
        return len(window) >= self._max_per_hour

    def _typing_delay_ms(self, reply: str) -> float:
        """Per-key delay, lowered so a long reply never types longer than the cap."""
        if self._char_delay_ms <= 0 or not reply:
            return 0.0
        return min(self._char_delay_ms, self._max_typing_seconds * 1000 / len(reply))

    def step(self) -> str | None:
        """One poll. Returns the reply text if one was produced."""
        if not self._allowlist and not self._warned_empty:
            log.warning("ALLOWED_CHATS is empty: the bot answers nobody")
            self._warned_empty = True
        if self._quiet is not None:
            quiet_now = self._quiet.contains(self._now().time())
            if quiet_now != self._was_quiet:
                log.info("quiet hours %s", "started" if quiet_now else "ended")
                self._was_quiet = quiet_now
            if quiet_now:
                return None
        chat = self._client.active_chat()
        if chat is None:
            return None
        title, is_group = chat
        if is_group and not self._allow_groups:
            return None
        rule = match_rule(title, self._allowlist, self._threshold)
        if rule is None:
            return None
        tag = self._tags.get(rule.split(":", 1)[1])

        chat_id = self._store.chat_id(title)
        self._store.upsert_messages(chat_id, self._client.read_messages())
        pending = self._store.pending_incoming(chat_id)
        if pending is None:
            self._last_pending.pop(chat_id, None)
            return None
        if (chat_id, pending.wa_id) in self._dry_seen:
            return None

        if self._debounce and self._last_pending.get(chat_id) != pending.wa_id:
            self._last_pending[chat_id] = pending.wa_id  # wait one poll for more messages
            return None
        if self._skip_trivial and is_trivial(pending.text):
            log.info("chat=%r skipped trivial %r", title, pending.text)
            self._store.mark_replied(chat_id, pending.wa_id)
            return None
        if self._rate_limited(chat_id):
            log.warning("chat=%r hit the hourly reply cap", title)
            return None

        profile = build_profile(self._store.incoming_texts(chat_id), tag)
        extra = prompt_block(profile, self._store.own_examples(chat_id))
        context = self._store.recent(chat_id, self._n)
        try:
            reply = self._generator.generate(context, extra)
        except FatalReplyError:
            raise
        except ReplyError as exc:
            log.error("no reply for %r: %s", title, exc)
            self._store.record_error(chat_id, pending.wa_id, str(exc))
            return None

        log.info(
            "chat=%r rule=%s relationship=%s reply=%r", title, rule, profile.relationship, reply
        )
        if self._dry_run:
            self._dry_seen.add((chat_id, pending.wa_id))
            return reply
        scale = FRIEND_DELAY_SCALE if profile.relationship == "friend" else 1.0
        self._sleep(random.uniform(*self._delay) * scale)
        self._store.record_bot_text(chat_id, reply)
        self._client.send(reply, self._typing_delay_ms(reply))
        self._store.mark_replied(chat_id, pending.wa_id)
        self._sent_at[chat_id].append(self._clock())
        return reply
