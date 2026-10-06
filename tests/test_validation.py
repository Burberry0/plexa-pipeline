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
