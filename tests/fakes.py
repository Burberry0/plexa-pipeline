from typing import Optional

import requests

from airtable_client import LeadRecord
from models import Classification, ExtractedLead


class FakeAI:
    def __init__(self, classification=Classification.LEAD, lead: Optional[ExtractedLead] = None, extract_error: Optional[Exception] = None):
        self.classification = classification
        self.lead = lead or ExtractedLead(location="Henderson", zip_code="89052", bedrooms=2, move_in_date="ASAP", budget_max=1800.0, confidence=0.9)
        self.extract_error = extract_error
        self.extract_calls = 0

    def classify_email(self, email):
        return self.classification, 10

    def extract_lead(self, email, today=None):
        self.extract_calls += 1
        if self.extract_error:
            raise self.extract_error
        return self.lead, 100


class FakeAirtable:
    def __init__(self):
        self.leads = {}       # email -> (record_id, fields)
        self.messages = {}    # message_id -> fields
        self.fail_on = None   # method name to raise HTTPError from
        self._n = 0

    def _maybe_fail(self, name):
        if self.fail_on == name:
            raise requests.HTTPError("500 Server Error")

    def find_lead(self, sender_email):
        self._maybe_fail("find_lead")
        hit = self.leads.get(sender_email.lower())
        return LeadRecord(hit[0], dict(hit[1])) if hit else None

    def upsert_lead(self, sender_email, fields, record_id=None):
        self._maybe_fail("upsert_lead")
        key = sender_email.lower()
        if record_id:
            rid, existing = self.leads[key]
            existing.update(fields)
            return rid
        self._n += 1
        rid = f"rec{self._n}"
        self.leads[key] = (rid, {"Email": key, **fields})
        return rid

    def message_exists(self, message_id):
        self._maybe_fail("message_exists")
        return message_id in self.messages

    def log_message(self, fields):
        self._maybe_fail("log_message")
        self.messages[fields.get("Message ID") or f"anon-{len(self.messages)}"] = fields
        return "recMsg"


class FakeAlerter:
    def __init__(self):
        self.sent = []

    def __call__(self, text):
        self.sent.append(text)
        return True
