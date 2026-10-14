import pytest

from models import ExtractedLead, Tier
from validation import classify_tier, get_missing_field_questions, tier_summary


@pytest.mark.parametrize(
    "lead,expected",
    [
        (ExtractedLead(location="Henderson", bedrooms=2, budget_max=1800), Tier.TIER_1),
        (ExtractedLead(location="Henderson", bedrooms=2, pets=[]), Tier.TIER_1),
        (ExtractedLead(location="Henderson", bedrooms=0), Tier.TIER_2),
        (ExtractedLead(location=None, bedrooms=2, budget_max=1800), Tier.TIER_3),
        (ExtractedLead(location="Henderson", bedrooms=None), Tier.TIER_3),
        (ExtractedLead(), Tier.TIER_3),
    ],
)
def test_classify_tier(lead, expected):
    assert classify_tier(lead) == expected


def test_no_pets_counts_as_bonus_but_none_does_not():
    assert ExtractedLead(location="x", bedrooms=1, pets=[]).bonus_count == 1
    assert ExtractedLead(location="x", bedrooms=1, pets=None).bonus_count == 0


def test_missing_questions_order_gate_first():
    qs = get_missing_field_questions(ExtractedLead())
    assert "area of Las Vegas" in qs[0]
    assert "bedrooms" in qs[1]
    assert len(qs) == 6


def test_tier3_summary_only_asks_gate_questions():
    summary = tier_summary(Tier.TIER_3, ExtractedLead(bedrooms=2))
    assert summary["follow_up_questions"] == [
        "What area of Las Vegas are you looking in? (City, neighborhood, or zip code all work.)"
    ]


def test_tier2_summary_asks_one_soft_question():
    summary = tier_summary(Tier.TIER_2, ExtractedLead(location="x", bedrooms=2))
    assert summary["follow_up_questions"] == ["Do you have a monthly budget range in mind?"]


from models import LeadStatus
from validation import merge_leads, status_for_tier


def test_merge_new_non_null_wins_and_prior_fills_gaps():
    prior = ExtractedLead(location="Henderson", bedrooms=2, budget_max=1800, confidence=0.6, notes="Section 8")
    new = ExtractedLead(bedrooms=3, move_in_date="2026-11-01", confidence=0.4, notes="has a dog")
    merged = merge_leads(prior, new)
    assert merged.location == "Henderson"
    assert merged.bedrooms == 3
    assert merged.budget_max == 1800
    assert merged.move_in_date == "2026-11-01"
    assert merged.confidence == 0.6
    assert merged.notes == "Section 8 | has a dog"


def test_merge_explicit_no_pets_overrides_prior_pets():
    merged = merge_leads(ExtractedLead(pets=["1 dog"]), ExtractedLead(pets=[]))
    assert merged.pets == []


def test_merge_recomputes_missing_fields():
    prior = ExtractedLead(location="Henderson")
    new = ExtractedLead(bedrooms=2, missing_fields=["location", "budget_max"])
    assert merge_leads(prior, new).missing_fields == ["budget_max"]


def test_merge_tier3_then_reply_becomes_tier1():
    prior = ExtractedLead(bedrooms=2)
    reply = ExtractedLead(location="Summerlin", budget_max=2000)
    assert classify_tier(merge_leads(prior, reply)) == Tier.TIER_1


def test_status_for_tier():
    assert status_for_tier(Tier.TIER_1) == LeadStatus.NEW
    assert status_for_tier(Tier.TIER_2) == LeadStatus.NEEDS_REVIEW
    assert status_for_tier(Tier.TIER_3) == LeadStatus.ON_HOLD
