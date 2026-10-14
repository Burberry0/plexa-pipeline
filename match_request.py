"""
Plexa Housing — Property-matching request builder

Turns a match-ready ExtractedLead into the body the Property Matching n8n
workflow already accepts: a JotForm submission. The matching workflow owns
formatting, zip → lat/long geocoding, Request_ID and Priority, so this module
only fills the form fields. Pure functions, no I/O, no config.

JotForm keys (form 260054674457057), values are strings and blanks are "":
  q2_q2_fullname0   {first, last}            q67_areYou        Individual | Company
  q68_typeA68       company holds lease?     q69_areYou69      connecting client directly?
  q71_company       company name             q18_whatEmail     email
  q4_q4_phone2      {full}                   q29_occupants     adults
  q33_number        children                 q72_desiredZip    5-digit zip
  q14_q14_dropdown12  "1 Month".."5 Months" | "6+ Months"
  q13_q13_datetime11  {month, day, year}     q6_q6_number4     min bedrooms
  q7_q7_number5     min bathrooms            q8_q8_number6     min sq ft
  q20_garageRequired  Yes | No               q21_garageSpots   1 | 2 | 3 | 3+
  q22_pets          Yes | No                 q35_petQuantity   "1".."10"
  q23_petType       Dog | Cat | Other        q28_dogWeight28   pet 1 weight/breed text
  q11_q11_checkbox9 amenity labels (list)    q12_q12_textarea10  special requests

TODO(jotform): pets 2-10 have their own repeating keys (q25_typeA, q63_petType63 /
q64_dogWeight / q65_petWeight, ...). Until they are confirmed from a real submission,
additional pets are appended to q12 so nothing is lost. q68/q69 are left blank.
"""

import re
from datetime import date
from typing import Optional

from models import ExtractedLead, InboundEmail, split_name

PET_TYPES = ("Dog", "Cat", "Other")
MAX_PETS = 10
MAX_GARAGE_SPOTS = 3


def _s(value) -> str:
    """JotForm sends every scalar as a string; None becomes ''."""
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


def _move_in(value: Optional[str], today: date) -> dict:
    if value == "ASAP":
        d = today
    else:
        try:
            d = date.fromisoformat((value or "").strip())
        except ValueError:
            return {"month": "", "day": "", "year": ""}
    return {"month": f"{d.month:02d}", "day": f"{d.day:02d}", "year": f"{d.year:04d}"}


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
        m = re.match(r"\s*(\d+)", p)
        total += int(m.group(1)) if m else 1
    return total


def _pets(lead: ExtractedLead) -> dict:
    count = _pet_count(lead)
    has_pets = (count or 0) > 0 or bool(lead.pets)
    if not has_pets:
        status = "No" if (lead.pets == [] or count == 0) else ""
        return {"q22_pets": status, "q35_petQuantity": "", "q23_petType": "", "q28_dogWeight28": "", "extra": []}

    details = lead.pet_details or []
    if details:
        first = details[0]
        pet_type = first.get("type") if first.get("type") in PET_TYPES else "Other"
        description = first.get("description") or ""
        extra = [f"{d.get('type') or 'Other'}{': ' + d['description'] if d.get('description') else ''}" for d in details[1:]]
    else:
        pet_type = _pet_type_from_text(lead.pets[0]) if lead.pets else "Other"
        description = ", ".join(lead.pets or [])
        extra = []
    return {
        "q22_pets": "Yes",
        "q35_petQuantity": _s(min(count or len(lead.pets or []) or 1, MAX_PETS)),
        "q23_petType": pet_type,
        "q28_dogWeight28": description,
        "extra": extra,
    }


def build_match_request(lead: ExtractedLead, email: InboundEmail, today: date) -> dict:
    """JotForm-shaped body for the Property Matching webhook. Call only when lead.has_gate_fields."""
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
        "q2_q2_fullname0": {"first": first, "last": last},
        "q67_areYou": requester,
        "q68_typeA68": "",
        "q69_areYou69": "",
        "q71_company": _s(lead.company_name),
        "q18_whatEmail": email.sender_email.lower(),
        "q4_q4_phone2": {"full": format_phone(lead.phone)},
        "q29_occupants": _s(adults),
        "q33_number": _s(lead.children),
        "q72_desiredZip": _s(lead.zip_code),
        "q14_q14_dropdown12": lease_bucket(lead.duration_months),
        "q13_q13_datetime11": _move_in(lead.move_in_date, today),
        "q6_q6_number4": _s(lead.bedrooms),
        "q7_q7_number5": _s(lead.bathrooms),
        "q8_q8_number6": _s(lead.square_feet),
        "q20_garageRequired": garage,
        "q21_garageSpots": spots,
        "q22_pets": pets["q22_pets"],
        "q35_petQuantity": pets["q35_petQuantity"],
        "q23_petType": pets["q23_petType"],
        "q28_dogWeight28": pets["q28_dogWeight28"],
        "q12_q12_textarea10": "\n".join(special),
        "q11_q11_checkbox9": list(lead.amenities or []),
        # Traceability for the matching workflow's logs; unknown keys are ignored by the form mapping.
        "source": "email",
        "message_id": email.message_id or "",
        "thread_id": email.thread_id or "",
    }
