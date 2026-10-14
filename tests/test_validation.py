import pytest

from models import ExtractedLead, Tier
from validation import (
    GATE_QUESTIONS,
    bonus_questions,
    classify_tier,
    gate_questions,
    get_missing_field_questions,
    tier_summary,
)

GATES = dict(zip_code="89052", bedrooms=2, move_in_date="2026-11-01")


@pytest.mark.parametrize(
    "lead,expected",
    [
        (ExtractedLead(**GATES, budget_max=1800), Tier.TIER_1),
        (ExtractedLead(**GATES, pets=[]), Tier.TIER_1),
        (ExtractedLead(**GATES, bathrooms=2), Tier.TIER_1),
        (ExtractedLead(zip_code="89052", bedrooms=0, move_in_date="ASAP"), Tier.TIER_2),
        (ExtractedLead(**GATES, location="Henderson", amenities=["Pool"], adults=2), Tier.TIER_2),
        (ExtractedLead(location="Henderson", bedrooms=2, move_in_date="2026-11-01", budget_max=1800), Tier.TIER_3),
        (ExtractedLead(zip_code="89052", bedrooms=2, budget_max=1800), Tier.TIER_3),
        (ExtractedLead(zip_code="89052", move_in_date="ASAP", budget_max=1800), Tier.TIER_3),
        (ExtractedLead(), Tier.TIER_3),
    ],
)
def test_classify_tier(lead, expected):
    assert classify_tier(lead) == expected


def test_gate_fields_are_zip_bedrooms_move_in():
    assert ExtractedLead.GATE_FIELDS == ("zip_code", "bedrooms", "move_in_date")
    assert ExtractedLead(zip_code="89052", bedrooms=2).missing_gate_fields == ["move_in_date"]
    assert ExtractedLead().missing_gate_fields == ["zip_code", "bedrooms", "move_in_date"]
    assert ExtractedLead(**GATES).has_gate_fields is True


def test_bonus_fields_exclude_move_in_and_include_bathrooms():
    assert "move_in_date" not in ExtractedLead.BONUS_FIELDS
    assert "location" not in ExtractedLead.BONUS_FIELDS
    assert "bathrooms" in ExtractedLead.BONUS_FIELDS


def test_no_pets_counts_as_bonus_but_none_does_not():
    assert ExtractedLead(**GATES, pets=[]).bonus_count == 1
    assert ExtractedLead(**GATES, pets=None).bonus_count == 0


def test_gate_questions_structured_and_ordered():
    assert gate_questions(ExtractedLead(bedrooms=2)) == [GATE_QUESTIONS["zip_code"], GATE_QUESTIONS["move_in_date"]]
    assert gate_questions(ExtractedLead(**GATES)) == []
    assert "ZIP" in GATE_QUESTIONS["zip_code"]
    assert "bedrooms" in GATE_QUESTIONS["bedrooms"]
    assert "move in" in GATE_QUESTIONS["move_in_date"]


def test_zip_question_mentions_known_location_clipped():
    qs = gate_questions(ExtractedLead(location="Henderson", bedrooms=2, move_in_date="ASAP"))
    assert len(qs) == 1
    assert "Henderson" in qs[0] and "ZIP" in qs[0]
    long = gate_questions(ExtractedLead(location="x" * 200, bedrooms=2, move_in_date="ASAP"))[0]
    assert "x" * 80 + "\u2026" in long and "x" * 81 not in long


def test_missing_questions_order_gate_first():
    qs = get_missing_field_questions(ExtractedLead())
    assert qs[:3] == gate_questions(ExtractedLead())
    assert qs[3:] == bonus_questions(ExtractedLead())
    assert len(qs) == 6


def test_tier3_summary_only_asks_gate_questions():
    summary = tier_summary(Tier.TIER_3, ExtractedLead(bedrooms=2))
    assert summary["follow_up_questions"] == [GATE_QUESTIONS["zip_code"], GATE_QUESTIONS["move_in_date"]]


def test_tier2_summary_asks_one_soft_question():
    summary = tier_summary(Tier.TIER_2, ExtractedLead(**GATES))
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
    reply = ExtractedLead(zip_code="89135", move_in_date="2026-12-01", budget_max=2000)
    assert classify_tier(merge_leads(prior, reply)) == Tier.TIER_1


def test_status_for_tier():
    assert status_for_tier(Tier.TIER_1) == LeadStatus.NEW
    assert status_for_tier(Tier.TIER_2) == LeadStatus.NEEDS_REVIEW
    assert status_for_tier(Tier.TIER_3) == LeadStatus.ON_HOLD


from validation import MERGEABLE_FIELDS  # noqa: E402


def test_mergeable_fields_cover_every_extraction_field():
    expected = set(ExtractedLead.__dataclass_fields__) - {"confidence", "missing_fields", "notes"}
    assert set(MERGEABLE_FIELDS) == expected


def test_merge_list_fields_and_new_scalars():
    prior = ExtractedLead(zip_code="89102", amenities=["Pool"], phone="7025551234")
    new = ExtractedLead(amenities=[], bathrooms=1.5)
    merged = merge_leads(prior, new)
    assert merged.amenities == []
    assert merged.zip_code == "89102"
    assert merged.phone == "7025551234"
    assert merged.bathrooms == 1.5
