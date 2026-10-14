"""
Plexa Housing — Canonical Data Models
All data shapes used across the pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime, timezone


class Tier(Enum):
    TIER_1 = "Tier 1"  # Gate + bonus fields → auto-match
    TIER_2 = "Tier 2"  # Gate fields only → match + soft ask
    TIER_3 = "Tier 3"  # Missing gate fields → hold + ask


class LeadStatus(Enum):
    NEW = "New"
    NEEDS_REVIEW = "Needs Review"
    ON_HOLD = "On Hold"
    MANUAL_REVIEW = "Manual Review"
    MATCHED = "Matched"


class Classification(Enum):
    LEAD = "LEAD"
    JUNK = "JUNK"


@dataclass
class InboundEmail:
    """Raw email after ingestion normalization."""
    sender_email: str
    sender_name: str
    subject: str
    body_html: str
    body_plain: str  # stripped plaintext
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    is_reply: bool = False

    @property
    def first_name(self) -> str:
        """Extract first name from sender_name. Handles 'First Last' and 'Last, First'."""
        if not self.sender_name or not self.sender_name.strip():
            return "there"
        name = self.sender_name.strip()
        if "," in name:
            parts = [p.strip() for p in name.split(",")]
            return parts[1].split()[0] if len(parts) > 1 and parts[1] else parts[0]
        return name.split()[0]


@dataclass
class ExtractedLead:
    """Structured data extracted from a lead email by the extraction model."""
    location: Optional[str] = None
    bedrooms: Optional[int] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    move_in_date: Optional[str] = None
    pets: Optional[list] = None
    occupants: Optional[int] = None
    duration_months: Optional[int] = None
    pet_friendly_required: Optional[bool] = None
    confidence: float = 0.0
    missing_fields: list = field(default_factory=list)
    notes: Optional[str] = None

    # Gate fields
    GATE_FIELDS = ("location", "bedrooms")

    # Bonus fields
    BONUS_FIELDS = (
        "budget_min", "budget_max", "move_in_date",
        "pets", "occupants", "duration_months"
    )

    @property
    def has_gate_fields(self) -> bool:
        return self.location is not None and self.bedrooms is not None

    @property
    def bonus_count(self) -> int:
        count = 0
        for f in self.BONUS_FIELDS:
            val = getattr(self, f)
            if val is not None:
                # pets=[] counts (explicitly stated 'no pets')
                if isinstance(val, list) or val:
                    count += 1
        return count

    @property
    def missing_gate_fields(self) -> list:
        missing = []
        if self.location is None:
            missing.append("location")
        if self.bedrooms is None:
            missing.append("bedrooms")
        return missing


@dataclass
class PipelineResult:
    """Final output of the pipeline for one email."""
    email: InboundEmail
    classification: Classification
    extracted: Optional[ExtractedLead] = None
    tier: Optional[Tier] = None
    status: LeadStatus = LeadStatus.NEW
    is_upgrade: bool = False
    is_duplicate: bool = False
    airtable_record_id: Optional[str] = None
    reply_subject: Optional[str] = None
    reply_html: Optional[str] = None
    should_reply: bool = False
    reply_skip_reason: Optional[str] = None
    error: Optional[str] = None
    processing_time_ms: float = 0.0

    # Cost tracking
    junk_filter_tokens: int = 0
    extraction_tokens: int = 0

    @property
    def is_lead(self) -> bool:
        return self.classification == Classification.LEAD

    @property
    def total_tokens(self) -> int:
        return self.junk_filter_tokens + self.extraction_tokens

    def to_dict(self) -> dict:
        """Serialize for API/demo output."""
        result = {
            "sender": f"{self.email.sender_name} <{self.email.sender_email}>",
            "subject": self.email.subject,
            "email": {
                "sender_email": self.email.sender_email,
                "sender_name": self.email.sender_name,
                "subject": self.email.subject,
                "message_id": self.email.message_id,
                "thread_id": self.email.thread_id,
            },
            "classification": self.classification.value,
            "is_duplicate": self.is_duplicate,
            "is_upgrade": self.is_upgrade,
            "processing_time_ms": round(self.processing_time_ms, 1),
            "tokens": {
                "junk_filter": self.junk_filter_tokens,
                "extraction": self.extraction_tokens,
                "total": self.total_tokens,
            },
        }
        if self.extracted:
            result["extraction"] = {
                "location": self.extracted.location,
                "bedrooms": self.extracted.bedrooms,
                "budget_min": self.extracted.budget_min,
                "budget_max": self.extracted.budget_max,
                "move_in_date": self.extracted.move_in_date,
                "pets": self.extracted.pets,
                "occupants": self.extracted.occupants,
                "duration_months": self.extracted.duration_months,
                "pet_friendly_required": self.extracted.pet_friendly_required,
                "confidence": self.extracted.confidence,
                "missing_fields": self.extracted.missing_fields,
                "notes": self.extracted.notes,
            }
        if self.tier:
            result["tier"] = self.tier.value
        result["status"] = self.status.value
        result["reply"] = {
            "should_send": self.should_reply,
            "skip_reason": self.reply_skip_reason,
            "subject": self.reply_subject,
            "html": self.reply_html,
        }
        if self.airtable_record_id:
            result["airtable_record_id"] = self.airtable_record_id
        if self.error:
            result["error"] = self.error
        return result
