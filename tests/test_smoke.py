from models import ExtractedLead, Tier
from validation import classify_tier


def test_harness_imports_project_and_tier_logic_runs():
    lead = ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="2026-11-01", budget_max=1800)
    assert classify_tier(lead) == Tier.TIER_1
