"""Decision loop: read chat, store, ask the model, send."""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol

from wabot.human import BETWEEN_PARTS_S, TypingPlan, reading_seconds, typing_plan
from wabot.llm import FatalReplyError, ReplyError, ReplyGenerator
from wabot.matching import allow_label, match_rule
from wabot.models import ChatRow, Message
from wabot.profile import build_profile, is_trivial, prompt_block
from wabot.quiet import QuietHours
from wabot.store import Store
from wabot.tone import rank_for, split_reply, tone_for

log = logging.getLogger(__name__)
MAX_LOGGED_CHARS = 200
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
        heartbeat_minutes: float = 0.0,
        read_seconds_per_word: float = 0.0,
        log_messages: bool = True,
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
        self._heartbeat_s = heartbeat_minutes * 60
        self._last_beat = clock()
        self._reasons: dict[str, str] = {}
        self._read_per_word = read_seconds_per_word
        self._log_messages = log_messages
        self._logged: set[tuple[int, str]] = set()
        self._was_afk = False
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

    def _reading_seconds(self, unanswered: Sequence[Message]) -> float:
        words = sum(len(m.text.split()) for m in unanswered if m.text != "[media]")
        return reading_seconds(words, self._read_per_word, self._rng)

    def _log_received(
        self, title: str, chat_id: int, wa_id: str, unanswered: Sequence[Message]
    ) -> None:
        """Log what they sent, once per waiting message. Text only if log_messages is on."""
        if (chat_id, wa_id) in self._logged:
            return
        self._logged.add((chat_id, wa_id))
        if not self._log_messages:
            chars = sum(len(m.text) for m in unanswered)
            log.info(
                "%s: %d new message(s) from them, %d characters", title, len(unanswered), chars
            )
            return
        log.info("%s: %d new message(s) from them:", title, len(unanswered))
        for m in unanswered:
            text = m.text if len(m.text) <= MAX_LOGGED_CHARS else m.text[:MAX_LOGGED_CHARS] + "..."
            log.info("  [%s] %s: %s", m.sent_at, m.sender, text)

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

    def _note(self, key: str, reason: str) -> None:
        """Log why a chat is being held back, once per change. Every poll in DEBUG."""
        if self._reasons.get(key) != reason:
            self._reasons[key] = reason
            log.info("%s: %s", key, reason)
        else:
            log.debug("%s: %s", key, reason)

    def _beat(self, text: str) -> None:
        """Heartbeat so a quiet terminal still shows the watcher is alive."""
        if self._heartbeat_s <= 0:
            return
        now = self._clock()
        if now - self._last_beat >= self._heartbeat_s:
            self._last_beat = now
            log.info("still watching: %s", text)

    def describe_chats(self, rows: Sequence[ChatRow]) -> list[str]:
        """One line per unread or allowed chat: what the bot will do with it."""
        lines = []
        for row in rows:
            label = allow_label(row.title, self._allowlist, self._tags, self._threshold)
            if row.unread or label != "not allowed":
                unread = f"unread {row.unread}" if row.unread else "read"
                lines.append(f"{row.title}  [{unread}]  {label}")
        return lines

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
        afk_now = self._now().timestamp() < self._afk_until
        if afk_now != self._was_afk:
            self._was_afk = afk_now
            if afk_now:
                until = datetime.fromtimestamp(self._afk_until).strftime("%H:%M")
                log.info("paused until %s (AFK spell)", until)
            else:
                log.info("AFK spell ended, watching again")
        return afk_now

    def step(self) -> str | None:
        """One poll. Returns the reply text if one was produced."""
        if self._gate_closed():
            self._beat("paused (quiet hours or an AFK spell)")
            return None
        if self._watch_mode == "list":
            return self._step_list()
        self._beat("open chat mode")
        return self._handle_open_chat(debounce=self._debounce, backlog_check=self._skip_backlog)

    def _tag_of(self, title: str) -> str | None:
        rule = match_rule(title, self._allowlist, self._threshold)
        return self._tags.get(rule.split(":", 1)[1]) if rule else None

    def _allowed(self, title: str) -> bool:
        return match_rule(title, self._allowlist, self._threshold) is not None

    def _cooling(self, title: str) -> bool:
        return self._clock() < self._cooldown_until.get(title, 0.0)

    def _pick_from_list(self, rows: Sequence[ChatRow]) -> tuple[str, str] | None:
        """Choose the next allowed chat to open as (title, why). Others are never chosen."""
        if not self._baselined:
            self._baselined = True
            if self._skip_backlog:
                self._baseline = {r.title: r.signature for r in rows if r.unread}
        for row in rows:
            if not row.unread:
                self._sig_seen.pop(row.title, None)
                self._unread_since.pop(row.title, None)
                self._baseline.pop(row.title, None)
                self._reasons.pop(row.title, None)
        ready: list[tuple[int, float, int, str, str]] = []
        for index, row in enumerate(rows):
            if not row.unread:
                continue
            if not self._allowed(row.title):
                self._note(row.title, "unread, not in ALLOWED_CHATS, ignoring")
                continue
            if self._baseline.get(row.title) == row.signature:
                self._note(
                    row.title,
                    "was waiting before start, ignoring until a new message (SKIP_BACKLOG)",
                )
                continue
            self._unread_since.setdefault(row.title, self._clock())
            previous = self._sig_seen.get(row.title)
            self._sig_seen[row.title] = row.signature
            if self._debounce and previous != row.signature:
                self._note(row.title, "new messages, waiting one poll to see if more arrive")
                continue
            if self._cooling(row.title):
                self._note(row.title, "cooling down after a failed attempt")
                continue
            ready.append(
                (
                    rank_for(self._tag_of(row.title)),
                    self._unread_since[row.title],
                    index,
                    row.title,
                    f"{row.unread} unread",
                )
            )
        if ready:
            _, _, _, title, why = min(ready)  # lover, family, then oldest first
            return title, why
        visible = {r.title for r in rows}
        for chat_id, title, wa_id in self._store.chats_with_pending():
            if (chat_id, wa_id) in self._dry_seen or self._cooling(title):
                continue
            if not self._allowed(title):
                continue
            carried = self._afk_return(chat_id) is not None
            if self._skip_backlog and chat_id not in self._seen_chats and not carried:
                self._note(title, "message from before start, ignoring (SKIP_BACKLOG)")
                continue
            if title not in visible:
                if title not in self._warned_hidden:
                    log.warning("chat=%r has a waiting message but is not in the chat list", title)
                    self._warned_hidden.add(title)
                continue
            return title, "waiting message, retrying"
        return None

    def _step_list(self) -> str | None:
        rows = self._client.chat_rows()
        unread = sum(1 for r in rows if r.unread)
        allowed = sum(1 for r in rows if self._allowed(r.title))
        self._beat(f"{len(rows)} chats visible, {unread} unread, {allowed} allowed")
        log.debug("poll: %d chats, %d unread, %d allowed", len(rows), unread, allowed)
        picked = self._pick_from_list(rows)
        if picked is None:
            return None
        title, why = picked
        if title != self._last_reply_title and self._clock() < self._gap_until:
            self._note(title, "waiting for the reply gap so two chats are not answered together")
            return None  # another chat was just answered: wait for the gap, one at a time
        self._reasons.pop(title, None)
        log.info("%s: opening chat (%s)", title, why)
        self._sleep(self._rng.uniform(*self._open_delay))
        if not self._client.open_chat(title):
            log.warning("chat=%r could not be opened", title)
            self._cooldown_until[title] = self._clock() + RETRY_COOLDOWN_S
            return None
        log.info("%s: chat opened", title)
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
        unanswered = self._store.unanswered_incoming(chat_id)
        self._log_received(title, chat_id, pending.wa_id, unanswered)
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
        tone = tone_for(profile.relationship)
        try:
            if tone is None:
                reply = self._generator.generate(context, extra)
            else:
                reply = self._generator.generate(context, extra, tone)
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
        reading = self._reading_seconds(unanswered)
        thinking = self._rng.uniform(*self._delay) if self._delay[1] > 0 else 0.0
        parts = split_reply(reply, tone)
        plans = [self._typing_plan(part) for part in parts]
        gaps = [self._rng.uniform(*BETWEEN_PARTS_S) for _ in parts[1:]]
        typing_s = sum(
            (p.start_pause_ms + p.typing_ms + p.enter_pause_ms) / 1000 for p in plans if p
        ) + sum(gaps)
        log.info(
            "%s: reading %.1f s, thinking %.1f s, then typing %d characters in %d message(s) "
            "(about %.1f s)",
            title,
            reading,
            thinking,
            len(reply),
            len(parts),
            typing_s,
        )
        if self._dry_run:
            self._dry_seen.add((chat_id, pending.wa_id))
            if len(parts) > 1 and self._log_messages:
                for number, part in enumerate(parts, start=1):
                    log.info("  message %d of %d: %s", number, len(parts), part)
            log.info("%s: dry run, nothing sent", title)
            return reply
        self._sleep(reading + thinking)
        for index, (part, plan) in enumerate(zip(parts, plans, strict=True)):
            if index:
                self._sleep(gaps[index - 1])
            self._store.record_bot_text(chat_id, part)
            self._client.send(part, plan)
            if index == 0:
                # Marked after the first part, so a failure halfway never repeats the reply.
                self._store.mark_replied(chat_id, pending.wa_id)
        log.info("%s: sent%s", title, f" {len(parts)} messages" if len(parts) > 1 else "")
        self._sent_at[chat_id].append(self._clock())
        return reply
