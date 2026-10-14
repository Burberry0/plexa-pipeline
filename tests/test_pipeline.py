from dataclasses import replace
from datetime import datetime, timezone

import pytest

from ai_client import ExtractionRefused
from airtable_client import lead_to_airtable_fields
from models import Classification, ExtractedLead, LeadStatus, Tier
from pipeline import Pipeline
from tests.fakes import FakeAI, FakeAirtable, FakeAlerter

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _pipeline(base_config, ai=None, airtable=None, alerter=None):
    return Pipeline(base_config, ai=ai or FakeAI(), airtable=airtable, alerter=alerter or FakeAlerter(), now=lambda: NOW)


def test_junk_stops_early_and_logs(base_config, make_email):
    at = FakeAirtable()
    p = _pipeline(base_config, ai=FakeAI(classification=Classification.JUNK), airtable=at)
    r = p.process_email(make_email(message_id="m1"))
    assert r.classification == Classification.JUNK
    assert r.extracted is None
    assert r.should_reply is False
    assert r.reply_skip_reason == "junk"
    assert at.messages["m1"]["Classification"] == "JUNK"
    assert at.leads == {}


def test_tier1_lead_upserts_and_decides_reply(base_config, make_email):
    at = FakeAirtable()
    r = _pipeline(base_config, airtable=at).process_email(make_email(message_id="m1"))
    assert r.tier == Tier.TIER_1
    assert r.status == LeadStatus.NEW
    assert r.should_reply is True
    assert r.reply_skip_reason == "ok"
    assert r.reply_subject == "Re: 2BR please"
    assert "Henderson" in r.reply_html
    assert r.airtable_record_id == "rec1"
    fields = at.leads["sarah@example.com"][1]
    assert fields["Tier"] == "Tier 1"
    assert fields["Reply Count"] == 1
    assert fields["Last Reply At"] == "2026-10-05T12:00:00Z"
    assert at.messages["m1"]["Should Reply"] is True
    assert at.messages["m1"]["Tier"] == "Tier 1"


def test_duplicate_message_is_skipped(base_config, make_email):
    at = FakeAirtable()
    ai = FakeAI()
    p = _pipeline(base_config, ai=ai, airtable=at)
    p.process_email(make_email(message_id="m1"))
    r2 = p.process_email(make_email(message_id="m1"))
    assert r2.is_duplicate is True
    assert r2.should_reply is False
    assert r2.reply_skip_reason == "duplicate"
    assert ai.extract_calls == 1
    assert at.leads["sarah@example.com"][1]["Reply Count"] == 1
    assert len(at.messages) == 1


def test_tier3_then_reply_upgrades_and_merges(base_config, make_email):
    at = FakeAirtable()
    first = FakeAI(lead=ExtractedLead(bedrooms=2, confidence=0.3))
    r1 = _pipeline(base_config, ai=first, airtable=at).process_email(make_email(message_id="m1"))
    assert r1.tier == Tier.TIER_3
    assert r1.is_upgrade is False

    # Move the first reply out of the cooldown window so the guardrail does not block the upgrade reply
    at.leads["sarah@example.com"][1]["Last Reply At"] = "2026-10-05T11:00:00Z"
    second = FakeAI(lead=ExtractedLead(zip_code="89135", bedrooms=3, move_in_date="2026-12-01", confidence=0.5))
    r2 = _pipeline(base_config, ai=second, airtable=at).process_email(make_email(message_id="m2", subject="Re: 2BR please"))
    assert r2.is_upgrade is True
    assert r2.tier == Tier.TIER_2
    assert r2.extracted.zip_code == "89135"
    assert r2.extracted.location is None
    assert r2.extracted.bedrooms == 3
    assert "exactly what we needed" in r2.reply_html
    assert r2.airtable_record_id == "rec1"
    assert at.leads["sarah@example.com"][1]["Reply Count"] == 2


def test_tier3_sender_capped_at_two_replies(base_config, make_email):
    at = FakeAirtable()
    p = _pipeline(base_config, ai=FakeAI(lead=ExtractedLead(bedrooms=2)), airtable=at)
    r1 = p.process_email(make_email(message_id="m1"))
    assert r1.tier == Tier.TIER_3
    assert r1.should_reply is True
    at.leads["sarah@example.com"][1]["Last Reply At"] = "2026-10-05T11:00:00Z"
    r2 = p.process_email(make_email(message_id="m2"))
    assert r2.should_reply is True
    at.leads["sarah@example.com"][1]["Last Reply At"] = "2026-10-05T11:00:00Z"
    r3 = p.process_email(make_email(message_id="m3"))
    assert r3.should_reply is False
    assert r3.reply_skip_reason == "max_replies_reached"
    assert r3.reply_html is not None  # rendered for audit, not sent
    assert at.leads["sarah@example.com"][1]["Reply Count"] == 2


def test_cooldown_blocks_immediate_second_reply(base_config, make_email):
    at = FakeAirtable()
    p = _pipeline(base_config, ai=FakeAI(lead=ExtractedLead(bedrooms=2)), airtable=at)
    p.process_email(make_email(message_id="m1"))
    r2 = p.process_email(make_email(message_id="m2"))
    assert r2.reply_skip_reason == "cooldown_active"


def test_tier1_follow_up_gets_no_reply(base_config, make_email):
    at = FakeAirtable()
    p = _pipeline(base_config, airtable=at)
    r1 = p.process_email(make_email(message_id="m1"))
    assert r1.tier == Tier.TIER_1
    assert r1.should_reply is True
    at.leads["sarah@example.com"][1]["Last Reply At"] = "2026-10-05T11:00:00Z"
    r2 = p.process_email(make_email(message_id="m2", subject="Re: 2BR please"))
    assert r2.should_reply is False
    assert r2.reply_skip_reason == "follow_up"
    assert r2.status == LeadStatus.NEEDS_REVIEW
    assert r2.reply_html is not None
    assert at.leads["sarah@example.com"][1]["Reply Count"] == 1


def test_manual_status_survives_follow_up(base_config, make_email):
    at = FakeAirtable()
    seeded = lead_to_airtable_fields(
        ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="ASAP", budget_max=1800.0, confidence=0.9),
        Tier.TIER_1,
        LeadStatus.NEW,
        make_email(message_id="m0"),
    )
    seeded["Status"] = "Matched"
    at.leads["sarah@example.com"] = ("rec1", seeded)
    r = _pipeline(base_config, airtable=at).process_email(make_email(message_id="m2"))
    assert r.error is None
    assert at.leads["sarah@example.com"][1]["Status"] == "Matched"


def test_kill_switch(base_config, make_email):
    cfg = replace(base_config, auto_reply_enabled=False)
    r = _pipeline(cfg, airtable=FakeAirtable()).process_email(make_email())
    assert r.should_reply is False
    assert r.reply_skip_reason == "auto_reply_disabled"
    assert r.reply_html is not None


def test_no_airtable_demo_mode_still_renders(base_config, make_email):
    r = _pipeline(base_config, airtable=None).process_email(make_email(), persist=False)
    assert r.tier == Tier.TIER_1
    assert r.reply_html is not None
    assert r.should_reply is True
    assert r.airtable_record_id is None


def test_persist_false_skips_airtable_even_when_configured(base_config, make_email):
    at = FakeAirtable()
    _pipeline(base_config, airtable=at).process_email(make_email(), persist=False)
    assert at.leads == {} and at.messages == {}


def test_airtable_failure_goes_to_manual_review_and_alerts(base_config, make_email):
    at = FakeAirtable()
    at.fail_on = "upsert_lead"
    alerter = FakeAlerter()
    r = _pipeline(base_config, airtable=at, alerter=alerter).process_email(make_email(message_id="m1"))
    assert r.status == LeadStatus.MANUAL_REVIEW
    assert r.should_reply is False
    assert r.reply_skip_reason == "pipeline_error"
    assert "500" in r.error
    assert r.tier == Tier.TIER_1  # classification survived
    assert len(alerter.sent) == 1
    assert "sarah@example.com" in alerter.sent[0]


def test_extraction_refusal_goes_to_manual_review(base_config, make_email):
    at = FakeAirtable()
    alerter = FakeAlerter()
    ai = FakeAI(extract_error=ExtractionRefused("nope"))
    r = _pipeline(base_config, ai=ai, airtable=at, alerter=alerter).process_email(make_email(message_id="m1"))
    assert r.classification == Classification.LEAD
    assert r.status == LeadStatus.MANUAL_REVIEW
    assert r.extracted is None
    assert at.messages["m1"]["Status"] == "Manual Review"
    assert "nope" in at.messages["m1"]["Error"]
    assert len(alerter.sent) == 1


def test_log_failure_does_not_mask_result(base_config, make_email):
    at = FakeAirtable()
    at.fail_on = "log_message"
    r = _pipeline(base_config, airtable=at).process_email(make_email(message_id="m1"))
    assert r.tier == Tier.TIER_1
    assert r.error is None


def test_to_dict_shape(base_config, make_email):
    d = _pipeline(base_config).process_email(make_email(), persist=False).to_dict()
    assert d["reply"]["should_send"] is True
    assert d["email"]["message_id"] == "msg-1"
    assert d["tokens"]["total"] == 110
    assert "zip_code" in d["extraction"]
    assert "amenities" in d["extraction"]
