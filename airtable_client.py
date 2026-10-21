"""
Plexa Housing — Airtable Client
Thin REST client. Airtable is the only state store for the pipeline.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Literal, Optional
from urllib.parse import quote

import requests

from config import PipelineConfig
from models import ExtractedLead, InboundEmail, LeadStatus, Tier

logger = logging.getLogger("plexa.airtable")

AIRTABLE_API = "https://api.airtable.com/v0"
REQUEST_TIMEOUT = 15
RETRY_STATUSES = (429, 503)
RETRY_DELAY_SECONDS = 1.0

# Partners.Status values that still count as a known partner for enrichment.
_ACTIVE_PARTNER_STATUSES = frozenset({"Active", ""})


@dataclass
class LeadRecord:
    record_id: str
    fields: dict


@dataclass(frozen=True)
class PartnerMatch:
    """A row from Partners used to tag a Lead on ingest."""
    email: str
    inventory_tier: Optional[str] = None  # Full | Snap
    vendor: Optional[str] = None
    company_name: Optional[str] = None
    status: Optional[str] = None
    matched_by: Literal["email", "domain"] = "email"


def iso_utc(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _escape_formula_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def email_domain(sender_email: str) -> Optional[str]:
    text = (sender_email or "").strip().lower()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[-1].strip()
    return domain or None


def partner_from_fields(fields: dict, matched_by: Literal["email", "domain"]) -> Optional[PartnerMatch]:
    """Build a PartnerMatch from an Airtable Partners row; skip inactive / DNC."""
    status = (fields.get("Status") or "").strip()
    if status and status not in _ACTIVE_PARTNER_STATUSES:
        return None
    email = (fields.get("Email") or "").strip().lower()

    def _opt(key: str) -> Optional[str]:
        val = fields.get(key)
        if val is None:
            return None
        text = str(val).strip()
        return text or None

    return PartnerMatch(
        email=email,
        inventory_tier=_opt("Inventory Tier"),
        vendor=_opt("Vendor"),
        company_name=_opt("Company Name"),
        status=status or "Active",
        matched_by=matched_by,
    )


def partner_to_lead_fields(partner: Optional[PartnerMatch]) -> dict:
    """Denormalized Partner columns written onto the Leads upsert."""
    if partner is None:
        return {"Known Partner": False}
    fields = {"Known Partner": True}
    if partner.inventory_tier:
        fields["Partner Tier"] = partner.inventory_tier
    if partner.vendor:
        fields["Vendor"] = partner.vendor
    return fields


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
        self._partners = config.airtable_partners_table

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

    # ── Partners ─────────────────────────────────────────────────────────

    def find_partner(self, sender_email: str) -> Optional[PartnerMatch]:
        """Look up Partners by exact Email, then by Domain. Active rows only.

        Failures are logged and return None so a missing Partners table never
        takes down ingest — Leads simply get Known Partner = false.
        """
        email = (sender_email or "").strip().lower()
        if not email:
            return None
        try:
            by_email = self._find_partner_records(
                f"LOWER({{Email}})='{_escape_formula_string(email)}'"
            )
            for fields in by_email:
                hit = partner_from_fields(fields, "email")
                if hit is not None:
                    return hit

            domain = email_domain(email)
            if not domain:
                return None
            by_domain = self._find_partner_records(
                f"LOWER({{Domain}})='{_escape_formula_string(domain)}'"
            )
            for fields in by_domain:
                hit = partner_from_fields(fields, "domain")
                if hit is not None:
                    return hit
        except Exception as e:  # noqa: BLE001 — enrichment must not fail ingest
            logger.warning(f"Partners lookup failed for {email}: {e}")
        return None

    def _find_partner_records(self, formula: str) -> list:
        data = self._request(
            "GET",
            self._partners,
            params={"filterByFormula": formula, "maxRecords": 5},
        )
        return [r.get("fields", {}) for r in data.get("records", [])]


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
