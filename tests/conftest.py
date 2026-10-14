import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import PipelineConfig  # noqa: E402
from models import InboundEmail  # noqa: E402


@pytest.fixture
def base_config():
    return PipelineConfig(
        openai_api_key="test-key",
        webhook_secret="s3cret",
        auto_reply_enabled=True,
    )


@pytest.fixture
def make_email():
    def _make(
        body="Looking for a 2 bedroom in Henderson, budget $1800",
        sender_email="sarah@example.com",
        sender_name="Sarah Johnson",
        subject="2BR please",
        message_id="msg-1",
        thread_id="thr-1",
    ):
        return InboundEmail(
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            body_html="",
            body_plain=body,
            received_at=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
            thread_id=thread_id,
            message_id=message_id,
        )

    return _make
