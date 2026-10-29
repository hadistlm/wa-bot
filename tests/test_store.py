from wabot.models import Message
from wabot.store import Store


def msg(i, out=False, sender="A"):
    return Message(f"id{i}", sender, f"t{i}", "ts", out)


def test_upsert_idempotent_and_ordered():
    with Store(":memory:") as s:
        c = s.chat_id("Budi")
        s.upsert_messages(c, [msg(1), msg(2), msg(3)])
        s.upsert_messages(c, [msg(2), msg(3), msg(4)])
        assert [m.wa_id for m in s.recent(c, 3)] == ["id2", "id3", "id4"]
        assert len(s.recent(c, 10)) == 4


def test_pending_and_replied():
    with Store(":memory:") as s:
        c = s.chat_id("Budi")
        s.upsert_messages(c, [msg(1)])
        assert s.pending_incoming(c).wa_id == "id1"
        s.mark_replied(c, "id1")
        assert s.pending_incoming(c) is None
        s.upsert_messages(c, [msg(2, out=True)])
        assert s.pending_incoming(c) is None


def test_chat_id_stable():
    with Store(":memory:") as s:
        assert s.chat_id("X") == s.chat_id("X") != s.chat_id("Y")


def test_bot_text_claimed_vs_hand_typed():
    with Store(":memory:") as s:
        c = s.chat_id("Budi")
        s.record_bot_text(c, "auto reply")
        s.upsert_messages(c, [msg(1, out=True, sender="Me")])  # text "t1": hand typed
        s.upsert_messages(c, [Message("id2", "Me", "auto reply", "ts", True)])
        assert s.own_examples(c) == ["t1"]


def test_incoming_texts_excludes_outgoing():
    with Store(":memory:") as s:
        c = s.chat_id("Budi")
        s.upsert_messages(c, [msg(1), msg(2, out=True), msg(3)])
        assert s.incoming_texts(c) == ["t1", "t3"]


def test_migrates_v1_db(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE chats (id INTEGER PRIMARY KEY, title TEXT UNIQUE, last_seen_at TEXT);"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, chat_id INTEGER, wa_id TEXT, sender TEXT,"
        " text TEXT, sent_at TEXT, outgoing INTEGER, replied INTEGER DEFAULT 0, reply_error TEXT,"
        " UNIQUE(chat_id, wa_id));"
    )
    conn.commit()
    conn.close()
    with Store(path) as s:
        c = s.chat_id("X")
        s.upsert_messages(c, [msg(1, out=True)])
        assert s.own_examples(c) == ["t1"]
