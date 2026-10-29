"""SQLite storage for chats and messages."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType
from typing import Self

from wabot.models import Message

SCHEMA_VERSION = 3
_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES chats(id),
    wa_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    outgoing INTEGER NOT NULL,
    replied INTEGER NOT NULL DEFAULT 0,
    reply_error TEXT,
    by_bot INTEGER NOT NULL DEFAULT 0,
    UNIQUE(chat_id, wa_id)
);
CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_texts (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(messages)")}
        if "by_bot" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN by_bot INTEGER NOT NULL DEFAULT 0")
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._conn.commit()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def get_state(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_state(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO bot_state(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def chat_id(self, title: str) -> int:
        self._conn.execute(
            "INSERT INTO chats(title, last_seen_at) VALUES (?, datetime('now')) "
            "ON CONFLICT(title) DO UPDATE SET last_seen_at=datetime('now')",
            (title,),
        )
        row = self._conn.execute("SELECT id FROM chats WHERE title=?", (title,)).fetchone()
        self._conn.commit()
        return int(row["id"])

    def upsert_messages(self, chat_id: int, messages: Iterable[Message]) -> None:
        """Insert unseen messages in DOM order. Insertion id gives conversation order.

        A new outgoing message whose text matches a recent bot reply is flagged by_bot.
        """
        for m in messages:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO messages(chat_id, wa_id, sender, text, sent_at, outgoing) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, m.wa_id, m.sender, m.text, m.sent_at, int(m.outgoing)),
            )
            if cur.rowcount == 1 and m.outgoing:
                self._claim_bot_text(chat_id, m)
        self._conn.commit()

    def _claim_bot_text(self, chat_id: int, m: Message) -> None:
        row = self._conn.execute(
            "SELECT id FROM bot_texts WHERE chat_id=? AND text=? "
            "AND created_at >= datetime('now', '-10 minutes') ORDER BY id LIMIT 1",
            (chat_id, m.text),
        ).fetchone()
        if row is None:
            return
        self._conn.execute("DELETE FROM bot_texts WHERE id=?", (row["id"],))
        self._conn.execute(
            "UPDATE messages SET by_bot=1 WHERE chat_id=? AND wa_id=?", (chat_id, m.wa_id)
        )

    def record_bot_text(self, chat_id: int, text: str) -> None:
        """Remember a reply we are about to send, so it can be told apart from your own."""
        self._conn.execute("INSERT INTO bot_texts(chat_id, text) VALUES (?, ?)", (chat_id, text))
        self._conn.execute("DELETE FROM bot_texts WHERE created_at < datetime('now', '-1 day')")
        self._conn.commit()

    def incoming_texts(self, chat_id: int, limit: int = 50) -> list[str]:
        rows = self._conn.execute(
            "SELECT text FROM messages WHERE chat_id=? AND outgoing=0 ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [r["text"] for r in reversed(rows)]

    def own_examples(self, chat_id: int, limit: int = 4) -> list[str]:
        """Your hand-typed messages in this chat, oldest first."""
        rows = self._conn.execute(
            "SELECT text FROM messages WHERE chat_id=? AND outgoing=1 AND by_bot=0 "
            "AND text != '[media]' ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [r["text"] for r in reversed(rows)]

    def find_chat_id(self, title: str) -> int | None:
        row = self._conn.execute("SELECT id FROM chats WHERE title=?", (title,)).fetchone()
        return None if row is None else int(row["id"])

    def chats_with_pending(self) -> list[tuple[int, str, str]]:
        """(chat_id, title, wa_id) for chats whose newest message is incoming and unanswered."""
        rows = self._conn.execute(
            "SELECT c.id, c.title, m.wa_id FROM chats c JOIN messages m "
            "ON m.id = (SELECT MAX(id) FROM messages WHERE chat_id = c.id) "
            "WHERE m.outgoing = 0 AND m.replied = 0 ORDER BY m.id"
        ).fetchall()
        return [(int(r["id"]), r["title"], r["wa_id"]) for r in rows]

    def recent(self, chat_id: int, limit: int) -> list[Message]:
        rows = self._conn.execute(
            "SELECT wa_id, sender, text, sent_at, outgoing FROM messages "
            "WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [
            Message(r["wa_id"], r["sender"], r["text"], r["sent_at"], bool(r["outgoing"]))
            for r in reversed(rows)
        ]

    def pending_incoming(self, chat_id: int) -> Message | None:
        """Newest message, if it is incoming and not yet replied."""
        row = self._conn.execute(
            "SELECT wa_id, sender, text, sent_at, outgoing, replied FROM messages "
            "WHERE chat_id=? ORDER BY id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
        if row is None or row["outgoing"] or row["replied"]:
            return None
        return Message(row["wa_id"], row["sender"], row["text"], row["sent_at"], False)

    def mark_replied(self, chat_id: int, wa_id: str) -> None:
        self._conn.execute(
            "UPDATE messages SET replied=1, reply_error=NULL WHERE chat_id=? AND wa_id=?",
            (chat_id, wa_id),
        )
        self._conn.commit()

    def record_error(self, chat_id: int, wa_id: str, error: str) -> None:
        self._conn.execute(
            "UPDATE messages SET reply_error=? WHERE chat_id=? AND wa_id=?",
            (error, chat_id, wa_id),
        )
        self._conn.commit()
