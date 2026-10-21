"""
Plexa Housing — Property-matching request builder

Turns a match-ready ExtractedLead into the body n8n POSTs to the Property
Matching webhook after Slack approval. Field names are plain English (same
concepts as ExtractedLead / Airtable), not JotForm q* keys. The matching
workflow owns geocoding, Request_ID and Priority. Pure functions, no I/O.

Keys (scalars are strings; blanks are ""; amenities is a list):
  first_name, last_name       from sender display name
  email                       sender address (lowercased)
  phone                       formatted US number or as written
  requester_type              Individual | Company | ""
  company_holds_lease         reserved ("" for now)
  connecting_client_directly  reserved ("" for now)
  company_name
  adults, children
  zip_code                    5-digit gate field
  lease_length                "1 Month".."5 Months" | "6+ Months" | ""
  move_in_date                YYYY-MM-DD ("ASAP" resolves to today)
  bedrooms, bathrooms, square_feet
  garage_required             Yes | No | ""
  garage_spaces               1 | 2 | 3 | 3+ | ""
  pets                        Yes | No | ""
  pet_quantity                "1".."10" | ""
  pet_type                    Dog | Cat | Other | ""
  pet_description             weight/breed text for first pet
  special_requests            free text (extra pets appended here)
  amenities                   list of JotForm amenity labels
  source                      "email"
  message_id, thread_id       Gmail traceability
"""

import re
from datetime import date
from typing import Optional

from models import ExtractedLead, InboundEmail, split_name

PET_TYPES = ("Dog", "Cat", "Other")
MAX_PETS = 10
MAX_GARAGE_SPOTS = 3


def _s(value) -> str:
    """Scalar to string; None becomes ''."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def format_phone(raw: Optional[str]) -> str:
    """(702) 555-1234 for a 10-digit US number (leading 1 dropped); otherwise as written."""
    text = (raw or "").strip()
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return text


def lease_bucket(months: Optional[int]) -> str:
    if not months or months < 1:
        return ""
    if months >= 6:
        return "6+ Months"
    return "1 Month" if months == 1 else f"{months} Months"


def _move_in_iso(value: Optional[str], today: date) -> str:
    """YYYY-MM-DD; ASAP → today; unparseable → ''."""
    if value == "ASAP":
        d = today
    else:
        try:
            d = date.fromisoformat((value or "").strip())
        except ValueError:
            return ""
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def _pet_type_from_text(text: str) -> str:
    lowered = text.lower()
    if "dog" in lowered or "pupp" in lowered:
        return "Dog"
    if "cat" in lowered or "kitten" in lowered:
        return "Cat"
    return "Other"


def _pet_count(lead: ExtractedLead) -> Optional[int]:
    if lead.pet_count is not None:
        return lead.pet_count
    if lead.pets is None:
        return None
    total = 0
    for p in lead.pets:
        # Only "2 dogs" / "1 cat" style counts — not "40 lb lab" weight prefixes.
        m = re.match(r"\s*(\d+)\s+(dogs?|cats?|pets?|puppies|kittens)\b", p, re.I)
        total += int(m.group(1)) if m else 1
    return total


def _pets(lead: ExtractedLead) -> dict:
    count = _pet_count(lead)
    has_pets = (count or 0) > 0 or bool(lead.pets)
    if not has_pets:
        status = "No" if (lead.pets == [] or count == 0) else ""
        return {
            "pets": status,
            "pet_quantity": "",
            "pet_type": "",
            "pet_description": "",
            "extra": [],
        }

    details = lead.pet_details or []
    if details:
        first = details[0]
        pet_type = first.get("type") if first.get("type") in PET_TYPES else "Other"
        description = first.get("description") or ""
        extra = [
            f"{d.get('type') or 'Other'}{': ' + d['description'] if d.get('description') else ''}"
            for d in details[1:]
        ]
    else:
        pet_type = _pet_type_from_text(lead.pets[0]) if lead.pets else "Other"
        description = ", ".join(lead.pets or [])
        extra = []
    return {
        "pets": "Yes",
        "pet_quantity": _s(min(count or len(lead.pets or []) or 1, MAX_PETS)),
        "pet_type": pet_type,
        "pet_description": description,
        "extra": extra,
    }


def build_match_request(lead: ExtractedLead, email: InboundEmail, today: date) -> dict:
    """Readable match body for the Property Matching webhook. Call only when lead.has_gate_fields."""
    first, last = split_name(email.sender_name)
    pets = _pets(lead)

    special = [lead.special_requests] if lead.special_requests else []
    if pets["extra"]:
        special.append("Additional pets: " + "; ".join(pets["extra"]))

    adults = lead.adults if lead.adults is not None else (lead.occupants if lead.children is None else None)
    requester = lead.requester_type or ("Company" if lead.company_name else "")

    if lead.garage_required is None:
        garage = ""
    else:
        garage = "Yes" if lead.garage_required else "No"
    if lead.garage_spaces is None:
        spots = ""
    else:
        spots = f"{MAX_GARAGE_SPOTS}+" if lead.garage_spaces > MAX_GARAGE_SPOTS else _s(lead.garage_spaces)

    return {
        "first_name": first,
        "last_name": last,
        "email": email.sender_email.lower(),
        "phone": format_phone(lead.phone),
        "requester_type": requester,
        "company_holds_lease": "",
        "connecting_client_directly": "",
        "company_name": _s(lead.company_name),
        "adults": _s(adults),
        "children": _s(lead.children),
        "zip_code": _s(lead.zip_code),
        "lease_length": lease_bucket(lead.duration_months),
        "move_in_date": _move_in_iso(lead.move_in_date, today),
        "bedrooms": _s(lead.bedrooms),
        "bathrooms": _s(lead.bathrooms),
        "square_feet": _s(lead.square_feet),
        "garage_required": garage,
        "garage_spaces": spots,
        "pets": pets["pets"],
        "pet_quantity": pets["pet_quantity"],
        "pet_type": pets["pet_type"],
        "pet_description": pets["pet_description"],
        "special_requests": "\n".join(special),
        "amenities": list(lead.amenities or []),
        "source": "email",
        "message_id": email.message_id or "",
        "thread_id": email.thread_id or "",
    }
