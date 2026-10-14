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
        "q2_q2_fullname0": {"first": "Rebeca", "last": "Villarroel"},
        "q67_areYou": "Company",
        "q68_typeA68": "",
        "q69_areYou69": "",
        "q71_company": "Acme Relocation",
        "q18_whatEmail": "rebeca@plexahousing.com",
        "q4_q4_phone2": {"full": "(702) 555-1234"},
        "q29_occupants": "2",
        "q33_number": "1",
        "q72_desiredZip": "89147",
        "q14_q14_dropdown12": "6+ Months",
        "q13_q13_datetime11": {"month": "10", "day": "20", "year": "2026"},
        "q6_q6_number4": "3",
        "q7_q7_number5": "2",
        "q8_q8_number6": "1500",
        "q20_garageRequired": "Yes",
        "q21_garageSpots": "2",
        "q22_pets": "Yes",
        "q35_petQuantity": "1",
        "q23_petType": "Dog",
        "q28_dogWeight28": "40 lbs Husky",
        "q12_q12_textarea10": "Section 8 voucher",
        "q11_q11_checkbox9": ["Pool", "Yard"],
        "source": "email",
        "message_id": "m-1",
        "thread_id": "t-1",
    }


def test_minimal_match_ready_lead_blanks_everything_else(make_email):
    body = build_match_request(ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="ASAP"), make_email(), today=TODAY)
    assert body["q72_desiredZip"] == "89052"
    assert body["q6_q6_number4"] == "2"
    assert body["q13_q13_datetime11"] == {"month": "10", "day": "13", "year": "2026"}
    assert body["q2_q2_fullname0"] == {"first": "Sarah", "last": "Johnson"}
    assert body["q18_whatEmail"] == "sarah@example.com"
    assert body["q11_q11_checkbox9"] == []
    for key in ("q67_areYou", "q71_company", "q29_occupants", "q33_number", "q14_q14_dropdown12",
                "q7_q7_number5", "q8_q8_number6", "q20_garageRequired", "q21_garageSpots",
                "q22_pets", "q35_petQuantity", "q23_petType", "q28_dogWeight28", "q12_q12_textarea10"):
        assert body[key] == "", key
    assert body["q4_q4_phone2"] == {"full": ""}


def test_bad_date_is_blank(make_email):
    body = build_match_request(ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="sometime"), make_email(), today=TODAY)
    assert body["q13_q13_datetime11"] == {"month": "", "day": "", "year": ""}


def test_zero_padded_date(make_email):
    body = build_match_request(ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="2027-06-05"), make_email(), today=TODAY)
    assert body["q13_q13_datetime11"] == {"month": "06", "day": "05", "year": "2027"}


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
        return build_match_request(ExtractedLead(**GATES, garage_required=True, garage_spaces=n), make_email(), today=TODAY)["q21_garageSpots"]
    assert spots(1) == "1" and spots(3) == "3" and spots(4) == "3+" and spots(None) == ""
    no = build_match_request(ExtractedLead(**GATES, garage_required=False), make_email(), today=TODAY)
    assert no["q20_garageRequired"] == "No"


def test_pets_fallback_from_legacy_strings(make_email):
    body = build_match_request(ExtractedLead(**GATES, pets=["2 cats"]), make_email(), today=TODAY)
    assert body["q22_pets"] == "Yes"
    assert body["q35_petQuantity"] == "2"
    assert body["q23_petType"] == "Cat"
    assert body["q28_dogWeight28"] == "2 cats"


def test_no_pets_and_unknown_pets(make_email):
    no = build_match_request(ExtractedLead(**GATES, pets=[]), make_email(), today=TODAY)
    assert no["q22_pets"] == "No" and no["q35_petQuantity"] == "" and no["q23_petType"] == ""
    unknown = build_match_request(ExtractedLead(**GATES), make_email(), today=TODAY)
    assert unknown["q22_pets"] == ""


def test_extra_pets_go_to_special_requests(make_email):
    lead = ExtractedLead(
        **GATES, pet_count=2, pets=["1 dog", "1 cat"],
        pet_details=[{"type": "Dog", "description": "40 lbs Husky"}, {"type": "Cat", "description": None}],
        special_requests="Ground floor please",
    )
    body = build_match_request(lead, make_email(), today=TODAY)
    assert body["q35_petQuantity"] == "2"
    assert body["q23_petType"] == "Dog"
    assert body["q12_q12_textarea10"] == "Ground floor please\nAdditional pets: Cat"


def test_pet_quantity_capped_at_ten(make_email):
    body = build_match_request(ExtractedLead(**GATES, pet_count=12, pets=["12 cats"]), make_email(), today=TODAY)
    assert body["q35_petQuantity"] == "10"


def test_occupants_fallback_to_adults_field(make_email):
    body = build_match_request(ExtractedLead(**GATES, occupants=4), make_email(), today=TODAY)
    assert body["q29_occupants"] == "4" and body["q33_number"] == ""
    body = build_match_request(ExtractedLead(**GATES, occupants=4, adults=2, children=2), make_email(), today=TODAY)
    assert body["q29_occupants"] == "2" and body["q33_number"] == "2"


def test_requester_type_defaults(make_email):
    assert build_match_request(ExtractedLead(**GATES, company_name="Acme"), make_email(), today=TODAY)["q67_areYou"] == "Company"
    assert build_match_request(ExtractedLead(**GATES, requester_type="Individual"), make_email(), today=TODAY)["q67_areYou"] == "Individual"
    assert build_match_request(ExtractedLead(**GATES), make_email(), today=TODAY)["q67_areYou"] == ""


def test_name_from_last_first_and_empty_sender(make_email):
    body = build_match_request(ExtractedLead(**GATES), make_email(sender_name="Johnson, Sarah"), today=TODAY)
    assert body["q2_q2_fullname0"] == {"first": "Sarah", "last": "Johnson"}
    body = build_match_request(ExtractedLead(**GATES), make_email(sender_name=""), today=TODAY)
    assert body["q2_q2_fullname0"] == {"first": "", "last": ""}
