import json

from evals.run_eval import load_cases, score_case, summarize
from models import Classification, ExtractedLead, InboundEmail, PipelineResult, Tier


def _result(classification, tier=None, location=None, bedrooms=None, zip_code=None, move_in_date=None):
    email = InboundEmail(sender_email="a@b.com", sender_name="A", subject="", body_html="", body_plain="")
    extracted = (
        ExtractedLead(location=location, bedrooms=bedrooms, zip_code=zip_code, move_in_date=move_in_date)
        if classification == Classification.LEAD else None
    )
    return PipelineResult(email=email, classification=classification, extracted=extracted, tier=tier)


ALL_OK = {"classification_ok": True, "tier_ok": True, "location_ok": True, "bedrooms_ok": True, "zip_ok": True, "match_ready_ok": True}


def test_load_cases(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text('{"id": "a", "body": "x"}\n\n{"id": "b", "body": "y"}\n')
    assert [c["id"] for c in load_cases(str(p))] == ["a", "b"]


def test_score_case_all_match():
    case = {"id": "x", "expected_classification": "LEAD", "expected_tier": "Tier 1", "expected_location": "Henderson",
            "expected_bedrooms": 2, "expected_zip_code": "89052", "expected_match_ready": True}
    s = score_case(case, _result(Classification.LEAD, Tier.TIER_1, "Henderson area", 2, zip_code="89052", move_in_date="ASAP"))
    assert s == {"id": "x", **ALL_OK}


def test_score_case_zip_and_match_ready_mismatch():
    case = {"id": "x", "expected_classification": "LEAD", "expected_tier": "Tier 3", "expected_location": "Henderson",
            "expected_bedrooms": 2, "expected_zip_code": None, "expected_match_ready": False}
    s = score_case(case, _result(Classification.LEAD, Tier.TIER_3, "Henderson", 2, zip_code="89052", move_in_date="ASAP"))
    assert s["zip_ok"] is False
    assert s["match_ready_ok"] is False


def test_score_case_mismatch_and_junk():
    case = {"id": "y", "expected_classification": "JUNK", "expected_tier": None, "expected_location": None,
            "expected_bedrooms": None, "expected_zip_code": None, "expected_match_ready": False}
    s = score_case(case, _result(Classification.LEAD, Tier.TIER_3))
    assert s["classification_ok"] is False
    assert s["tier_ok"] is False
    assert s["location_ok"] is True
    assert s["zip_ok"] is True
    assert s["match_ready_ok"] is True


def test_summarize():
    scores = [
        {"id": "a", **ALL_OK},
        {"id": "b", **ALL_OK, "tier_ok": False, "location_ok": False},
        {"id": "c", **ALL_OK, "zip_ok": False},
    ]
    s = summarize(scores)
    assert s["total"] == 3
    assert s["classification_accuracy"] == 1.0
    assert s["tier_accuracy"] == 0.667
    assert s["zip_accuracy"] == 0.667
    assert s["match_ready_accuracy"] == 1.0
    assert s["failures"] == ["b", "c"]


def test_golden_set_has_matching_keys():
    import os
    cases = load_cases(os.path.join(os.path.dirname(__file__), "..", "evals", "golden_emails.jsonl"))
    assert len(cases) >= 10
    for c in cases:
        assert "expected_zip_code" in c and "expected_match_ready" in c, c["id"]
        assert c["expected_tier"] in {"Tier 1", "Tier 2", "Tier 3", None}
        assert c["expected_match_ready"] == (c["expected_tier"] in ("Tier 1", "Tier 2")), c["id"]
        if c["expected_match_ready"]:
            assert c["expected_zip_code"], c["id"]
    ids = {c["id"] for c in cases}
    assert {"tier3_missing_zip", "tier3_missing_movein", "tier1_company_with_pets_amenities"} <= ids


def test_model_overrides_replace_only_given_models():
    from config import PipelineConfig
    from evals.run_eval import apply_model_overrides

    base = PipelineConfig(openai_api_key="k", junk_filter_model="a", extraction_model="b")
    cfg = apply_model_overrides(base, junk_model=None, extraction_model="deepseek-v4-pro")
    assert cfg.junk_filter_model == "a"
    assert cfg.extraction_model == "deepseek-v4-pro"
    assert apply_model_overrides(base, "glm-5.3-flash", None).junk_filter_model == "glm-5.3-flash"


def test_format_line_shows_pipeline_error():
    from evals.run_eval import format_line

    ok = _result(Classification.LEAD, Tier.TIER_1, "Henderson", 2, zip_code="89052", move_in_date="ASAP")
    line = format_line({"id": "x", **ALL_OK}, ok)
    assert line.startswith("OK ") and "err=" not in line
    assert "zip=89052" in line and "mr=True" in line
    ok.processing_time_ms = 1234.5
    assert "ms=1234" in format_line({"id": "x", **ALL_OK}, ok)

    bad = _result(Classification.LEAD)
    bad.error = "Model returned empty extraction"
    line = format_line({"id": "y", **ALL_OK, "tier_ok": False, "location_ok": False, "bedrooms_ok": False}, bad)
    assert line.startswith("BAD") and "err=Model returned empty extraction" in line
