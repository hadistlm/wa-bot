"""Decision loop: read chat, store, ask the model, send."""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from wabot.human import TypingPlan, typing_plan
from wabot.llm import FatalReplyError, ReplyError, ReplyGenerator
from wabot.matching import match_rule
from wabot.models import ChatRow, Message
from wabot.profile import build_profile, is_trivial, prompt_block
from wabot.quiet import QuietHours
from wabot.store import Store

log = logging.getLogger(__name__)
FRIEND_DELAY_SCALE = 0.5
AFK_UNTIL_KEY = "afk_until"
RETRY_COOLDOWN_S = 60.0
AFK_BACK_KEY = "afk_back"  # "<chat_id>:<minutes>" until the first reply after a spell


class ChatClient(Protocol):
    def active_chat(self) -> tuple[str, bool] | None:
        """(title, is_group) of the open chat, or None."""
        ...

    def read_messages(self) -> Sequence[Message]: ...

    def chat_rows(self) -> Sequence[ChatRow]: ...

    def open_chat(self, title: str) -> bool: ...

    def close_chat(self) -> None: ...

    def send(self, text: str, plan: TypingPlan | None = None) -> None: ...


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
        afk_chance: float = 0.0,
        afk_minutes: tuple[float, float] = (3.0, 20.0),
        afk_acknowledge: bool = False,
        afk_ack_min_minutes: float = 5.0,
        skip_backlog: bool = False,
        watch_mode: str = "open",
        open_delay: tuple[float, float] = (0.0, 0.0),
        reply_gap: tuple[float, float] = (0.0, 0.0),
        rng: random.Random | None = None,
        char_delay_ms: float = 0.0,
        typing_jitter: float = 0.4,
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
        self._typing_jitter = typing_jitter
        self._max_typing_seconds = max_typing_seconds
        self._now = now
        self._was_quiet = False
        self._afk_chance = afk_chance
        self._afk_minutes = afk_minutes
        self._afk_ack = afk_acknowledge
        self._afk_ack_min = afk_ack_min_minutes
        self._skip_backlog = skip_backlog
        self._seen_chats: set[int] = set()
        self._watch_mode = watch_mode
        self._open_delay = open_delay
        self._reply_gap = reply_gap
        self._gap_until = 0.0
        self._last_reply_title = ""
        self._unread_since: dict[str, float] = {}
        self._baselined = False
        self._baseline: dict[str, tuple[int, str]] = {}
        self._sig_seen: dict[str, tuple[int, str]] = {}
        self._cooldown_until: dict[str, float] = {}
        self._warned_hidden: set[str] = set()
        self._rng = rng or random.Random()
        self._afk_until = float(store.get_state(AFK_UNTIL_KEY) or 0)
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

    def _typing_plan(self, reply: str) -> TypingPlan | None:
        return typing_plan(
            reply, self._char_delay_ms, self._typing_jitter, self._max_typing_seconds, self._rng
        )

    @staticmethod
    def _rolled_key(chat_id: int) -> str:
        return f"afk_rolled:{chat_id}"

    def _afk_return(self, chat_id: int) -> float | None:
        """Minutes the last spell lasted, if this chat holds the first reply after it."""
        raw = self._store.get_state(AFK_BACK_KEY)
        if not raw:
            return None
        owner, _, minutes = raw.partition(":")
        return float(minutes) if owner == str(chat_id) else None

    def _maybe_go_afk(self, chat_id: int, wa_id: str) -> bool:
        """Roll once per incoming message. On a hit, stay away for a random spell.

        The end time and the last rolled message per chat live in SQLite, so a restart
        neither ends the spell early nor rolls the same message again.
        """
        rolled_key = self._rolled_key(chat_id)
        if self._afk_chance <= 0 or self._store.get_state(rolled_key) == wa_id:
            return False
        self._store.set_state(rolled_key, wa_id)
        if self._rng.random() >= self._afk_chance:
            return False
        minutes = self._rng.uniform(*self._afk_minutes)
        self._afk_until = self._now().timestamp() + minutes * 60
        self._store.set_state(AFK_UNTIL_KEY, str(self._afk_until))
        self._store.set_state(AFK_BACK_KEY, f"{chat_id}:{minutes}")
        log.info("going AFK for %.1f minutes", minutes)
        return True

    @staticmethod
    def _back_hint(minutes: float) -> str:
        return (
            f"You were away from your phone for about {round(minutes)} minutes. If it fits, "
            "acknowledge the delay in one short casual phrase in the sender's language "
            "(for example 'sori baru bales'). Skip it if the message does not call for it."
        )

    def _gate_closed(self) -> bool:
        """True when the bot must do nothing at all: quiet hours or an AFK spell."""
        if not self._allowlist and not self._warned_empty:
            log.warning("ALLOWED_CHATS is empty: the bot answers nobody")
            self._warned_empty = True
        if self._quiet is not None:
            quiet_now = self._quiet.contains(self._now().time())
            if quiet_now != self._was_quiet:
                log.info("quiet hours %s", "started" if quiet_now else "ended")
                self._was_quiet = quiet_now
            if quiet_now:
                return True
        return self._now().timestamp() < self._afk_until

    def step(self) -> str | None:
        """One poll. Returns the reply text if one was produced."""
        if self._gate_closed():
            return None
        if self._watch_mode == "list":
            return self._step_list()
        return self._handle_open_chat(debounce=self._debounce, backlog_check=self._skip_backlog)

    def _allowed(self, title: str) -> bool:
        return match_rule(title, self._allowlist, self._threshold) is not None

    def _cooling(self, title: str) -> bool:
        return self._clock() < self._cooldown_until.get(title, 0.0)

    def _pick_from_list(self, rows: Sequence[ChatRow]) -> str | None:
        """Choose the next allowed chat to open. Chats outside ALLOWED_CHATS are never chosen."""
        if not self._baselined:
            self._baselined = True
            if self._skip_backlog:
                self._baseline = {r.title: r.signature for r in rows if r.unread}
        for row in rows:
            if not row.unread:
                self._sig_seen.pop(row.title, None)
                self._unread_since.pop(row.title, None)
                self._baseline.pop(row.title, None)
        ready: list[tuple[float, int, str]] = []
        for index, row in enumerate(rows):
            if not row.unread or not self._allowed(row.title):
                continue
            if self._baseline.get(row.title) == row.signature:
                continue  # was already waiting when the bot started
            self._unread_since.setdefault(row.title, self._clock())
            previous = self._sig_seen.get(row.title)
            self._sig_seen[row.title] = row.signature
            if self._debounce and previous != row.signature:
                continue  # wait one poll so a burst of messages gets one reply
            if not self._cooling(row.title):
                ready.append((self._unread_since[row.title], index, row.title))
        if ready:
            return min(ready)[2]  # oldest waiting chat first, not the top of the list
        visible = {r.title for r in rows}
        for chat_id, title, wa_id in self._store.chats_with_pending():
            if (chat_id, wa_id) in self._dry_seen or self._cooling(title):
                continue
            if not self._allowed(title):
                continue
            carried = self._afk_return(chat_id) is not None
            if self._skip_backlog and chat_id not in self._seen_chats and not carried:
                continue
            if title not in visible:
                if title not in self._warned_hidden:
                    log.warning("chat=%r has a waiting message but is not in the chat list", title)
                    self._warned_hidden.add(title)
                continue
            return title
        return None

    def _step_list(self) -> str | None:
        title = self._pick_from_list(self._client.chat_rows())
        if title is None:
            return None
        if title != self._last_reply_title and self._clock() < self._gap_until:
            return None  # another chat was just answered: wait for the gap, one at a time
        self._sleep(self._rng.uniform(*self._open_delay))
        if not self._client.open_chat(title):
            log.warning("chat=%r could not be opened", title)
            self._cooldown_until[title] = self._clock() + RETRY_COOLDOWN_S
            return None
        try:
            reply = self._handle_open_chat(debounce=False, backlog_check=False)
        finally:
            self._client.close_chat()
        if reply is not None:
            self._last_reply_title = title
            self._gap_until = self._clock() + self._rng.uniform(*self._reply_gap)
        if reply is None:
            chat_id = self._store.find_chat_id(title)
            if chat_id is not None and self._store.pending_incoming(chat_id) is not None:
                self._cooldown_until[title] = self._clock() + RETRY_COOLDOWN_S
        return reply

    def _handle_open_chat(self, *, debounce: bool, backlog_check: bool) -> str | None:
        """Answer the chat that is open right now, if it is allowed and has something waiting."""
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
        first_seen = chat_id not in self._seen_chats
        self._seen_chats.add(chat_id)
        pending = self._store.pending_incoming(chat_id)
        if pending is None:
            self._last_pending.pop(chat_id, None)
            if self._afk_return(chat_id) is not None:
                self._store.set_state(AFK_BACK_KEY, "")  # you answered by hand meanwhile
            return None
        if first_seen and backlog_check and self._afk_return(chat_id) is None:
            log.info("chat=%r skipped message that was waiting before start", title)
            self._store.mark_replied(chat_id, pending.wa_id)
            return None
        if (chat_id, pending.wa_id) in self._dry_seen:
            return None

        if debounce and self._last_pending.get(chat_id) != pending.wa_id:
            self._last_pending[chat_id] = pending.wa_id  # wait one poll for more messages
            return None
        if self._skip_trivial and is_trivial(pending.text):
            log.info("chat=%r skipped trivial %r", title, pending.text)
            self._store.mark_replied(chat_id, pending.wa_id)
            return None
        if self._rate_limited(chat_id):
            log.warning("chat=%r hit the hourly reply cap", title)
            return None

        away = self._afk_return(chat_id)
        if away is not None:
            # First reply after a spell: no new roll, so spells never chain.
            self._store.set_state(AFK_BACK_KEY, "")
            self._store.set_state(self._rolled_key(chat_id), pending.wa_id)
        elif self._maybe_go_afk(chat_id, pending.wa_id):
            return None

        profile = build_profile(self._store.incoming_texts(chat_id), tag)
        extra = prompt_block(profile, self._store.own_examples(chat_id))
        if away is not None and self._afk_ack and away >= self._afk_ack_min:
            extra = f"{extra}\n{self._back_hint(away)}".strip()
        context = self._store.recent(chat_id, self._n)
        try:
            reply = self._generator.generate(context, extra)
        except FatalReplyError:
            raise
        except ReplyError as exc:
            log.error("no reply for %r: %s", title, exc)
            if away is not None:
                self._store.set_state(AFK_BACK_KEY, f"{chat_id}:{away}")
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
        self._client.send(reply, self._typing_plan(reply))
        self._store.mark_replied(chat_id, pending.wa_id)
        self._sent_at[chat_id].append(self._clock())
        return reply
