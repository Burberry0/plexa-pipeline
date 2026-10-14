from models import InboundEmail


def _email(name):
    return InboundEmail(sender_email="x@y.com", sender_name=name, subject="", body_html="", body_plain="")


def test_first_name_variants():
    assert _email("Sarah Johnson").first_name == "Sarah"
    assert _email("Johnson, Sarah").first_name == "Sarah"
    assert _email("").first_name == "there"
    assert _email("   ").first_name == "there"


from models import ExtractedLead, split_name  # noqa: E402


def test_new_extraction_fields_default_none():
    lead = ExtractedLead()
    for f in (
        "zip_code", "phone", "bathrooms", "square_feet", "adults", "children",
        "pet_count", "pet_details", "garage_required", "garage_spaces",
        "amenities", "special_requests", "requester_type", "company_name",
    ):
        assert getattr(lead, f) is None, f


def test_split_name_variants():
    assert split_name("Sarah Johnson") == ("Sarah", "Johnson")
    assert split_name("Johnson, Sarah") == ("Sarah", "Johnson")
    assert split_name("Ana Maria de la Cruz") == ("Ana", "Maria de la Cruz")
    assert split_name("Cher") == ("Cher", "")
    assert split_name("") == ("", "")
    assert split_name("   ") == ("", "")
    assert split_name(None) == ("", "")
