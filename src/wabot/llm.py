"""Reply generation via Gemini."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Protocol

from google import genai
from google.genai import errors, types

from wabot.models import Message
from wabot.tone import Tone

log = logging.getLogger(__name__)


class ReplyError(Exception):
    """Retryable failure producing a reply."""


class FatalReplyError(Exception):
    """Misconfiguration (bad key or model). Retrying will not help."""


class ReplyGenerator(Protocol):
    def generate(
        self, context: Sequence[Message], extra: str = "", tone: Tone | None = None
    ) -> str: ...


def format_context(context: Sequence[Message]) -> str:
    return "\n".join(f"{m.sender}: {m.text}" for m in context)


class GeminiReplyGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        system_instruction: str,
        temperature: float = 0.8,
        max_output_tokens: int = 300,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._retries = retries
        self._sleep = sleep
        self._system_instruction = system_instruction
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens

    def system_instruction(self, extra: str = "", tone: Tone | None = None) -> str:
        """The prompt for one call.

        With a tone the order is: priority rules, persona, chat notes, reminder. The rules sit
        above the persona and say they win, so nothing in the persona can shorten the reply.
        """
        if tone is None:
            return f"{self._system_instruction}\n\n{extra}".strip()
        sections = [
            tone.rules,
            f"PERSONA\n{self._system_instruction}",
            f"CHAT NOTES\n{extra}" if extra else "",
            tone.reminder,
        ]
        return "\n\n".join(s for s in sections if s)

    def generate(
        self, context: Sequence[Message], extra: str = "", tone: Tone | None = None
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=self.system_instruction(extra, tone),
            temperature=self._temperature,
            max_output_tokens=max(self._max_output_tokens, tone.max_output_tokens)
            if tone
            else self._max_output_tokens,
        )
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = self._client.models.generate_content(
                    model=self._model, contents=format_context(context), config=config
                )
            except errors.ClientError as exc:
                if exc.code in (400, 401, 403, 404):
                    raise FatalReplyError(f"{self._model}: {exc}") from exc
                last = exc
            except errors.APIError as exc:
                last = exc
            else:
                text = (response.text or "").strip()
                if text:
                    return text
                last = ReplyError("empty response")
            log.warning("gemini attempt %d failed: %s", attempt + 1, last)
            self._sleep(2**attempt)
        raise ReplyError(str(last))
