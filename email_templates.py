"""
Plexa Housing — Email Templates
Tier-specific HTML email renderer.

Styled to match the Monday landlord email (RyanPlexa email/confirm-mail-core.js)
so both messages read as the same company. Tables and inline styles only, with
literal colours: Outlook renders with Word and drops flexbox, <style> blocks and
CSS custom properties.
"""

from datetime import date
from html import escape as _esc

from models import InboundEmail, ExtractedLead, Tier
from validation import bonus_questions, gate_questions


# Approved palette only (RyanPlexa design/plexa-design.md).
TEAL = "#27A3A5"
TINT_TEAL = "#F1F9F9"
INK = "#282828"
INK_2 = "#5F5C57"
INK_3 = "#8E8A82"
PAGE = "#FAF8F3"
LINE = "#E7E3D9"
LINE_2 = "#F2EFEA"
WHITE = "#FFFFFF"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif"

# n8n's Gmail Reply node sends HTML only and cannot attach a cid: image, so the
# logo is the hosted copy of design/plexa-logo-email.png (teal baked in, 2x).
# Clients that block remote images show the alt text, styled to read as the
# wordmark on the teal band.
LOGO_URL = "https://availablity-check.vercel.app/api/logo.png"
LOGO_WIDTH = 280
LOGO_HEIGHT = 44

BODY_STYLE = f"font:16px/1.6 {FONT};color:{INK};"
SMALL_STYLE = f"font:13px/1.55 {FONT};color:{INK_2};"

FOOTER_NOTE = (
    "Plexa Housing · Las Vegas, NV<br>"
    "This is an automated message. Reply to this email and a team member will follow up."
)


def _p(html: str, bottom: int = 18) -> str:
    return f'<p style="margin:0 0 {bottom}px;{BODY_STYLE}">{html}</p>'


def _signoff(closing: str) -> str:
    return _p(f"{closing}<br><strong>Ryan</strong><br>Plexa Housing", bottom=0)


def _logo() -> str:
    return (
        f'<img src="{LOGO_URL}" alt="Plexa Housing" width="{LOGO_WIDTH}" height="{LOGO_HEIGHT}" '
        f'style="display:block;border:0;outline:none;text-decoration:none;'
        f'font:700 13px/1 {FONT};letter-spacing:.16em;text-transform:uppercase;color:{WHITE};">'
    )


def _preheader(text: str) -> str:
    # Inbox preview line. Without it clients show the first body words ("Hi Sarah,").
    # The zero-width padding stops them pulling body text in after it.
    return (
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
        f'font-size:1px;line-height:1px;color:{PAGE};">{_esc(text)}'
        + "&#8203;&nbsp;" * 40 + '</div>'
    )


def _wrap_body(body_html: str, preheader: str) -> str:
    return (
        '<!doctype html>'
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<meta name="supported-color-schemes" content="light">'
        '<title>Plexa Housing</title></head>'
        f'<body style="margin:0;padding:0;background:{PAGE};">'
        f'{_preheader(preheader)}'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{PAGE};"><tr><td align="center" style="padding:28px 12px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:520px;background:{WHITE};border:1px solid {LINE};border-radius:14px;">'
        f'<tr><td bgcolor="{TEAL}" style="background:{TEAL};border-radius:14px 14px 0 0;'
        f'padding:22px 26px;">{_logo()}</td></tr>'
        f'<tr><td style="padding:30px 26px 26px;">{body_html}</td></tr>'
        f'<tr><td style="padding:16px 26px 24px;border-top:1px solid {LINE_2};{SMALL_STYLE}">'
        f'{FOOTER_NOTE}</td></tr>'
        '</table></td></tr></table></body></html>'
    )


MAX_VALUE_CHARS = 80


def _clip(text: str) -> str:
    """Truncate model-copied free text so a prospect-facing reply stays short."""
    text = str(text)
    if len(text) <= MAX_VALUE_CHARS:
        return text
    return text[:MAX_VALUE_CHARS] + "\u2026"


def _format_move_in(value):
    """ISO dates read as "June 15, 2026"; anything else ("ASAP") is shown as written."""
    if value is None:
        return None
    try:
        d = date.fromisoformat(str(value).strip())
    except ValueError:
        return _clip(value)
    return f"{d:%B} {d.day}, {d.year}"


def _format_number(value):
    """2.0 → "2", 1.5 → "1.5"."""
    if value is None:
        return None
    return f"{value:g}" if isinstance(value, float) else value


def _sentence_case(text: str) -> str:
    text = _clip(text)
    return text[:1].upper() + text[1:]


def _recap_table(lead: ExtractedLead) -> str:
    """Build an HTML table summarizing extracted data. Every value is escaped.

    Free-text notes are never shown to the prospect; long values are clipped.
    """
    rows = []
    fields = [
        ("Location", _clip(lead.location) if lead.location else lead.location),
        ("Zip Code", lead.zip_code),
        ("Bedrooms", "Studio" if lead.bedrooms == 0 else lead.bedrooms),
        ("Bathrooms", _format_number(lead.bathrooms)),
        ("Budget", _format_budget(lead.budget_min, lead.budget_max)),
        ("Move-in Date", _format_move_in(lead.move_in_date)),
        ("Pets", ", ".join(_sentence_case(p) for p in lead.pets) if lead.pets else ("None" if lead.pets == [] else None)),
        ("Occupants", lead.occupants),
        ("Lease Duration", (f"{lead.duration_months} month" + ("" if lead.duration_months == 1 else "s"))
         if lead.duration_months else None),
        ("Amenities", ", ".join(_sentence_case(a) for a in lead.amenities) if lead.amenities else None),
    ]
    shown = [(label, value) for label, value in fields if value is not None]
    for i, (label, value) in enumerate(shown):
        rule = f"border-bottom:1px solid {LINE_2};" if i < len(shown) - 1 else ""
        rows.append(
            f'<tr><td style="padding:10px 2px;{rule}font:14px/1.4 {FONT};color:{INK_2};">{label}</td>'
            f'<td align="right" style="padding:10px 2px;{rule}font:600 14px/1.4 {FONT};color:{INK};">'
            f'{_esc(str(value))}</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:4px 0 22px;border:1px solid {LINE};border-radius:12px;">'
        f'<tr><td style="padding:14px 18px 4px;font:600 11.5px/1 {FONT};letter-spacing:.14em;'
        f'text-transform:uppercase;color:{INK_3};">What We Heard</td></tr>'
        '<tr><td style="padding:4px 16px 6px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"{''.join(rows)}</table></td></tr></table>"
    )


def _format_budget(min_val, max_val):
    """Show the budget number(s) the requester stated — one figure when possible.

    Prefer a single monthly amount (what they're looking for). Only show a range
    when they wrote two different bounds. Legacy ±10% extraction bands
    (e.g. ~$1800 → 1620–1980) collapse to the midpoint.
    """
    if min_val is None and max_val is None:
        return None
    if min_val is not None and max_val is not None:
        if min_val == max_val:
            return f"${min_val:,.0f}/mo"
        mid = (min_val + max_val) / 2.0
        # Old extractions expanded a single figure to ±10%; show that figure.
        if mid > 0 and abs(min_val - mid * 0.9) < 0.51 and abs(max_val - mid * 1.1) < 0.51:
            return f"${mid:,.0f}/mo"
        return f"${min_val:,.0f} – ${max_val:,.0f}/mo"
    if max_val is not None:
        return f"${max_val:,.0f}/mo"
    return f"${min_val:,.0f}/mo"


def _question_list(questions: list) -> str:
    items = "".join(
        f'<li style="margin:6px 0 0;font:15px/1.5 {FONT};color:{INK};">{_esc(q)}</li>'
        for q in questions
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:4px 0 22px;">'
        f'<tr><td bgcolor="{TINT_TEAL}" style="background:{TINT_TEAL};border-left:3px solid {TEAL};'
        'border-radius:0 12px 12px 0;padding:16px 18px;">'
        f'<p style="margin:0;font:600 14.5px/1.4 {FONT};color:{INK};">'
        f'{"A quick question" if len(questions) == 1 else "A few quick questions"} '
        'to help us match you faster:</p>'
        f'<ul style="margin:4px 0 0;padding-left:20px;">{items}</ul>'
        '</td></tr></table>'
    )


def render_tier1_email(email: InboundEmail, lead: ExtractedLead) -> str:
    """Tier 1 — Full confirmation with recap table."""
    body = (
        _p(f"Hi {_esc(email.first_name)},")
        + _p("Thanks for reaching out! We've got everything we need to start looking for the right "
             "place for you. Here's what we picked up from your message:")
        + _recap_table(lead)
        + _p("We're already running a match against our available properties. You'll hear back "
             "from us shortly with options that fit your criteria.", bottom=22)
        + _signoff("Talk soon,")
    )
    return _wrap_body(body, "We have everything we need and are matching you with available rentals now.")


def render_tier2_email(email: InboundEmail, lead: ExtractedLead) -> str:
    """Tier 2 — Match + soft follow-up question."""
    questions = bonus_questions(lead)[:1]  # One soft ask
    body = (
        _p(f"Hi {_esc(email.first_name)},")
        + _p("Thanks for your inquiry! We've started looking into options for you based on what "
             "you shared:")
        + _recap_table(lead)
        + (_question_list(questions) if questions else "")
        + _p("No rush — just hit reply whenever you get a chance. We're working on matches in "
             "the meantime.", bottom=22)
        + _signoff("Best,")
    )
    return _wrap_body(body, "Your rental search has started. Here's what we have so far.")


def render_tier3_email(email: InboundEmail, lead: ExtractedLead) -> str:
    """Tier 3 — Missing gate fields. Ask before matching."""
    questions = gate_questions(lead)
    one = len(questions) == 1
    body = (
        _p(f"Hi {_esc(email.first_name)},")
        + _p("Thanks for reaching out to Plexa Housing! We'd love to help you find the right rental.")
        + _p(f"To get started on a search, we just need {'one more detail' if one else 'a few details'}:")
        + _question_list(questions)
        + _p(f"Just hit reply with {'that' if one else 'those details'} and we'll start matching you "
             "right away.", bottom=22)
        + _signoff("Thanks!")
    )
    return _wrap_body(body, "One quick reply and we can start your rental search.")


def render_upgrade_email(email: InboundEmail, lead: ExtractedLead) -> str:
    """Upgrade confirmation — Tier 3 replied with missing data."""
    body = (
        _p(f"Hi {_esc(email.first_name)},")
        + _p("Perfect — that's exactly what we needed! Here's your updated search profile:")
        + _recap_table(lead)
        + _p("We're now running a full match against our available inventory. Expect to hear "
             "back shortly.", bottom=22)
        + _signoff("Talk soon,")
    )
    return _wrap_body(body, "Thanks, that's everything we needed. Your full match is running now.")


def render_email_for_tier(tier: Tier, email: InboundEmail, lead: ExtractedLead) -> str:
    """Route to the correct template based on tier."""
    if tier == Tier.TIER_1:
        return render_tier1_email(email, lead)
    elif tier == Tier.TIER_2:
        return render_tier2_email(email, lead)
    else:
        return render_tier3_email(email, lead)


DEFAULT_SUBJECT = "Your rental inquiry — Plexa Housing"


def reply_subject(original_subject: str) -> str:
    subject = (original_subject or "").strip()
    if not subject:
        return DEFAULT_SUBJECT
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


def render_reply(tier: Tier, is_upgrade: bool, email: InboundEmail, lead: ExtractedLead) -> tuple:
    """Return (subject, html) for the reply the pipeline decided on."""
    if is_upgrade:
        html = render_upgrade_email(email, lead)
    else:
        html = render_email_for_tier(tier, email, lead)
    return reply_subject(email.subject), html
