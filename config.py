"""
Plexa Housing — Configuration
Frozen dataclass. All secrets from environment variables (a local .env is
loaded if present; real environment variables always win).
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

OPENCODE_DEFAULT_BASE_URL = "https://opencode.ai/inference/go/v1"
RESPONSE_FORMATS = ("json_schema", "json_object", "none")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class PipelineConfig:
    """Immutable pipeline configuration. All secrets from env vars."""

    # AI provider. OPENCODE_API_KEY present → OpenCode Go (OpenAI-compatible);
    # otherwise OPENAI_API_KEY → api.openai.com.
    openai_api_key: str = field(default="", repr=False)
    opencode_api_key: str = field(default="", repr=False)
    opencode_base_url: str = OPENCODE_DEFAULT_BASE_URL
    ai_user_agent: str = "plexa-pipeline/1.0"
    junk_filter_model: str = "gpt-4o-mini"
    extraction_model: str = "gpt-4o"
    junk_filter_max_tokens: int = 512
    extraction_max_tokens: int = 4096
    extraction_response_format: str = "json_schema"  # json_schema | json_object | none
    openai_timeout_seconds: float = 20.0
    openai_max_retries: int = 1

    # Airtable
    airtable_api_key: str = field(default="", repr=False)
    airtable_base_id: str = ""
    airtable_leads_table: str = "Leads"
    airtable_messages_table: str = "Messages"

    # Auto-reply guardrails
    auto_reply_enabled: bool = False
    max_auto_replies: int = 2
    reply_cooldown_minutes: int = 5

    # Alerts
    alert_webhook_url: str = field(default="", repr=False)

    # Server
    webhook_secret: str = field(default="", repr=False)
    allowed_origin: str = ""
    port: int = 5000

    def __post_init__(self):
        if self.extraction_response_format not in RESPONSE_FORMATS:
            raise ValueError(
                f"EXTRACTION_RESPONSE_FORMAT must be one of {RESPONSE_FORMATS}, "
                f"got {self.extraction_response_format!r}"
            )

    @classmethod
    def from_env(cls, load_env_file: bool = True) -> "PipelineConfig":
        """Build config from environment variables with sane defaults.

        Loads the nearest `.env` (searching upward from this file) unless
        `load_env_file` is False. Variables already in the environment win.
        """
        if load_env_file:
            load_dotenv()
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            opencode_api_key=os.getenv("OPENCODE_API_KEY", ""),
            opencode_base_url=os.getenv("OPENCODE_BASE_URL", OPENCODE_DEFAULT_BASE_URL),
            ai_user_agent=os.getenv("AI_USER_AGENT", "plexa-pipeline/1.0"),
            junk_filter_model=os.getenv("JUNK_FILTER_MODEL", "gpt-4o-mini"),
            extraction_model=os.getenv("EXTRACTION_MODEL", "gpt-4o"),
            junk_filter_max_tokens=int(os.getenv("JUNK_FILTER_MAX_TOKENS", "512")),
            extraction_max_tokens=int(os.getenv("EXTRACTION_MAX_TOKENS", "4096")),
            extraction_response_format=os.getenv("EXTRACTION_RESPONSE_FORMAT", "json_schema").strip().lower(),
            openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20")),
            openai_max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "1")),
            airtable_api_key=os.getenv("AIRTABLE_API_KEY", ""),
            airtable_base_id=os.getenv("AIRTABLE_BASE_ID", ""),
            airtable_leads_table=os.getenv("AIRTABLE_LEADS_TABLE", "Leads"),
            airtable_messages_table=os.getenv("AIRTABLE_MESSAGES_TABLE", "Messages"),
            auto_reply_enabled=_env_bool("AUTO_REPLY_ENABLED", False),
            max_auto_replies=int(os.getenv("MAX_AUTO_REPLIES", "2")),
            reply_cooldown_minutes=int(os.getenv("REPLY_COOLDOWN_MINUTES", "5")),
            alert_webhook_url=os.getenv("ALERT_WEBHOOK_URL", ""),
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            allowed_origin=os.getenv("ALLOWED_ORIGIN", ""),
            port=int(os.getenv("PORT", "5000")),
        )

    # ── AI provider ──────────────────────────────────────────────────────

    @property
    def ai_provider(self) -> str:
        return "opencode" if self.opencode_api_key else "openai"

    @property
    def ai_api_key(self) -> str:
        return self.opencode_api_key or self.openai_api_key

    @property
    def ai_base_url(self) -> Optional[str]:
        """Base URL for the OpenAI SDK; None means the SDK default (api.openai.com)."""
        return self.opencode_base_url if self.ai_provider == "opencode" else None

    @property
    def has_ai_key(self) -> bool:
        return bool(self.ai_api_key)

    @property
    def has_airtable_config(self) -> bool:
        return bool(self.airtable_api_key and self.airtable_base_id)

    @property
    def has_webhook_secret(self) -> bool:
        return bool(self.webhook_secret)
