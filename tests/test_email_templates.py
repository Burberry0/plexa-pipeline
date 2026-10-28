from email_templates import _format_budget, render_email_for_tier, render_reply
from models import ExtractedLead, Tier


def test_brand_header_omits_property_management_tagline(make_email):
    _, html = render_reply(Tier.TIER_1, False, make_email(), ExtractedLead(location="x", bedrooms=2))
    assert "Plexa Housing" in html
    assert "Las Vegas Property Management" not in html


def test_format_budget_is_the_number_they_are_looking_for():
    # Single stated figure (current extraction: min == max)
    assert _format_budget(1800, 1800) == "$1,800/mo"
    assert _format_budget(None, 2000) == "$2,000/mo"
    assert _format_budget(1200, None) == "$1,200/mo"
    # Legacy ±10% bands still collapse to the stated figure
    assert _format_budget(1620, 1980) == "$1,800/mo"
    # Only a true two-bound range stays a range
    assert _format_budget(1200, 1500) == "$1,200 – $1,500/mo"
    assert _format_budget(None, None) is None


def test_recap_budget_uses_stated_amount(make_email):
    lead = ExtractedLead(
        zip_code="89052", bedrooms=2, move_in_date="ASAP",
        budget_min=1800, budget_max=1800,
    )
    _, html = render_reply(Tier.TIER_1, False, make_email(), lead)
    assert "$1,800/mo" in html
    assert "$1,800 – $" not in html
    assert "Up to $" not in html


def test_sender_name_and_values_are_escaped(make_email):
    email = make_email(sender_name="<b>Bob</b> Smith")
    lead = ExtractedLead(location="<script>alert(1)</script>", bedrooms=2, notes="a & b", pets=["1 <dog>"])
    subject, html = render_reply(Tier.TIER_1, False, email, lead)
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Hi &lt;b&gt;Bob&lt;/b&gt;," in html
    assert "a &amp; b" not in html
    assert "Notes" not in html
    assert "1 &lt;dog&gt;" in html


def test_subject_is_reply_to_original(make_email):
    subject, _ = render_reply(Tier.TIER_2, False, make_email(subject="3BR in Summerlin?"), ExtractedLead(location="x", bedrooms=3))
    assert subject == "Re: 3BR in Summerlin?"
    subject2, _ = render_reply(Tier.TIER_2, False, make_email(subject="Re: 3BR in Summerlin?"), ExtractedLead(location="x", bedrooms=3))
    assert subject2 == "Re: 3BR in Summerlin?"
    subject3, _ = render_reply(Tier.TIER_3, False, make_email(subject=""), ExtractedLead())
    assert subject3 == "Your rental inquiry — Plexa Housing"


def test_upgrade_uses_upgrade_template(make_email):
    _, html = render_reply(Tier.TIER_1, True, make_email(), ExtractedLead(location="Henderson", bedrooms=2, budget_max=1800))
    assert "exactly what we needed" in html


def test_tier3_asks_only_missing_gate_questions(make_email):
    _, html = render_reply(Tier.TIER_3, False, make_email(), ExtractedLead(location="Henderson", bedrooms=2))
    assert "ZIP" in html
    assert "move in" in html
    assert "How many bedrooms" not in html
    assert "What area of Las Vegas" not in html


def test_tier2_soft_ask_is_a_bonus_question(make_email):
    _, html = render_reply(Tier.TIER_2, False, make_email(), ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="ASAP"))
    assert "monthly budget" in html
    assert "ZIP" not in html


def test_recap_shows_zip_bathrooms_amenities_and_escapes(make_email):
    lead = ExtractedLead(zip_code="89052", bedrooms=2, move_in_date="ASAP", bathrooms=1.5,
                         amenities=["Pool", "<b>Yard</b>"], phone="7025551234")
    _, html = render_reply(Tier.TIER_1, False, make_email(), lead)
    assert "Zip Code" in html and "89052" in html
    assert "Bathrooms" in html and "1.5" in html
    assert "Amenities" in html and "Pool, &lt;b&gt;Yard&lt;/b&gt;" in html
    assert "7025551234" not in html


def test_studio_renders_as_studio(make_email):
    _, html = render_reply(Tier.TIER_2, False, make_email(), ExtractedLead(location="89102", bedrooms=0))
    assert "Studio" in html


def test_legacy_renderer_still_works(make_email):
    assert "Plexa Housing" in render_email_for_tier(Tier.TIER_1, make_email(), ExtractedLead(location="x", bedrooms=1, pets=[]))


def test_long_values_are_clipped(make_email):
    _, html = render_reply(Tier.TIER_1, False, make_email(), ExtractedLead(location="x" * 200, bedrooms=2, pets=["y" * 200]))
    assert "x" * 80 + "\u2026" in html
    assert "x" * 81 not in html
    assert "y" * 80 + "\u2026" in html
    assert "y" * 81 not in html
