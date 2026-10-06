"""
Plexa Housing — Ingestion Layer
Abstract adapter layer. Normalises all sources into InboundEmail.
"""

import re
import logging
from abc import ABC, abstractmethod
from html.parser import HTMLParser
from datetime import datetime, timezone
from typing import Optional

from models import InboundEmail

logger = logging.getLogger("plexa.ingestion")


# ── HTML → Plaintext Stripper ───────────────────────────────────────────────

class HTMLStripper(HTMLParser):
    """Custom HTML parser that strips to clean plaintext."""

    EXCLUDED_TAGS = {"script", "style", "head", "meta", "link"}
    BLOCK_TAGS = {"p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th"}

    def __init__(self):
        super().__init__()
        self._lines = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.EXCLUDED_TAGS:
            self._skip_depth += 1
        elif tag.lower() in self.BLOCK_TAGS and not self._skip_depth:
            self._lines.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self.EXCLUDED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag.lower() in self.BLOCK_TAGS and not self._skip_depth:
            self._lines.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._lines.append(data)

    def get_text(self) -> str:
        raw = "".join(self._lines)
        # Collapse consecutive blank lines
        cleaned = re.sub(r"\n{3,}", "\n\n", raw)
        return cleaned.strip()


def strip_html(html_body: str) -> str:
    """Strip HTML to clean plaintext. Critical for extraction quality."""
    if not html_body:
        return ""
    stripper = HTMLStripper()
    try:
        stripper.feed(html_body)
        return stripper.get_text()
    except Exception as e:
        logger.warning(f"HTML strip failed, falling back to regex: {e}")
        # Fallback: regex strip
        text = re.sub(r"<[^>]+>", " ", html_body)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


# ── Adapter Interface ───────────────────────────────────────────────────────

class EmailIngestionAdapter(ABC):
    """Abstract interface for email ingestion sources."""

    @abstractmethod
    def fetch_emails(self) -> list:
        """Fetch and return a list of InboundEmail objects."""
        ...

    @abstractmethod
    def mark_processed(self, email: InboundEmail) -> None:
        """Mark an email as processed so it is not re-fetched."""
        ...


# ── Direct Input Adapter (for demo / testing) ──────────────────────────────

class DirectInputAdapter(EmailIngestionAdapter):
    """
    Direct input adapter for testing and demos.
    Accepts raw email data and normalizes it.
    """

    def __init__(self):
        self._queue = []

    def add_email(
        self,
        sender_email: str,
        sender_name: str,
        subject: str,
        body: str,
        is_html: bool = False,
        thread_id: Optional[str] = None,
        is_reply: bool = False,
    ) -> InboundEmail:
        """Add an email to the processing queue."""
        body_html = body if is_html else ""
        body_plain = strip_html(body) if is_html else body

        email = InboundEmail(
            sender_email=sender_email,
            sender_name=sender_name,
            subject=subject,
            body_html=body_html,
            body_plain=body_plain,
            received_at=datetime.now(timezone.utc),
            thread_id=thread_id,
            is_reply=is_reply,
        )
        self._queue.append(email)
        return email

    def fetch_emails(self) -> list:
        emails = list(self._queue)
        self._queue.clear()
        return emails

    def mark_processed(self, email: InboundEmail) -> None:
        logger.debug(f"Marked processed: {email.sender_email}")


# ── Webhook Payload Parser ──────────────────────────────────────────────────

def parse_webhook_payload(payload: dict) -> InboundEmail:
    """Parse a JSON webhook payload (from n8n) into InboundEmail."""
    body_html = payload.get("body_html", "")
    body_plain = payload.get("body_plain", "") or strip_html(body_html)

    return InboundEmail(
        sender_email=payload.get("sender_email", "unknown@unknown.com"),
        sender_name=payload.get("sender_name", "Unknown"),
        subject=payload.get("subject", "(no subject)"),
        body_html=body_html,
        body_plain=body_plain,
        received_at=datetime.now(timezone.utc),
        thread_id=payload.get("thread_id"),
        message_id=payload.get("message_id"),
        is_reply=payload.get("is_reply", False),
    )
