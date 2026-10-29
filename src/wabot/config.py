from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from wabot.matching import parse_allowlist

DEFAULT_PERSONA = "You are {name}. Reply naturally and briefly."
OUTPUT_RULES = "\n\nOutput only the next message text. Do not include timestamps or sender names."


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    gemini_api_key: SecretStr
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.8
    gemini_max_output_tokens: int = 300

    persona_name: str = "Me"
    persona_file: Path = Path("persona.md")
    persona_prompt: str = ""

    allowed_chats: str = ""
    allow_groups: bool = False
    match_threshold: float = Field(0.85, ge=0.0, le=1.0)

    context_messages: int = Field(5, ge=1, le=50)
    poll_interval: float = Field(4.0, gt=0)
    reply_delay_min: float = Field(2.0, ge=0)
    reply_delay_max: float = Field(6.0, ge=0)
    db_path: Path = Path("wabot.db")
    profile_dir: Path = Path(".wa-profile")
    browser_channel: str = ""

    skip_trivial: bool = True
    debounce: bool = True
    max_replies_per_hour: int = Field(20, ge=1)

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
