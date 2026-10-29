from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from wabot.matching import parse_allowlist
from wabot.quiet import QuietHours, parse_quiet_hours

DEFAULT_PERSONA = "You are {name}. Reply naturally and briefly."
OUTPUT_RULES = "\n\nOutput only the next message text. Do not include timestamps or sender names."


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.8
    gemini_max_output_tokens: int = 300

    persona_name: str = "Me"
    own_names: str = ""
    persona_file: Path = Path("persona.md")
    persona_prompt: str = ""

    allowed_chats: str = ""
    allow_groups: bool = False
    match_threshold: float = Field(0.85, ge=0.0, le=1.0)

    context_messages: int = Field(5, ge=1, le=50)
    poll_interval: float = Field(4.0, gt=0)
    reply_delay_min: float = Field(4.0, ge=0)
    reply_delay_max: float = Field(12.0, ge=0)
    db_path: Path = Path("data/wabot.db")
    profile_dir: Path = Path("data/profile")
    browser_channel: str = ""

    quiet_hours: str = ""
    typing_char_delay_ms: float = Field(200.0, ge=0)
    typing_jitter: float = Field(0.4, ge=0.0, le=1.0)
    max_typing_seconds: float = Field(30.0, gt=0)
    read_seconds_per_word: float = Field(0.25, ge=0)
    log_messages: bool = True
    afk_chance: float = Field(0.1, ge=0.0, le=1.0)
    afk_min_minutes: float = Field(3.0, ge=0)
    afk_max_minutes: float = Field(20.0, ge=0)
    afk_acknowledge: bool = False
    afk_ack_min_minutes: float = Field(5.0, ge=0)
    skip_backlog: bool = True
    watch_mode: Literal["list", "open"] = "list"
    open_delay_min: float = Field(1.0, ge=0)
    open_delay_max: float = Field(4.0, ge=0)
    reply_gap_min: float = Field(15.0, ge=0)
    reply_gap_max: float = Field(45.0, ge=0)
    headless: bool = False
    chromium_sandbox: bool = True
    heartbeat_minutes: float = Field(5.0, ge=0)
    skip_trivial: bool = True
    debounce: bool = True
    max_replies_per_hour: int = Field(20, ge=1)

    @property
    def quiet(self) -> QuietHours | None:
        return parse_quiet_hours(self.quiet_hours)

    @property
    def allowlist(self) -> tuple[str, ...]:
        return tuple(parse_allowlist(self.allowed_chats))

    @property
    def chat_tags(self) -> dict[str, str | None]:
        return parse_allowlist(self.allowed_chats)

    def system_instruction(self) -> str:
        """Persona text with `{name}` filled in. File beats env var."""
        if self.persona_file.is_file():
            base = self.persona_file.read_text(encoding="utf-8")
        else:
            base = self.persona_prompt or DEFAULT_PERSONA
        return base.replace("{name}", self.persona_name).strip() + OUTPUT_RULES
