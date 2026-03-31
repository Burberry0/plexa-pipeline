"""
Plexa Housing — Configuration
Frozen dataclass. All secrets from environment variables.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineConfig:
    """Immutable pipeline configuration. All secrets from env vars."""

    # Anthropic
    anthropic_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""

    # Models
    junk_filter_model: str = "gpt-4o-mini"
    extraction_model: str = "gpt-4o"
    junk_filter_max_tokens: int = 50
    extraction_max_tokens: int = 1024

    # Airtable
    airtable_api_key: str = ""
    airtable_base_id: str = ""
    airtable_leads_table: str = "Leads"

    # Gmail
    gmail_sender_address: str = ""
    gmail_sender_name: str = "Ryan"
    gmail_credentials_path: str = "credentials.json"
    gmail_token_path: str = "token.json"

    # Auto-reply guardrails
    max_auto_replies: int = 2
    reply_cooldown_minutes: int = 5

    # Ingestion
    ingestion_mode: str = "polling"  # "polling" or "webhook"
    poll_interval_seconds: int = 60
    port: int = 5000

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        """Build config from environment variables with sane defaults."""
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            junk_filter_model=os.getenv("JUNK_FILTER_MODEL", "gpt-4o-mini"),
            extraction_model=os.getenv("EXTRACTION_MODEL", "gpt-4o"),
            junk_filter_max_tokens=int(os.getenv("JUNK_FILTER_MAX_TOKENS", "50")),
            extraction_max_tokens=int(os.getenv("EXTRACTION_MAX_TOKENS", "1024")),
            airtable_api_key=os.getenv("AIRTABLE_API_KEY", ""),
            airtable_base_id=os.getenv("AIRTABLE_BASE_ID", ""),
            airtable_leads_table=os.getenv("AIRTABLE_LEADS_TABLE", "Leads"),
            gmail_sender_address=os.getenv("GMAIL_SENDER_ADDRESS", ""),
            gmail_sender_name=os.getenv("GMAIL_SENDER_NAME", "Ryan"),
            gmail_credentials_path=os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json"),
            gmail_token_path=os.getenv("GMAIL_TOKEN_PATH", "token.json"),
            max_auto_replies=int(os.getenv("MAX_AUTO_REPLIES", "2")),
            reply_cooldown_minutes=int(os.getenv("REPLY_COOLDOWN_MINUTES", "5")),
            ingestion_mode=os.getenv("INGESTION_MODE", "polling"),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "60")),
            port=int(os.getenv("PORT", "5000")),
        )

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_airtable_config(self) -> bool:
        return bool(self.airtable_api_key and self.airtable_base_id)

    @property
    def has_gmail_config(self) -> bool:
        return bool(self.gmail_sender_address)
