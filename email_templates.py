"""
Plexa Housing — Email Templates
Tier-specific HTML email renderer.
"""

from html import escape as _esc

from models import InboundEmail, ExtractedLead, Tier
from validation import get_missing_field_questions


BRAND_HEADER = """
<div style="background-color:#1a365d; padding:20px 30px; border-radius:8px 8px 0 0;">
  <h1 style="color:#ffffff; margin:0; font-family:Arial,sans-serif; font-size:22px;">
    Plexa Housing
  </h1>
  <p style="color:#a0c4ff; margin:4px 0 0; font-family:Arial,sans-serif; font-size:13px;">
    Las Vegas Property Management
  </p>
</div>
"""

BRAND_FOOTER = """
<div style="background-color:#f0f4f8; padding:16px 30px; border-radius:0 0 8px 8px; border-top:1px solid #e2e8f0;">
  <p style="color:#64748b; font-family:Arial,sans-serif; font-size:12px; margin:0;">
    Plexa Housing · Las Vegas, NV<br>
    This is an automated message. Reply to this email and a team member will follow up.
  </p>
</div>
"""


def _wrap_body(body_html: str) -> str:
    return f"""
    <div style="max-width:600px; margin:0 auto; font-family:Arial,sans-serif;">
      {BRAND_HEADER}
      <div style="padding:24px 30px; background:#ffffff;">
        {body_html}
      </div>
      {BRAND_FOOTER}
    </div>
    """


def _recap_table(lead: ExtractedLead) -> str:
    """Build an HTML table summarizing extracted data. Every value is escaped."""
    rows = []
    fields = [
        ("Location", lead.location),
        ("Bedrooms", "Studio" if lead.bedrooms == 0 else lead.bedrooms),
        ("Budget", _format_budget(lead.budget_min, lead.budget_max)),
        ("Move-in Date", lead.move_in_date),
        ("Pets", ", ".join(lead.pets) if lead.pets else ("None" if lead.pets == [] else None)),
        ("Occupants", lead.occupants),
        ("Lease Duration", f"{lead.duration_months} months" if lead.duration_months else None),
    ]
    for label, value in fields:
        if value is not None:
            rows.append(
                f'<tr><td style="padding:6px 12px; color:#64748b; font-size:13px;">{label}</td>'
                f'<td style="padding:6px 12px; font-weight:bold; font-size:13px;">{_esc(str(value))}</td></tr>'
            )
    if lead.notes:
        rows.append(
            f'<tr><td style="padding:6px 12px; color:#64748b; font-size:13px;">Notes</td>'
            f'<td style="padding:6px 12px; font-size:13px;">{_esc(lead.notes)}</td></tr>'
        )
    return f"""
    <table style="width:100%; border-collapse:collapse; background:#f8fafc; border-radius:6px; margin:16px 0;">
      <thead><tr><td colspan="2" style="padding:10px 12px; font-weight:bold; color:#1a365d; border-bottom:1px solid #e2e8f0;">
        What We Heard
      </td></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def _format_budget(min_val, max_val):
    if min_val and max_val:
        return f"${min_val:,.0f} – ${max_val:,.0f}/mo"
    elif max_val:
        return f"Up to ${max_val:,.0f}/mo"
    elif min_val:
        return f"From ${min_val:,.0f}/mo"
    return None


def _question_list(questions: list) -> str:
    items = "".join(
        f'<li style="margin:6px 0; color:#334155;">{_esc(q)}</li>' for q in questions
    )
    return f"""
    <div style="background:#fffbeb; border-left:4px solid #f59e0b; padding:12px 16px; margin:16px 0; border-radius:0 6px 6px 0;">
      <p style="margin:0 0 8px; font-weight:bold; color:#92400e;">Quick question(s) to help us match you faster:</p>
      <ul style="margin:0; padding-left:20px;">{items}</ul>
    </div>
    """


def render_tier1_email(email: InboundEmail, lead: ExtractedLead) -> str:
    """Tier 1 — Full confirmation with recap table."""
    body = f"""
    <p style="color:#334155; line-height:1.6;">Hi {_esc(email.first_name)},</p>
    <p style="color:#334155; line-height:1.6;">
      Thanks for reaching out! We've got everything we need to start looking for the right place for you.
      Here's what we picked up from your message:
    </p>
    {_recap_table(lead)}
    <p style="color:#334155; line-height:1.6;">
      We're already running a match against our available properties. You'll hear back from us shortly
      with options that fit your criteria.
    </p>
    <p style="color:#334155; line-height:1.6;">Talk soon,<br><strong>Ryan</strong><br>Plexa Housing</p>
    """
    return _wrap_body(body)


def render_tier2_email(email: InboundEmail, lead: ExtractedLead) -> str:
    """Tier 2 — Match + soft follow-up question."""
    questions = get_missing_field_questions(lead)[:1]  # One soft ask
    body = f"""
    <p style="color:#334155; line-height:1.6;">Hi {_esc(email.first_name)},</p>
    <p style="color:#334155; line-height:1.6;">
      Thanks for your inquiry! We've started looking into options for you based on what you shared:
    </p>
    {_recap_table(lead)}
    {_question_list(questions) if questions else ''}
    <p style="color:#334155; line-height:1.6;">
      No rush — just hit reply whenever you get a chance. We're working on matches in the meantime.
    </p>
    <p style="color:#334155; line-height:1.6;">Best,<br><strong>Ryan</strong><br>Plexa Housing</p>
    """
    return _wrap_body(body)


def render_tier3_email(email: InboundEmail, lead: ExtractedLead) -> str:
    """Tier 3 — Missing gate fields. Ask before matching."""
    questions = [
        q for q in get_missing_field_questions(lead)
        if any(kw in q.lower() for kw in ["area", "bedroom"])
    ]
    body = f"""
    <p style="color:#334155; line-height:1.6;">Hi {_esc(email.first_name)},</p>
    <p style="color:#334155; line-height:1.6;">
      Thanks for reaching out to Plexa Housing! We'd love to help you find the right rental.
    </p>
    <p style="color:#334155; line-height:1.6;">
      To get started on a search, we just need a couple of details:
    </p>
    {_question_list(questions)}
    <p style="color:#334155; line-height:1.6;">
      Just hit reply with those details and we'll start matching you right away.
    </p>
    <p style="color:#334155; line-height:1.6;">Thanks!<br><strong>Ryan</strong><br>Plexa Housing</p>
    """
    return _wrap_body(body)


def render_upgrade_email(email: InboundEmail, lead: ExtractedLead) -> str:
    """Upgrade confirmation — Tier 3 replied with missing data."""
    body = f"""
    <p style="color:#334155; line-height:1.6;">Hi {_esc(email.first_name)},</p>
    <p style="color:#334155; line-height:1.6;">
      Perfect — that's exactly what we needed! Here's your updated search profile:
    </p>
    {_recap_table(lead)}
    <p style="color:#334155; line-height:1.6;">
      We're now running a full match against our available inventory. Expect to hear back shortly.
    </p>
    <p style="color:#334155; line-height:1.6;">Talk soon,<br><strong>Ryan</strong><br>Plexa Housing</p>
    """
    return _wrap_body(body)


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
