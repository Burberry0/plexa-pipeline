from email_templates import render_email_for_tier, render_reply
from models import ExtractedLead, Tier


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
    _, html = render_reply(Tier.TIER_3, False, make_email(), ExtractedLead(bedrooms=2))
    assert "What area of Las Vegas" in html
    assert "How many bedrooms" not in html


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
