import json

from evals.run_eval import load_cases, score_case, summarize
from models import Classification, ExtractedLead, InboundEmail, PipelineResult, Tier


def _result(classification, tier=None, location=None, bedrooms=None):
    email = InboundEmail(sender_email="a@b.com", sender_name="A", subject="", body_html="", body_plain="")
    extracted = ExtractedLead(location=location, bedrooms=bedrooms) if classification == Classification.LEAD else None
    return PipelineResult(email=email, classification=classification, extracted=extracted, tier=tier)


def test_load_cases(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text('{"id": "a", "body": "x"}\n\n{"id": "b", "body": "y"}\n')
    assert [c["id"] for c in load_cases(str(p))] == ["a", "b"]


def test_score_case_all_match():
    case = {"id": "x", "expected_classification": "LEAD", "expected_tier": "Tier 1", "expected_location": "Henderson", "expected_bedrooms": 2}
    s = score_case(case, _result(Classification.LEAD, Tier.TIER_1, "Henderson area", 2))
    assert s == {"id": "x", "classification_ok": True, "tier_ok": True, "location_ok": True, "bedrooms_ok": True}


def test_score_case_mismatch_and_junk():
    case = {"id": "y", "expected_classification": "JUNK", "expected_tier": None, "expected_location": None, "expected_bedrooms": None}
    s = score_case(case, _result(Classification.LEAD, Tier.TIER_3))
    assert s["classification_ok"] is False
    assert s["tier_ok"] is False
    assert s["location_ok"] is True


def test_summarize():
    scores = [
        {"id": "a", "classification_ok": True, "tier_ok": True, "location_ok": True, "bedrooms_ok": True},
        {"id": "b", "classification_ok": True, "tier_ok": False, "location_ok": False, "bedrooms_ok": True},
    ]
    s = summarize(scores)
    assert s["total"] == 2
    assert s["classification_accuracy"] == 1.0
    assert s["tier_accuracy"] == 0.5
    assert s["failures"] == ["b"]
