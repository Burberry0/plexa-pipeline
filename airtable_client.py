"""
Plexa Housing — Airtable Client
Thin REST client. Airtable is the only state store for the pipeline.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import quote

import requests

from config import PipelineConfig
from models import ExtractedLead, InboundEmail, LeadStatus, Tier

logger = logging.getLogger("plexa.airtable")

AIRTABLE_API = "https://api.airtable.com/v0"
REQUEST_TIMEOUT = 15
RETRY_STATUSES = (429, 503)
RETRY_DELAY_SECONDS = 1.0


@dataclass
class LeadRecord:
    record_id: str
    fields: dict


def iso_utc(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _escape_formula_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class AirtableClient:
    def __init__(self, config: PipelineConfig, session=None):
        self._session = session or requests.Session()
        self._base = f"{AIRTABLE_API}/{config.airtable_base_id}"
        self._headers = {
            "Authorization": f"Bearer {config.airtable_api_key}",
            "Content-Type": "application/json",
        }
        self._leads = config.airtable_leads_table
        self._messages = config.airtable_messages_table

    def _request(self, method: str, table: str, path: str = "", **kwargs) -> dict:
        url = f"{self._base}/{quote(table)}{path}"
        resp = self._session.request(method, url, headers=self._headers, timeout=REQUEST_TIMEOUT, **kwargs)
        if resp.status_code in RETRY_STATUSES:
            logger.warning(f"Airtable {resp.status_code} on {method} {table}; retrying once")
            time.sleep(RETRY_DELAY_SECONDS)
            resp = self._session.request(method, url, headers=self._headers, timeout=REQUEST_TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # ── Leads ────────────────────────────────────────────────────────────

    def find_lead(self, sender_email: str) -> Optional[LeadRecord]:
        formula = f"LOWER({{Email}})='{_escape_formula_string(sender_email.lower())}'"
        data = self._request("GET", self._leads, params={"filterByFormula": formula, "maxRecords": 1})
        records = data.get("records", [])
        if not records:
            return None
        return LeadRecord(records[0]["id"], records[0].get("fields", {}))

    def upsert_lead(self, sender_email: str, fields: dict, record_id: Optional[str] = None) -> str:
        """Create or update the sender's Leads row in one call.

        Uses Airtable's performUpsert, merging on Email, so two concurrent
        requests for the same sender cannot create two rows. `record_id` is
        ignored (kept so callers don't change); Airtable matches on Email.
        """
        payload = {
            "performUpsert": {"fieldsToMergeOn": ["Email"]},
            "records": [{"fields": {"Email": sender_email.lower(), **fields}}],
            "typecast": True,
        }
        data = self._request("PATCH", self._leads, json=payload)
        return data["records"][0]["id"]

    # ── Messages ─────────────────────────────────────────────────────────

    def message_exists(self, message_id: str) -> bool:
        formula = f"{{Message ID}}='{_escape_formula_string(message_id)}'"
        data = self._request("GET", self._messages, params={"filterByFormula": formula, "maxRecords": 1})
        return bool(data.get("records"))

    def log_message(self, fields: dict) -> str:
        data = self._request("POST", self._messages, json={"fields": fields, "typecast": True})
        return data["id"]


# ── Field mapping ───────────────────────────────────────────────────────────

def lead_to_airtable_fields(lead: ExtractedLead, tier: Tier, status: LeadStatus, email: InboundEmail) -> dict:
    """Map a lead to Airtable column names. None values are omitted so blanks stay blank."""
    if lead.pets is None:
        pets_text = None
    elif lead.pets == []:
        pets_text = "None"
    else:
        pets_text = ", ".join(lead.pets)

    fields = {
        "Email": email.sender_email.lower(),
        "Name": email.sender_name or None,
        "Location": lead.location,
        "Bedrooms": lead.bedrooms,
        "Budget Min": lead.budget_min,
        "Budget Max": lead.budget_max,
        "Move-in Date": lead.move_in_date,
        "Pets": pets_text,
        "Occupants": lead.occupants,
        "Duration Months": lead.duration_months,
        "Pet Friendly Required": lead.pet_friendly_required,
        "Zip Code": lead.zip_code,
        "Phone": lead.phone,
        "Bathrooms": lead.bathrooms,
        "Adults": lead.adults,
        "Children": lead.children,
        "Amenities": ", ".join(lead.amenities) if lead.amenities else None,
        "Special Requests": lead.special_requests,
        "Match Ready": lead.has_gate_fields,  # always written so a lead can flip back to False
        "Confidence": round(lead.confidence, 2),
        "Notes": lead.notes,
        "Tier": tier.value,
        "Status": status.value,
        "Last Subject": email.subject or None,
        "Last Contact": iso_utc(email.received_at),
        "Extraction JSON": json.dumps(asdict(lead)),
    }
    return {k: v for k, v in fields.items() if v is not None}


def lead_from_record(record: LeadRecord) -> Optional[ExtractedLead]:
    raw = record.fields.get("Extraction JSON")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return ExtractedLead(**{k: data.get(k) for k in ExtractedLead.__dataclass_fields__ if k in data})
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse Extraction JSON on {record.record_id}: {e}")
        return None


def tier_from_record(record: LeadRecord) -> Optional[Tier]:
    try:
        return Tier(record.fields.get("Tier"))
    except ValueError:
        return None
