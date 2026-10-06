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

    Gate fields: location, bedrooms
      - Both must be non-null for Tier 1 or 2.

    Bonus fields: budget_min, budget_max, move_in_date, pets, occupants, duration_months
      - One or more present → Tier 1 (instead of Tier 2).

    Tier 1: Both gate fields + at least one bonus field → auto-match immediately.
    Tier 2: Both gate fields, no bonus fields → match + soft follow-up.
    Tier 3: Missing gate field(s) → hold, ask for missing info.
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


def get_missing_field_questions(lead: ExtractedLead) -> list:
    """
    Generate follow-up questions for missing fields.
    Used in Tier 2 (soft ask) and Tier 3 (gate ask) templates.
    """
    questions = []

    # Gate field questions (Tier 3 — must ask)
    if lead.location is None:
        questions.append(
            "What area of Las Vegas are you looking in? "
            "(City, neighborhood, or zip code all work.)"
        )
    if lead.bedrooms is None:
        questions.append(
            "How many bedrooms do you need? "
            "(Studio, 1BR, 2BR, etc.)"
        )

    # Bonus field questions (Tier 2 — soft ask, pick most impactful)
    if lead.budget_min is None and lead.budget_max is None:
        questions.append(
            "Do you have a monthly budget range in mind?"
        )
    if lead.move_in_date is None:
        questions.append(
            "When are you looking to move in?"
        )
    if lead.pets is None:
        questions.append(
            "Will you have any pets?"
        )
    if lead.occupants is None:
        questions.append(
            "How many people will be living in the unit?"
        )

    return questions


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
        summary["action"] = "Auto-match runs immediately. Full confirmation sent."
    elif tier == Tier.TIER_2:
        summary["action"] = "Match runs with flag. Soft follow-up question sent."
        summary["follow_up_questions"] = get_missing_field_questions(lead)[:1]
    elif tier == Tier.TIER_3:
        summary["action"] = "Lead held. Asking for missing gate fields."
        summary["follow_up_questions"] = [
            q for q in get_missing_field_questions(lead)
            if any(gf in q.lower() for gf in ["area", "bedroom"])
        ]

    return summary


MERGEABLE_FIELDS = (
    "location", "bedrooms", "budget_min", "budget_max", "move_in_date",
    "pets", "occupants", "duration_months", "pet_friendly_required",
)


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

    return ExtractedLead(
        **merged,
        confidence=max(prior.confidence, new.confidence),
        missing_fields=missing,
        notes=" | ".join(notes) if notes else None,
    )


def status_for_tier(tier: Tier) -> LeadStatus:
    if tier == Tier.TIER_1:
        return LeadStatus.NEW
    if tier == Tier.TIER_2:
        return LeadStatus.NEEDS_REVIEW
    return LeadStatus.ON_HOLD
