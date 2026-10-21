from datetime import date

from match_request import build_match_request, format_phone, lease_bucket
from models import ExtractedLead

TODAY = date(2026, 10, 13)
GATES = dict(zip_code="89147", bedrooms=3, move_in_date="2026-10-20")


def test_full_lead_maps_every_key(make_email):
    lead = ExtractedLead(
        **GATES, location="Spring Valley", phone="702-555-1234", bathrooms=2, square_feet=1500,
        occupants=3, adults=2, children=1, duration_months=12,
        pets=["1 dog"], pet_count=1, pet_details=[{"type": "Dog", "description": "40 lbs Husky"}],
        garage_required=True, garage_spaces=2, amenities=["Pool", "Yard"],
        special_requests="Section 8 voucher", requester_type="Company", company_name="Acme Relocation",
    )
    email = make_email(sender_name="Rebeca Villarroel", sender_email="Rebeca@PlexaHousing.com", message_id="m-1", thread_id="t-1")
    body = build_match_request(lead, email, today=TODAY)
    assert body == {
        "first_name": "Rebeca",
        "last_name": "Villarroel",
        "email": "rebeca@plexahousing.com",
        "phone": "(702) 555-1234",
        "requester_type": "Company",
        "company_holds_lease": "",
        "connecting_client_directly": "",
        "company_name": "Acme Relocation",
        "adults": "2",
        "children": "1",
        "zip_code": "89147",
        "lease_length": "6+ Months",
        "move_in_date": "2026-10-20",
        "bedrooms": "3",
        "bathrooms": "2",
        "square_feet": "1500",
        "garage_required": "Yes",
        "garage_spaces": "2",
        "pets": "Yes",
        "pet_quantity": "1",
        "pet_type": "Dog",
        "pet_description": "40 lbs Husky",
        "special_requests": "Section 8 voucher",
        "amenities": ["Pool", "Yard"],
        "source": "email",
        "message_id": "m-1",
        "thread_id": "t-1",
    }


def test_minimal_match_ready_lead_blanks_everything_else(make_email):
    body = build_match_request(ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="ASAP"), make_email(), today=TODAY)
    assert body["zip_code"] == "89052"
    assert body["bedrooms"] == "2"
    assert body["move_in_date"] == "2026-10-13"
    assert body["first_name"] == "Sarah" and body["last_name"] == "Johnson"
    assert body["email"] == "sarah@example.com"
    assert body["amenities"] == []
    for key in (
        "requester_type", "company_name", "adults", "children", "lease_length",
        "bathrooms", "square_feet", "garage_required", "garage_spaces",
        "pets", "pet_quantity", "pet_type", "pet_description", "special_requests", "phone",
    ):
        assert body[key] == "", key


def test_bad_date_is_blank(make_email):
    body = build_match_request(ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="sometime"), make_email(), today=TODAY)
    assert body["move_in_date"] == ""


def test_zero_padded_date(make_email):
    body = build_match_request(ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="2027-06-05"), make_email(), today=TODAY)
    assert body["move_in_date"] == "2027-06-05"


def test_phone_formats():
    assert format_phone("702-555-1234") == "(702) 555-1234"
    assert format_phone("17025551234") == "(702) 555-1234"
    assert format_phone("+1 (702) 555 1234") == "(702) 555-1234"
    assert format_phone("555-1234") == "555-1234"
    assert format_phone(None) == ""
    assert format_phone("   ") == ""


def test_lease_buckets():
    assert lease_bucket(1) == "1 Month"
    assert lease_bucket(2) == "2 Months"
    assert lease_bucket(5) == "5 Months"
    assert lease_bucket(6) == "6+ Months"
    assert lease_bucket(24) == "6+ Months"
    assert lease_bucket(0) == ""
    assert lease_bucket(None) == ""


def test_garage_spots_capped(make_email):
    def spots(n):
        return build_match_request(
            ExtractedLead(**GATES, garage_required=True, garage_spaces=n), make_email(), today=TODAY
        )["garage_spaces"]
    assert spots(1) == "1" and spots(3) == "3" and spots(4) == "3+" and spots(None) == ""
    no = build_match_request(ExtractedLead(**GATES, garage_required=False), make_email(), today=TODAY)
    assert no["garage_required"] == "No"


def test_pets_fallback_from_legacy_strings(make_email):
    body = build_match_request(ExtractedLead(**GATES, pets=["2 cats"]), make_email(), today=TODAY)
    assert body["pets"] == "Yes"
    assert body["pet_quantity"] == "2"
    assert body["pet_type"] == "Cat"
    assert body["pet_description"] == "2 cats"


def test_no_pets_and_unknown_pets(make_email):
    no = build_match_request(ExtractedLead(**GATES, pets=[]), make_email(), today=TODAY)
    assert no["pets"] == "No" and no["pet_quantity"] == "" and no["pet_type"] == ""
    unknown = build_match_request(ExtractedLead(**GATES), make_email(), today=TODAY)
    assert unknown["pets"] == ""


def test_extra_pets_go_to_special_requests(make_email):
    lead = ExtractedLead(
        **GATES, pet_count=2, pets=["1 dog", "1 cat"],
        pet_details=[{"type": "Dog", "description": "40 lbs Husky"}, {"type": "Cat", "description": None}],
        special_requests="Ground floor please",
    )
    body = build_match_request(lead, make_email(), today=TODAY)
    assert body["pet_quantity"] == "2"
    assert body["pet_type"] == "Dog"
    assert body["special_requests"] == "Ground floor please\nAdditional pets: Cat"


def test_pet_quantity_capped_at_ten(make_email):
    body = build_match_request(ExtractedLead(**GATES, pet_count=12, pets=["12 cats"]), make_email(), today=TODAY)
    assert body["pet_quantity"] == "10"


def test_occupants_fallback_to_adults_field(make_email):
    body = build_match_request(ExtractedLead(**GATES, occupants=4), make_email(), today=TODAY)
    assert body["adults"] == "4" and body["children"] == ""
    body = build_match_request(ExtractedLead(**GATES, occupants=4, adults=2, children=2), make_email(), today=TODAY)
    assert body["adults"] == "2" and body["children"] == "2"


def test_requester_type_defaults(make_email):
    assert build_match_request(ExtractedLead(**GATES, company_name="Acme"), make_email(), today=TODAY)["requester_type"] == "Company"
    assert build_match_request(ExtractedLead(**GATES, requester_type="Individual"), make_email(), today=TODAY)["requester_type"] == "Individual"
    assert build_match_request(ExtractedLead(**GATES), make_email(), today=TODAY)["requester_type"] == ""


def test_name_from_last_first_and_empty_sender(make_email):
    body = build_match_request(ExtractedLead(**GATES), make_email(sender_name="Johnson, Sarah"), today=TODAY)
    assert body["first_name"] == "Sarah" and body["last_name"] == "Johnson"
    body = build_match_request(ExtractedLead(**GATES), make_email(sender_name=""), today=TODAY)
    assert body["first_name"] == "" and body["last_name"] == ""


def test_pet_weight_is_not_read_as_a_count(make_email):
    body = build_match_request(ExtractedLead(**GATES, pets=["40 lb lab"]), make_email(), today=TODAY)
    assert body["pets"] == "Yes"
    assert body["pet_quantity"] == "1"
    assert body["pet_type"] == "Other"
    assert body["pet_description"] == "40 lb lab"
