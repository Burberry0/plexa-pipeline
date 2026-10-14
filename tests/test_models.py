from models import InboundEmail


def _email(name):
    return InboundEmail(sender_email="x@y.com", sender_name=name, subject="", body_html="", body_plain="")


def test_first_name_variants():
    assert _email("Sarah Johnson").first_name == "Sarah"
    assert _email("Johnson, Sarah").first_name == "Sarah"
    assert _email("").first_name == "there"
    assert _email("   ").first_name == "there"
