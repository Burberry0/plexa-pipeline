"""
Plexa Housing — Canonical Data Models
All data shapes used across the pipeline.
"""

from dataclasses import asdict, dataclass, field
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


def split_name(sender_name) -> tuple:
    """Split a display name into (first, last). Handles 'First Last', 'First Middle Last'
    (middle goes with last) and 'Last, First'. Empty input gives ("", "")."""
    name = (sender_name or "").strip()
    if not name:
        return "", ""
    if "," in name:
        last, _, first = (p.strip() for p in name.partition(","))
        return (first.split()[0] if first else ""), last
    parts = name.split()
    return parts[0], " ".join(parts[1:])


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
    # Property-matching inputs (see match_request.py)
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    bathrooms: Optional[float] = None
    square_feet: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    pet_count: Optional[int] = None
    pet_details: Optional[list] = None  # [{"type": "Dog"|"Cat"|"Other", "description": str|None}]
    garage_required: Optional[bool] = None
    garage_spaces: Optional[int] = None
    amenities: Optional[list] = None  # JotForm amenity labels; [] = none requested
    special_requests: Optional[str] = None
    requester_type: Optional[str] = None  # "Individual" | "Company"
    company_name: Optional[str] = None
    confidence: float = 0.0
    missing_fields: list = field(default_factory=list)
    notes: Optional[str] = None

    # Gate fields: the minimum the property-matching workflow needs. All three
    # present ⇔ match-ready ⇔ Tier 1 or 2. "ASAP" counts as a move-in date.
    GATE_FIELDS = ("zip_code", "bedrooms", "move_in_date")

    # Bonus fields: any one of these lifts a match-ready lead to Tier 1.
    # `location` is excluded because a bare zip is copied into it as well.
    BONUS_FIELDS = (
        "budget_min", "budget_max", "pets", "occupants", "duration_months", "bathrooms",
    )

    @property
    def has_gate_fields(self) -> bool:
        return all(getattr(self, f) is not None for f in self.GATE_FIELDS)

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
        return [f for f in self.GATE_FIELDS if getattr(self, f) is None]


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
    match_request: Optional[dict] = None  # Readable match body; set only when match-ready
    # Partner enrichment from Airtable Partners (email, then domain). Always set for LEADs.
    partner_known: bool = False
    partner_inventory_tier: Optional[str] = None  # Full | Snap
    partner_vendor: Optional[str] = None
    partner_matched_by: Optional[str] = None  # email | domain
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

    @property
    def match_ready(self) -> bool:
        # Failed runs clear match_request and must never look match-ready to n8n.
        if self.error:
            return False
        return self.extracted is not None and self.extracted.has_gate_fields

    @property
    def match_missing_fields(self) -> list:
        if self.error:
            return []
        return self.extracted.missing_gate_fields if self.extracted else []

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
            result["extraction"] = asdict(self.extracted)
        if self.tier:
            result["tier"] = self.tier.value
        result["status"] = self.status.value
        result["reply"] = {
            "should_send": self.should_reply,
            "skip_reason": self.reply_skip_reason,
            "subject": self.reply_subject,
            "html": self.reply_html,
        }
        # n8n branches on match.ready after Slack approval and POSTs match.request
        # to the property-matching workflow. Always present so the branch never sees undefined.
        result["match"] = {
            "ready": self.match_ready,
            "missing_fields": self.match_missing_fields,
            "request": self.match_request if self.match_ready else None,
        }
        # Always present so n8n Slack logs can branch without undefined checks.
        result["partner"] = {
            "known": self.partner_known,
            "inventory_tier": self.partner_inventory_tier,
            "vendor": self.partner_vendor,
            "matched_by": self.partner_matched_by,
        }
        if self.airtable_record_id:
            result["airtable_record_id"] = self.airtable_record_id
        if self.error:
            result["error"] = self.error
        return result
