"""
Plexa Housing — AI Client
Two GPT calls: cheap junk filter (gpt-4o-mini) then structured extraction (gpt-4o).
Anti-hallucination contract enforced here.
"""

import json
import time
import logging
from typing import Tuple, Optional
from openai import OpenAI

from models import InboundEmail, ExtractedLead, Classification
from config import PipelineConfig

logger = logging.getLogger("plexa.ai_client")


# ── Prompt Definitions ──────────────────────────────────────────────────────

JUNK_FILTER_SYSTEM_PROMPT = """You are a rental inquiry classifier for Plexa Housing, a property management company in Las Vegas.

Your ONLY job is to determine if an inbound email represents a genuine rental inquiry or if it's noise (spam, newsletters, automated messages).

RESPONSE RULES:
- Output EXACTLY one word: either "LEAD" or "JUNK"
- No punctuation, no explanation, no preamble
- No markdown formatting
- Just the single word

CLASSIFY AS LEAD if the email contains ANY of:
- Someone looking to rent a property
- Questions about available units or rentals
- Mentions of location, bedrooms, budget, or move-in date
- Inquiries about rental requirements, applications, or scheduling viewings
- Even vague rental intent ("looking for a place", "need housing")

CLASSIFY AS JUNK if the email is:
- Newsletters, marketing emails, promotional content
- Vendor pitches, service offers, sales outreach
- Automated replies (out-of-office, delivery failures, system notifications)
- Spam, phishing attempts
- Unrelated business correspondence

WHEN IN DOUBT: Choose LEAD. A false positive costs one extra extraction call.
A false negative costs a lost customer."""

JUNK_FILTER_USER_TEMPLATE = """Classify this email as LEAD or JUNK:

FROM: {sender_name} <{sender_email}>
SUBJECT: {subject}

EMAIL BODY:
{body}"""


EXTRACTION_SYSTEM_PROMPT = """You are a structured data extractor for Plexa Housing, a property management company in Las Vegas.

You will receive an email from a prospective renter. Extract rental requirements into a strict JSON schema.

CRITICAL RULES — ANTI-HALLUCINATION:
1. NULL OVER GUESS: If a field is not explicitly stated in the email, set it to null. Never infer, assume, or guess.
2. EXACT SCHEMA ONLY: Return ONLY valid JSON with exactly these 12 fields. No extra fields, no explanation, no preamble.
3. NO MARKDOWN: Your response must start with { and end with }. No fences, no backticks, no formatting.
4. PRESERVE ORIGINAL LANGUAGE: Keep location names, pet descriptions exactly as written.
5. SELF-SCORE: The confidence field is your honest assessment (0.0 to 1.0) of extraction completeness.
6. MISSING FIELDS AWARENESS: List any important fields that would help matching but are absent.

JSON SCHEMA (12 fields):
{
  "location": string | null,          // City, zip code, neighborhood — exactly as written
  "bedrooms": integer | null,         // Number of bedrooms (0 for studio)
  "budget_min": float | null,         // Minimum monthly rent
  "budget_max": float | null,         // Maximum monthly rent
  "move_in_date": string | null,      // ISO date (YYYY-MM-DD) or "ASAP"
  "pets": array | null,               // e.g. ["1 dog", "2 cats"] or [] for "no pets"
  "occupants": integer | null,        // Total number of people moving in
  "duration_months": integer | null,  // Preferred lease length in months
  "pet_friendly_required": boolean | null,  // Only true if EXPLICITLY required
  "confidence": float,                // 0.0 to 1.0 self-assessment
  "missing_fields": array,            // Fields absent but would help matching
  "notes": string | null              // Edge cases: Section 8, accessibility, etc.
}

FIELD CONVERSION RULES:

Bedrooms:
  "1 bedroom", "1BR", "1bd" → 1
  "studio" → 0
  "2br", "two bedroom" → 2
  Range ("2-3 bedrooms") → use lower bound (2)
  Not mentioned → null

Budget:
  "around $1500" → min: 1350, max: 1650 (±10%)
  "up to $2000" → min: null, max: 2000
  "$1200-$1500" → min: 1200, max: 1500
  "$1500/month" → min: 1500, max: 1500
  Not mentioned → null for both

Move-in Date:
  "June 15th" → "2026-06-15"
  "next month", "ASAP", "soon" → "ASAP"
  "end of summer" → "ASAP"
  Not mentioned → null

Pets:
  "I have a dog" → ["1 dog"]
  "two cats and a small dog" → ["2 cats", "1 dog"]
  "no pets" → []
  "I have pets" (vague) → ["pets (unspecified)"]
  Not mentioned → null

Occupants:
  "me and my wife" → 2
  "family of four" → 4
  "just me" → 1
  Not mentioned → null

Confidence scoring:
  All 3 gate fields present (location, bedrooms, budget) → 0.8-1.0
  2 gate fields → 0.5-0.7
  1 or fewer → 0.2-0.4"""

EXTRACTION_USER_TEMPLATE = """Extract rental requirements from this email:

FROM: {sender_name} <{sender_email}>
SUBJECT: {subject}

EMAIL BODY:
{body}"""


# ── Prompt Version Registry ─────────────────────────────────────────────────

PROMPTS = {
    "junk_filter": {
        "version": "1.0.0",
        "last_updated": "2026-03-26",
        "system_prompt": JUNK_FILTER_SYSTEM_PROMPT,
        "user_template": JUNK_FILTER_USER_TEMPLATE,
    },
    "extraction": {
        "version": "1.0.0",
        "last_updated": "2026-03-26",
        "system_prompt": EXTRACTION_SYSTEM_PROMPT,
        "user_template": EXTRACTION_USER_TEMPLATE,
    },
}


class AIClient:
    """Handles all OpenAI API interactions for the Plexa pipeline."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.client = OpenAI(api_key=config.openai_api_key)
        logger.info(
            f"AIClient initialized | junk_filter={config.junk_filter_model} "
            f"| extraction={config.extraction_model}"
        )

    def classify_email(self, email: InboundEmail) -> Tuple[Classification, int]:
        """
        Junk filter — binary LEAD/JUNK classification via gpt-4o-mini.
        Returns (Classification, input+output tokens used).
        """
        user_message = PROMPTS["junk_filter"]["user_template"].format(
            sender_name=email.sender_name,
            sender_email=email.sender_email,
            subject=email.subject,
            body=email.body_plain[:3000],  # Cap body length for cost
        )

        start = time.time()
        response = self.client.chat.completions.create(
            model=self.config.junk_filter_model,
            max_tokens=self.config.junk_filter_max_tokens,
            temperature=0.0,
            messages=[
                {"role": "system", "content": PROMPTS["junk_filter"]["system_prompt"]},
                {"role": "user", "content": user_message},
            ],
        )
        elapsed_ms = (time.time() - start) * 1000

        raw = response.choices[0].message.content.strip().upper()
        tokens = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

        classification = Classification.LEAD if "LEAD" in raw else Classification.JUNK
        logger.info(
            f"Junk filter: {classification.value} | "
            f"raw='{raw}' | {elapsed_ms:.0f}ms | {tokens} tokens | "
            f"from={email.sender_email}"
        )
        return classification, tokens

    def extract_lead(self, email: InboundEmail) -> Tuple[ExtractedLead, int]:
        """
        Structured extraction via gpt-4o. Only called on LEADs.
        Returns (ExtractedLead, input+output tokens used).
        """
        user_message = PROMPTS["extraction"]["user_template"].format(
            sender_name=email.sender_name,
            sender_email=email.sender_email,
            subject=email.subject,
            body=email.body_plain[:5000],  # Larger cap for extraction
        )

        start = time.time()
        response = self.client.chat.completions.create(
            model=self.config.extraction_model,
            max_tokens=self.config.extraction_max_tokens,
            temperature=0.0,
            messages=[
                {"role": "system", "content": PROMPTS["extraction"]["system_prompt"]},
                {"role": "user", "content": user_message},
            ],
        )
        elapsed_ms = (time.time() - start) * 1000

        raw_text = response.choices[0].message.content.strip()
        tokens = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)

        logger.info(
            f"Extraction complete | {elapsed_ms:.0f}ms | {tokens} tokens | "
            f"from={email.sender_email}"
        )

        # Parse and validate
        data = self._validate_extraction(raw_text)
        lead = ExtractedLead(
            location=data.get("location"),
            bedrooms=data.get("bedrooms"),
            budget_min=data.get("budget_min"),
            budget_max=data.get("budget_max"),
            move_in_date=data.get("move_in_date"),
            pets=data.get("pets"),
            occupants=data.get("occupants"),
            duration_months=data.get("duration_months"),
            pet_friendly_required=data.get("pet_friendly_required"),
            confidence=data.get("confidence", 0.0),
            missing_fields=data.get("missing_fields", []),
            notes=data.get("notes"),
        )
        return lead, tokens

    @staticmethod
    def _validate_extraction(response_text: str) -> dict:
        """Validate and clean AI extraction response."""
        cleaned = response_text.strip()

        # Strip markdown fences if model disobeyed
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        data = json.loads(cleaned)

        required_fields = [
            "location", "bedrooms", "budget_min", "budget_max",
            "move_in_date", "pets", "occupants", "duration_months",
            "pet_friendly_required", "confidence", "missing_fields", "notes",
        ]

        for field in required_fields:
            if field not in data:
                logger.warning(f"Missing required field in extraction: {field}")
                data[field] = None

        extra_fields = set(data.keys()) - set(required_fields)
        if extra_fields:
            logger.warning(f"Extra fields in extraction (discarded): {extra_fields}")
            for ef in extra_fields:
                del data[ef]

        # Enforce types
        if data.get("confidence") is not None:
            data["confidence"] = float(data["confidence"])
        if data.get("missing_fields") is None:
            data["missing_fields"] = []

        return data
