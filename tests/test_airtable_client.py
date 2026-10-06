import json

import pytest
import requests

from airtable_client import (
    AirtableClient,
    LeadRecord,
    lead_from_record,
    lead_to_airtable_fields,
    tier_from_record,
)
from config import PipelineConfig
from models import ExtractedLead, LeadStatus, Tier


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)


@pytest.fixture
def cfg():
    return PipelineConfig(airtable_api_key="pat", airtable_base_id="appX")


def test_find_lead_escapes_quotes_and_lowercases(cfg):
    session = FakeSession([FakeResp(200, {"records": [{"id": "rec1", "fields": {"Email": "o'brien@x.com"}}]})])
    client = AirtableClient(cfg, session=session)
    rec = client.find_lead("O'Brien@x.com")
    assert rec == LeadRecord("rec1", {"Email": "o'brien@x.com"})
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://api.airtable.com/v0/appX/Leads"
    assert kwargs["params"]["filterByFormula"] == "LOWER({Email})='o\\'brien@x.com'"
    assert kwargs["headers"]["Authorization"] == "Bearer pat"
    assert kwargs["timeout"] == 15


def test_find_lead_none_when_empty(cfg):
    client = AirtableClient(cfg, session=FakeSession([FakeResp(200, {"records": []})]))
    assert client.find_lead("nobody@x.com") is None


def test_upsert_creates_then_updates(cfg):
    session = FakeSession([FakeResp(200, {"id": "recNew"}), FakeResp(200, {"id": "recNew"})])
    client = AirtableClient(cfg, session=session)
    assert client.upsert_lead("A@x.com", {"Tier": "Tier 1"}) == "recNew"
    assert client.upsert_lead("A@x.com", {"Tier": "Tier 2"}, record_id="recNew") == "recNew"
    post = session.calls[0]
    assert post[0] == "POST"
    assert post[2]["json"] == {"fields": {"Email": "a@x.com", "Tier": "Tier 1"}, "typecast": True}
    patch = session.calls[1]
    assert patch[0] == "PATCH"
    assert patch[1].endswith("/Leads/recNew")
    assert patch[2]["json"] == {"fields": {"Tier": "Tier 2"}, "typecast": True}


def test_message_exists_and_log(cfg):
    session = FakeSession([FakeResp(200, {"records": [{"id": "m"}]}), FakeResp(200, {"id": "recMsg"})])
    client = AirtableClient(cfg, session=session)
    assert client.message_exists("abc") is True
    assert client.log_message({"Message ID": "abc"}) == "recMsg"
    assert session.calls[0][2]["params"]["filterByFormula"] == "{Message ID}='abc'"
    assert session.calls[1][1].endswith("/Messages")


def test_http_error_raises(cfg):
    client = AirtableClient(cfg, session=FakeSession([FakeResp(500, {})]))
    with pytest.raises(requests.HTTPError):
        client.find_lead("a@x.com")


def test_lead_to_fields_and_back(make_email):
    lead = ExtractedLead(location="Henderson", bedrooms=0, budget_max=1200.0, pets=[], confidence=0.8, notes="Section 8")
    fields = lead_to_airtable_fields(lead, Tier.TIER_1, LeadStatus.NEW, make_email(sender_name="Linda W"))
    assert fields["Email"] == "sarah@example.com"
    assert fields["Name"] == "Linda W"
    assert fields["Bedrooms"] == 0
    assert fields["Pets"] == "None"
    assert fields["Tier"] == "Tier 1"
    assert fields["Status"] == "New"
    assert "Budget Min" not in fields
    assert fields["Last Contact"] == "2026-10-05T12:00:00Z"
    assert json.loads(fields["Extraction JSON"])["budget_max"] == 1200.0

    record = LeadRecord("rec", fields)
    back = lead_from_record(record)
    assert back == lead
    assert tier_from_record(record) == Tier.TIER_1


def test_lead_from_record_handles_missing_or_bad_json():
    assert lead_from_record(LeadRecord("r", {})) is None
    assert lead_from_record(LeadRecord("r", {"Extraction JSON": "{not json"})) is None
    assert tier_from_record(LeadRecord("r", {"Tier": "Tier 9"})) is None
