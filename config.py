"""
Plexa Housing — Configuration
Frozen dataclass. All secrets from environment variables.
"""

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class PipelineConfig:
    """Immutable pipeline configuration. All secrets from env vars."""

    # OpenAI
    openai_api_key: str = ""
    junk_filter_model: str = "gpt-4o-mini"
    extraction_model: str = "gpt-4o"
    junk_filter_max_tokens: int = 50
    extraction_max_tokens: int = 1024
    openai_timeout_seconds: float = 20.0
    openai_max_retries: int = 1

    # Airtable
    airtable_api_key: str = ""
    airtable_base_id: str = ""
    airtable_leads_table: str = "Leads"
    airtable_messages_table: str = "Messages"

    # Auto-reply guardrails
    auto_reply_enabled: bool = False
    max_auto_replies: int = 2
    reply_cooldown_minutes: int = 5

    # Alerts
    alert_webhook_url: str = ""

    # Server
    webhook_secret: str = ""
    allowed_origin: str = ""
    port: int = 5000

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        """Build config from environment variables with sane defaults."""
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            junk_filter_model=os.getenv("JUNK_FILTER_MODEL", "gpt-4o-mini"),
            extraction_model=os.getenv("EXTRACTION_MODEL", "gpt-4o"),
            junk_filter_max_tokens=int(os.getenv("JUNK_FILTER_MAX_TOKENS", "50")),
            extraction_max_tokens=int(os.getenv("EXTRACTION_MAX_TOKENS", "1024")),
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

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_airtable_config(self) -> bool:
        return bool(self.airtable_api_key and self.airtable_base_id)

    @property
    def has_webhook_secret(self) -> bool:
        return bool(self.webhook_secret)
