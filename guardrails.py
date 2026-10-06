"""
Plexa Housing — Auto-reply guardrails
Pure decision logic. State comes from the Airtable Leads record.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Union


@dataclass(frozen=True)
class ReplyDecision:
    should_reply: bool
    reason: str


def parse_airtable_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def decide_reply(
    *,
    enabled: bool,
    reply_count: int,
    last_reply_at: Union[str, datetime, None],
    max_replies: int,
    cooldown_minutes: int,
    now: datetime,
) -> ReplyDecision:
    if not enabled:
        return ReplyDecision(False, "auto_reply_disabled")
    if (reply_count or 0) >= max_replies:
        return ReplyDecision(False, "max_replies_reached")
    last = parse_airtable_datetime(last_reply_at)
    if last is not None and now - last < timedelta(minutes=cooldown_minutes):
        return ReplyDecision(False, "cooldown_active")
    return ReplyDecision(True, "ok")
