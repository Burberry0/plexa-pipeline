"""
Plexa Housing — Pipeline Orchestrator
Calls every module in sequence. Owns the PipelineResult.
Handles errors without crashing.
"""

import time
import logging
from typing import Optional

from models import (
    InboundEmail,
    PipelineResult,
    Classification,
    LeadStatus,
)
from config import PipelineConfig
from ai_client import AIClient
from validation import classify_tier, tier_summary

logger = logging.getLogger("plexa.pipeline")


class Pipeline:
    """
    Main orchestrator. Processes a single email through the full chain:
      1. Junk filter (Haiku)
      2. AI extraction (Opus) — only if LEAD
      3. Tier classification — only if extracted
      4. Airtable upsert — Tier 1/2 only (stubbed for demo)
      5. Auto-reply — with guardrails (stubbed for demo)
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.ai = AIClient(config)

    def process_email(self, email: InboundEmail) -> PipelineResult:
        """
        Process a single email through the full pipeline.
        Returns PipelineResult with all data populated.
        """
        start_time = time.time()
        result = PipelineResult(
            email=email,
            classification=Classification.JUNK,  # default
        )

        try:
            # ── Step 1: Junk Filter ──────────────────────────
            classification, junk_tokens = self.ai.classify_email(email)
            result.classification = classification
            result.junk_filter_tokens = junk_tokens

            if classification == Classification.JUNK:
                logger.info(f"JUNK — stopped pipeline for {email.sender_email}")
                result.processing_time_ms = (time.time() - start_time) * 1000
                return result

            # ── Step 2: AI Extraction ────────────────────────
            extracted, extract_tokens = self.ai.extract_lead(email)
            result.extracted = extracted
            result.extraction_tokens = extract_tokens

            # ── Step 3: Tier Classification ──────────────────
            tier = classify_tier(extracted)
            result.tier = tier

            # Set initial status based on tier
            if tier.value == "Tier 1":
                result.status = LeadStatus.NEW
            elif tier.value == "Tier 2":
                result.status = LeadStatus.NEEDS_REVIEW
            else:
                result.status = LeadStatus.ON_HOLD

            logger.info(
                f"LEAD — {tier.value} | confidence={extracted.confidence} | "
                f"from={email.sender_email}"
            )

            # ── Step 4: Airtable Upsert (stub) ──────────────
            # TODO: Wire up airtable_client.py for production
            # For demo, we log the record that would be created
            logger.info(f"[STUB] Would upsert to Airtable: {email.sender_email}")

            # ── Step 5: Auto-Reply (stub) ────────────────────
            # TODO: Wire up email_templates.py + Gmail sender
            logger.info(f"[STUB] Would send {tier.value} auto-reply to {email.sender_email}")
            result.auto_reply_sent = False  # Will be True in production

        except Exception as e:
            logger.error(f"Pipeline error for {email.sender_email}: {e}", exc_info=True)
            result.error = str(e)
            result.status = LeadStatus.MANUAL_REVIEW

        result.processing_time_ms = (time.time() - start_time) * 1000
        return result

    def process_batch(self, emails: list) -> list:
        """Process a batch of emails. Returns list of PipelineResults."""
        results = []
        for i, email in enumerate(emails, 1):
            logger.info(f"Processing {i}/{len(emails)}: {email.sender_email}")
            result = self.process_email(email)
            results.append(result)
        return results
