from types import SimpleNamespace

import pytest
from google.genai import errors

from wabot.llm import FatalReplyError, GeminiReplyGenerator, ReplyError, format_context
from wabot.models import Message

CTX = [Message("1", "Budi", "hi", "ts", False)]


def gen(responses):
    g = GeminiReplyGenerator("k", "m", "sys", sleep=lambda _: None)
    it = iter(responses)

    def fake(**_):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(text=r)

    g._client = SimpleNamespace(models=SimpleNamespace(generate_content=fake))
    return g


def test_format_context():
    assert format_context(CTX) == "Budi: hi"


def test_returns_text_after_empty():
    assert gen([None, " hey "]).generate(CTX) == "hey"


def test_server_error_retries_then_raises():
    err = errors.ServerError(500, {"error": {"message": "x"}})
    with pytest.raises(ReplyError):
        gen([err, err, err]).generate(CTX)


def test_not_found_is_fatal():
    err = errors.ClientError(404, {"error": {"message": "no model"}})
    with pytest.raises(FatalReplyError):
        gen([err]).generate(CTX)
