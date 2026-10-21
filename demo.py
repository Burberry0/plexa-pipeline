"""
Plexa Housing — Demo Runner
Processes sample emails through the full pipeline.
Outputs structured JSON results for the demo UI.

Usage:
  python demo.py            # AI key from env or .env (OPENCODE_API_KEY or OPENAI_API_KEY)
  python demo.py --json     # machine-readable output
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone

from config import PipelineConfig
from pipeline import Pipeline
from ingestion import DirectInputAdapter
from validation import tier_summary, get_missing_field_questions
from email_templates import render_email_for_tier

# ── Logging Setup ───────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("plexa.demo")


# ── Sample Emails ───────────────────────────────────────────────────────────

SAMPLE_EMAILS = [
    {
        "id": "tier1_full",
        "label": "Tier 1 — Match-ready (zip 89052, 2BR, move-in, budget, pets)",
        "sender_name": "Sarah Johnson",
        "sender_email": "sarah.j@gmail.com",
        "subject": "Looking for 2BR apartment",
        "body": (
            "Hi, I'm moving to Las Vegas on June 15th and need a 2 bedroom apartment. "
            "Budget around $1800/month. I have a small dog. "
            "Looking for something in Henderson, zip code 89052. "
            "It'll be me and my husband. Thanks!"
        ),
    },
    {
        "id": "tier2_gates_only",
        "label": "Tier 2 — Gate Fields Only (zip + bedrooms + ASAP, no extras)",
        "sender_name": "James Chen",
        "sender_email": "jchen.lv@yahoo.com",
        "subject": "3BR rental in Summerlin?",
        "body": (
            "Hi there, do you have any 3 bedroom places available in 89135? "
            "I need to move ASAP. Let me know what you've got."
        ),
    },
    {
        "id": "tier3_vague",
        "label": "Tier 3 — Vague Inquiry (missing gate fields)",
        "sender_name": "Mike Torres",
        "sender_email": "mike.torres@yahoo.com",
        "subject": "Question",
        "body": "Hey do you guys have any places available? Looking to move soon.",
    },
    {
        "id": "tier1_section8",
        "label": "Tier 1 — Section 8 Lead (studio, zip, budget, notes)",
        "sender_name": "Linda Williams",
        "sender_email": "lwilliams88@hotmail.com",
        "subject": "Studio or 1BR - Section 8",
        "body": (
            "I'm looking for a studio or 1BR in zip code 89102. Budget up to $1200. "
            "I'm on Section 8. Move-in date flexible but prefer by end of July. "
            "Just me, no pets."
        ),
    },
    {
        "id": "tier3_missing_zip",
        "label": "Tier 3 — Neighborhood but no ZIP (asked for a zip code)",
        "sender_name": "Priya Nair",
        "sender_email": "priya.nair@gmail.com",
        "subject": "2BR in Henderson",
        "body": (
            "Hello! We're relocating and need a 2 bedroom in Henderson starting November 1st. "
            "Budget is up to $2,000 a month. Two adults, no pets."
        ),
    },
    {
        "id": "tier1_company_with_pets_amenities",
        "label": "Tier 1 — Company request with pets, amenities, phone",
        "sender_name": "Dana Whitfield",
        "sender_email": "dana.whitfield@acmerelocation.com",
        "subject": "Furnished 3BR/2BA for relocating engineer - 89147",
        "body": (
            "Hi, I'm with Acme Relocation placing one of our client's engineers in Las Vegas. "
            "We need a furnished 3 bedroom, 2 bath single-story home in zip 89147 with a pool and a 2-car garage, "
            "move-in October 20, 2026, 6 month lease. Two adults and one child. "
            "They have two dogs: a 40 lb Husky and a 10 lb Chihuahua. Budget up to $3,500.\n\n"
            "Dana Whitfield\nAcme Relocation\n(702) 555-0199"
        ),
    },
    {
        "id": "junk_newsletter",
        "label": "JUNK — Newsletter / Marketing",
        "sender_name": "Marketing Team",
        "sender_email": "noreply@propertyvendor.com",
        "subject": "Exclusive Offer: Property Management Software",
        "body": (
            "Streamline your rental business with our all-in-one platform! "
            "Click here for a free demo. Limited time offer. "
            "Manage listings, tenants, and maintenance all in one place."
        ),
    },
    {
        "id": "junk_ooo",
        "label": "JUNK — Out-of-Office Auto-Reply",
        "sender_name": "David Park",
        "sender_email": "david.park@company.com",
        "subject": "Re: Your inquiry - Out of Office",
        "body": (
            "Thank you for your message. I am currently out of the office "
            "from March 28 to April 5 with limited access to email. "
            "I will respond to your message upon my return."
        ),
    },
    {
        "id": "junk_vendor",
        "label": "JUNK — Vendor Sales Pitch",
        "sender_name": "Alex from RentTech",
        "sender_email": "alex@renttech.io",
        "subject": "Boost your occupancy rates by 30%",
        "body": (
            "Hi Ryan, I noticed Plexa Housing has some vacancies. "
            "Our AI-powered listing optimization tool has helped property managers "
            "like you increase occupancy by 30% in just 90 days. "
            "Can I schedule a quick 15-minute demo?"
        ),
    },
]


# ── Demo Runner ─────────────────────────────────────────────────────────────

def run_demo(output_json: bool = False):
    """Run the full pipeline demo with sample emails."""

    # Config
    config = PipelineConfig.from_env()
    if not config.has_ai_key:
        print("ERROR: set OPENCODE_API_KEY (OpenCode Go) or OPENAI_API_KEY in the environment or .env.")
        print("Usage: python demo.py")
        sys.exit(1)

    # Initialize
    pipeline = Pipeline(config)
    adapter = DirectInputAdapter()

    # Load sample emails
    for sample in SAMPLE_EMAILS:
        adapter.add_email(
            sender_email=sample["sender_email"],
            sender_name=sample["sender_name"],
            subject=sample["subject"],
            body=sample["body"],
        )

    emails = adapter.fetch_emails()
    print(f"\n{'='*70}")
    print(f"  PLEXA HOUSING — Email Intake Pipeline Demo")
    print(f"  Processing {len(emails)} sample emails")
    print(f"  Junk filter: {config.junk_filter_model}")
    print(f"  Extraction:  {config.extraction_model}")
    print(f"  Timestamp:   {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"{'='*70}\n")

    # Process
    all_results = []
    total_tokens = 0
    leads = 0
    junk = 0

    for i, email in enumerate(emails):
        sample = SAMPLE_EMAILS[i]
        print(f"\n{'─'*70}")
        print(f"  [{i+1}/{len(emails)}] {sample['label']}")
        print(f"  From: {email.sender_name} <{email.sender_email}>")
        print(f"  Subject: {email.subject}")
        print(f"{'─'*70}")

        result = pipeline.process_email(email, persist=False)
        result_dict = result.to_dict()

        # Track stats
        total_tokens += result.junk_filter_tokens + result.extraction_tokens
        if result.is_lead:
            leads += 1
        else:
            junk += 1

        # Display
        if result.classification.value == "JUNK":
            print(f"  ❌ JUNK — Filtered out ({result.junk_filter_tokens} tokens, {result.processing_time_ms:.0f}ms)")
        else:
            print(f"  ✅ LEAD → {result.tier.value}")
            print(f"  ⏱️  Processing: {result.processing_time_ms:.0f}ms | Tokens: {result.junk_filter_tokens + result.extraction_tokens}")

            if result.extracted:
                ext = result.extracted
                print(f"\n  📊 Extraction Results:")
                print(f"     Location:    {ext.location or '—'}")
                print(f"     Zip Code:    {ext.zip_code or '—'}")
                print(f"     Bedrooms:    {'Studio' if ext.bedrooms == 0 else (ext.bedrooms or '—')}")
                print(f"     Bathrooms:   {ext.bathrooms or '—'}")
                if ext.budget_min or ext.budget_max:
                    bmin = f"${ext.budget_min:,.0f}" if ext.budget_min else "—"
                    bmax = f"${ext.budget_max:,.0f}" if ext.budget_max else "—"
                    print(f"     Budget:      {bmin} – {bmax}/mo")
                else:
                    print(f"     Budget:      —")
                print(f"     Move-in:     {ext.move_in_date or '—'}")
                print(f"     Pets:        {', '.join(ext.pets) if ext.pets else ('None' if ext.pets == [] else '—')}")
                print(f"     Occupants:   {ext.occupants or '—'}")
                print(f"     Duration:    {f'{ext.duration_months} months' if ext.duration_months else '—'}")
                print(f"     Amenities:   {', '.join(ext.amenities) if ext.amenities else ('None' if ext.amenities == [] else '—')}")
                print(f"     Phone:       {ext.phone or '—'}")
                print(f"     Requester:   {ext.requester_type or '—'}{f' ({ext.company_name})' if ext.company_name else ''}")
                print(f"     Confidence:  {ext.confidence}")
                if ext.missing_fields:
                    print(f"     Missing:     {', '.join(ext.missing_fields)}")
                if ext.notes:
                    print(f"     Notes:       {ext.notes}")

            # Tier summary
            if result.tier and result.extracted:
                ts = tier_summary(result.tier, result.extracted)
                print(f"\n  🎯 Tier Action: {ts['action']}")
                if "follow_up_questions" in ts and ts["follow_up_questions"]:
                    print(f"     Follow-up: {ts['follow_up_questions'][0]}")

            # Property-matching hand-off
            if result.match_ready:
                mr = result.match_request
                print(f"\n  🏠 Match request ready → zip {mr['zip_code']}, {mr['bedrooms']}BR, "
                      f"move-in {mr['move_in_date']}")
            elif result.extracted:
                print(f"\n  ⏸️  Not match-ready — missing: {', '.join(result.match_missing_fields)}")

        all_results.append(result_dict)

    # Summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Total emails:  {len(emails)}")
    print(f"  Leads:         {leads} ({leads/len(emails)*100:.0f}%)")
    print(f"  Junk:          {junk} ({junk/len(emails)*100:.0f}%)")
    print(f"  Total tokens:  {total_tokens}")
    print(f"{'='*70}\n")

    # JSON output
    if output_json:
        output = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "config": {
                "junk_filter_model": config.junk_filter_model,
                "extraction_model": config.extraction_model,
            },
            "summary": {
                "total": len(emails),
                "leads": leads,
                "junk": junk,
                "total_tokens": total_tokens,
            },
            "results": all_results,
        }
        json_path = "demo_results.json"
        with open(json_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"  JSON results written to {json_path}\n")
        return output

    return all_results


def run_single(body: str, sender_name: str = "Demo User", sender_email: str = "demo@test.com", subject: str = "Rental inquiry"):
    """Run a single email through the pipeline. For API/interactive use."""
    config = PipelineConfig.from_env()
    if not config.has_ai_key:
        raise ValueError("OPENCODE_API_KEY or OPENAI_API_KEY not set")

    pipeline = Pipeline(config)
    adapter = DirectInputAdapter()
    email = adapter.add_email(
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        body=body,
    )
    result = pipeline.process_email(email, persist=False)
    return result.to_dict()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plexa Housing Pipeline Demo")
    parser.add_argument("--json", action="store_true", help="Output results as JSON file")
    args = parser.parse_args()
    run_demo(output_json=args.json)
