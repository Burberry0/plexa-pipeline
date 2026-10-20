"""
Plexa Housing — Tier Classification
Pure Python tier classifier. No I/O. No AI calls.
Deterministic function of the ExtractedLead dataclass.
"""

import logging
from models import ExtractedLead, LeadStatus, Tier

logger = logging.getLogger("plexa.validation")


def classify_tier(lead: ExtractedLead) -> Tier:
    """
    Classify an extracted lead into Tier 1, 2, or 3.

    Gate fields: zip_code, bedrooms, move_in_date (ExtractedLead.GATE_FIELDS)
      - All three must be non-null for Tier 1 or 2. This is also the
        match-ready test: Tier 1/2 leads can be sent to property matching.

    Bonus fields: budget_min, budget_max, pets, occupants, duration_months, bathrooms
      - One or more present → Tier 1 (instead of Tier 2).

    Tier 1: Gate fields + at least one bonus field → match immediately.
    Tier 2: Gate fields only → match + soft follow-up.
    Tier 3: Missing gate field(s) → hold, ask for the missing ones.
    """
    if not lead.has_gate_fields:
        missing = lead.missing_gate_fields
        logger.info(f"Tier 3 — missing gate fields: {missing}")
        return Tier.TIER_3

    if lead.bonus_count >= 1:
        logger.info(
            f"Tier 1 — gate fields present + {lead.bonus_count} bonus field(s)"
        )
        return Tier.TIER_1

    logger.info("Tier 2 — gate fields present, no bonus fields")
    return Tier.TIER_2


MAX_QUESTION_VALUE_CHARS = 80

GATE_QUESTIONS = {
    "zip_code": "Which ZIP code (or a couple of ZIP codes) should we search in? We currently serve the Las Vegas area.",
    "bedrooms": "How many bedrooms do you need? (Studio, 1BR, 2BR, etc.)",
    "move_in_date": "When are you looking to move in? (A date or \"ASAP\" both work.)",
}


def _clip(text: str) -> str:
    text = str(text)
    return text if len(text) <= MAX_QUESTION_VALUE_CHARS else text[:MAX_QUESTION_VALUE_CHARS] + "\u2026"


def gate_questions(lead: ExtractedLead) -> list:
    """One question per missing gate field, in GATE_FIELDS order (Tier 3 must-ask)."""
    questions = []
    for f in lead.missing_gate_fields:
        if f == "zip_code" and lead.location:
            questions.append(
                f"You mentioned {_clip(lead.location)} — which ZIP code (or a couple of ZIP codes) should we search in?"
            )
        else:
            questions.append(GATE_QUESTIONS[f])
    return questions


def bonus_questions(lead: ExtractedLead) -> list:
    """Soft asks, most impactful first (Tier 2 sends the first one)."""
    questions = []
    if lead.budget_min is None and lead.budget_max is None:
        questions.append("Do you have a monthly budget range in mind?")
    if lead.pets is None:
        questions.append("Will you have any pets?")
    if lead.occupants is None:
        questions.append("How many people will be living in the unit?")
    return questions


def get_missing_field_questions(lead: ExtractedLead) -> list:
    """Gate questions first, then soft asks."""
    return gate_questions(lead) + bonus_questions(lead)


def tier_summary(tier: Tier, lead: ExtractedLead) -> dict:
    """Generate a human-readable tier summary for demo/logging."""
    summary = {
        "tier": tier.value,
        "gate_fields_present": lead.has_gate_fields,
        "bonus_field_count": lead.bonus_count,
        "missing_gate_fields": lead.missing_gate_fields,
        "confidence": lead.confidence,
    }

    if tier == Tier.TIER_1:
        summary["action"] = "Match-ready. Sent to property matching on approval. Full confirmation sent."
    elif tier == Tier.TIER_2:
        summary["action"] = "Match-ready. Sent to property matching on approval. Soft follow-up question sent."
        summary["follow_up_questions"] = bonus_questions(lead)[:1]
    elif tier == Tier.TIER_3:
        summary["action"] = "Lead held. Asking for missing gate fields."
        summary["follow_up_questions"] = gate_questions(lead)

    return summary


# Every extracted value merges (new non-null wins); only the bookkeeping fields are recomputed.
NON_MERGEABLE_FIELDS = ("confidence", "missing_fields", "notes")
MERGEABLE_FIELDS = tuple(f for f in ExtractedLead.__dataclass_fields__ if f not in NON_MERGEABLE_FIELDS)


def lead_has_pets(lead: ExtractedLead) -> bool:
    """True when the lead indicates at least one pet (empty pets=[] is not pets)."""
    if isinstance(lead.pets, list) and len(lead.pets) > 0:
        return True
    if lead.pet_count is not None and lead.pet_count > 0:
        return True
    if isinstance(lead.pet_details, list) and len(lead.pet_details) > 0:
        return True
    return False


def ensure_pet_friendly_required(lead: ExtractedLead) -> ExtractedLead:
    """If the renter has pets, pet_friendly_required must be true on the response."""
    if lead_has_pets(lead):
        lead.pet_friendly_required = True
    return lead


def merge_leads(prior: ExtractedLead, new: ExtractedLead) -> ExtractedLead:
    """
    Merge a new extraction over a prior one for the same sender.
    New non-null values win (pets=[] is a value). Prior fills gaps.
    """
    merged = {}
    for f in MERGEABLE_FIELDS:
        new_val = getattr(new, f)
        merged[f] = new_val if new_val is not None else getattr(prior, f)

    notes = [n for n in (prior.notes, new.notes) if n]
    notes = list(dict.fromkeys(notes))  # dedupe, keep order
    missing = [m for m in new.missing_fields if merged.get(m) is None]

    return ensure_pet_friendly_required(ExtractedLead(
        **merged,
        confidence=max(prior.confidence, new.confidence),
        missing_fields=missing,
        notes=" | ".join(notes) if notes else None,
    ))


def status_for_tier(tier: Tier) -> LeadStatus:
    if tier == Tier.TIER_1:
        return LeadStatus.NEW
    if tier == Tier.TIER_2:
        return LeadStatus.NEEDS_REVIEW
    return LeadStatus.ON_HOLD
