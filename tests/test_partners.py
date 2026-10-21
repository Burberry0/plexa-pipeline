"""Partner enrichment: Airtable lookup + Lead field mapping."""

from airtable_client import (
    PartnerMatch,
    email_domain,
    partner_to_lead_fields,
)
from models import Classification
from pipeline import Pipeline
from tests.fakes import FakeAI, FakeAirtable, FakeAlerter


def test_email_domain_extracts_host():
    assert email_domain("Alexandria.Negrete@ALESolutions.com") == "alesolutions.com"
    assert email_domain("no-at-sign") is None
    assert email_domain("") is None


def test_partner_to_lead_fields_known():
    p = PartnerMatch(
        email="alexandria.negrete@alesolutions.com",
        inventory_tier="Full",
        vendor="ALE",
        company_name="ALE Solutions",
        matched_by="email",
        status="Active",
    )
    assert partner_to_lead_fields(p) == {
        "Known Partner": True,
        "Partner Tier": "Full",
        "Vendor": "ALE",
    }


def test_partner_to_lead_fields_unknown():
    assert partner_to_lead_fields(None) == {"Known Partner": False}


def test_find_partner_by_exact_email(base_config):
    at = FakeAirtable()
    at.partners = {
        "alexandria.negrete@alesolutions.com": {
            "Email": "alexandria.negrete@alesolutions.com",
            "Inventory Tier": "Full",
            "Vendor": "ALE",
            "Domain": "alesolutions.com",
            "Status": "Active",
            "Company Name": "ALE Solutions",
        }
    }
    hit = at.find_partner("Alexandria.Negrete@ALESolutions.com")
    assert hit is not None
    assert hit.matched_by == "email"
    assert hit.inventory_tier == "Full"
    assert hit.vendor == "ALE"


def test_find_partner_falls_back_to_domain(base_config):
    at = FakeAirtable()
    at.partners_by_domain = {
        "alesolutions.com": {
            "Email": "rentals@alesolutions.com",
            "Inventory Tier": "Full",
            "Vendor": "ALE",
            "Domain": "alesolutions.com",
            "Status": "Active",
        }
    }
    hit = at.find_partner("new.hire@alesolutions.com")
    assert hit is not None
    assert hit.matched_by == "domain"
    assert hit.vendor == "ALE"


def test_find_partner_skips_inactive(base_config):
    at = FakeAirtable()
    at.partners = {
        "old@alesolutions.com": {
            "Email": "old@alesolutions.com",
            "Inventory Tier": "Full",
            "Vendor": "ALE",
            "Domain": "alesolutions.com",
            "Status": "Inactive",
        }
    }
    assert at.find_partner("old@alesolutions.com") is None


def test_pipeline_stamps_partner_on_lead_and_response(base_config, make_email):
    at = FakeAirtable()
    at.partners = {
        "sarah@alesolutions.com": {
            "Email": "sarah@alesolutions.com",
            "Inventory Tier": "Snap",
            "Vendor": "ALE",
            "Domain": "alesolutions.com",
            "Status": "Active",
        }
    }
    r = Pipeline(base_config, ai=FakeAI(), airtable=at, alerter=FakeAlerter()).process_email(
        make_email(sender_email="sarah@alesolutions.com", message_id="m-partner-1")
    )
    assert r.classification == Classification.LEAD
    fields = at.leads["sarah@alesolutions.com"][1]
    assert fields["Known Partner"] is True
    assert fields["Partner Tier"] == "Snap"
    assert fields["Vendor"] == "ALE"
    partner = r.to_dict()["partner"]
    assert partner == {
        "known": True,
        "inventory_tier": "Snap",
        "vendor": "ALE",
        "matched_by": "email",
    }


def test_pipeline_unknown_sender_sets_known_partner_false(base_config, make_email):
    at = FakeAirtable()
    r = Pipeline(base_config, ai=FakeAI(), airtable=at, alerter=FakeAlerter()).process_email(
        make_email(sender_email="stranger@gmail.com", message_id="m-partner-2")
    )
    assert at.leads["stranger@gmail.com"][1]["Known Partner"] is False
    assert "Partner Tier" not in at.leads["stranger@gmail.com"][1]
    assert r.to_dict()["partner"] == {
        "known": False,
        "inventory_tier": None,
        "vendor": None,
        "matched_by": None,
    }
