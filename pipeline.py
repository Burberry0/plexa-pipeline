"""
Plexa Housing — Pipeline Orchestrator
Stateless decision engine. Airtable is the only state store.
Handles errors without crashing: errors → MANUAL_REVIEW + alert.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from ai_client import AIClient
from airtable_client import (
    AirtableClient,
    iso_utc,
    lead_from_record,
    lead_to_airtable_fields,
    tier_from_record,
)
from alerts import send_alert
from config import PipelineConfig
from email_templates import render_reply
from guardrails import ReplyDecision, decide_reply
from match_request import build_match_request
from models import Classification, InboundEmail, LeadStatus, PipelineResult, Tier
from validation import classify_tier, ensure_pet_friendly_required, merge_leads, status_for_tier

logger = logging.getLogger("plexa.pipeline")

# Lead statuses the service sets itself. Any other Status on a Leads row
# (e.g. "Matched") was set by a human and is not overwritten by follow-ups.
AUTOMATIC_STATUSES = {
    LeadStatus.NEW.value,
    LeadStatus.NEEDS_REVIEW.value,
    LeadStatus.ON_HOLD.value,
    LeadStatus.MANUAL_REVIEW.value,
}


class Pipeline:
    """
    Processes a single email:
      1. Dedupe on message_id (Airtable Messages)
      2. Junk filter (cheap chat model)
      3. Extraction (strict JSON schema), merged over the sender's prior record if any
      4. Tier classification + upgrade detection; a match-ready lead (all gate
         fields) also gets a JotForm-shaped `match_request` for n8n to POST to
         the property-matching workflow once a human approves in Slack
      5. Reply decision (guardrails) + reply rendering
      6. Airtable upsert (all tiers) + message log

    The prior tier is the *effective* one: the stored extraction re-classified
    under the current gate, falling back to the Tier column only when the
    extraction is missing. Auto-replies go out only on first contact or to a
    sender whose effective prior tier was Tier 3; any other follow-up is routed
    to Needs Review for a human.
    reply_skip_reason values: "ok", "auto_reply_disabled", "max_replies_reached",
    "cooldown_active", "follow_up", "junk", "duplicate", "pipeline_error".
    """

    def __init__(
        self,
        config: PipelineConfig,
        ai=None,
        airtable=None,
        alerter: Optional[Callable[[str], bool]] = None,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config
        self.ai = ai or AIClient(config)
        if airtable is not None:
            self.airtable = airtable
        elif config.has_airtable_config:
            self.airtable = AirtableClient(config)
        else:
            self.airtable = None
        self.alert = alerter or (lambda text: send_alert(config.alert_webhook_url, text))
        self.now = now or (lambda: datetime.now(timezone.utc))

    def process_email(self, email: InboundEmail, persist: bool = True) -> PipelineResult:
        start = time.time()
        now = self.now()
        airtable = self.airtable if persist else None
        result = PipelineResult(email=email, classification=Classification.JUNK)

        try:
            # ── 1. Dedupe ─────────────────────────────────────────────
            if airtable and email.message_id and airtable.message_exists(email.message_id):
                result.is_duplicate = True
                result.reply_skip_reason = "duplicate"
                logger.info(f"Duplicate message {email.message_id} from {email.sender_email}, skipping")
                result.processing_time_ms = (time.time() - start) * 1000
                return result

            # ── 2. Junk filter ────────────────────────────────────────
            classification, junk_tokens = self.ai.classify_email(email)
            result.classification = classification
            result.junk_filter_tokens = junk_tokens
            if classification == Classification.JUNK:
                result.reply_skip_reason = "junk"
                logger.info(f"JUNK — stopped pipeline for {email.sender_email}")
                return result

            # ── 3. Extraction + merge ─────────────────────────────────
            extracted, extract_tokens = self.ai.extract_lead(email, today=now.date())
            result.extraction_tokens = extract_tokens

            prior = airtable.find_lead(email.sender_email) if airtable else None
            prior_lead = lead_from_record(prior) if prior else None
            # Effective prior tier: re-tier the stored extraction so rows written under an
            # older gate definition are judged by today's rules. Column is the fallback.
            if prior_lead is not None:
                prior_tier = classify_tier(prior_lead)
            else:
                prior_tier = tier_from_record(prior) if prior else None
            if prior_lead is not None:
                extracted = merge_leads(prior_lead, extracted)
            # Pets imply pet-friendly must be required (model often leaves this null).
            extracted = ensure_pet_friendly_required(extracted)
            result.extracted = extracted

            # ── 4. Tier + upgrade ─────────────────────────────────────
            tier = classify_tier(extracted)
            result.tier = tier
            result.status = status_for_tier(tier)
            result.is_upgrade = prior_tier == Tier.TIER_3 and tier != Tier.TIER_3
            if extracted.has_gate_fields:
                result.match_request = build_match_request(extracted, email, today=now.date())
            logger.info(
                f"LEAD — {tier.value} | upgrade={result.is_upgrade} | match_ready={result.match_ready} | "
                f"confidence={extracted.confidence} | from={email.sender_email}"
            )

            # ── 5. Reply decision + render ────────────────────────────
            prior_fields = prior.fields if prior else {}
            reply_count = int(prior_fields.get("Reply Count") or 0)
            prior_status = prior_fields.get("Status")
            human_status = bool(prior and prior_status and prior_status not in AUTOMATIC_STATUSES)
            is_first_contact = prior is None
            is_tier3_follow_up = prior_tier == Tier.TIER_3
            if human_status and not result.is_upgrade:
                # Human-set status (e.g. Matched): do not auto-ask for missing gates.
                decision = ReplyDecision(False, "follow_up")
            elif is_first_contact or is_tier3_follow_up:
                decision = decide_reply(
                    enabled=self.config.auto_reply_enabled,
                    reply_count=reply_count,
                    last_reply_at=prior_fields.get("Last Reply At"),
                    max_replies=self.config.max_auto_replies,
                    cooldown_minutes=self.config.reply_cooldown_minutes,
                    now=now,
                )
            else:
                # Follow-up from a Tier 1/2 lead: a human answers, not the first-contact template.
                decision = ReplyDecision(False, "follow_up")
                result.status = LeadStatus.NEEDS_REVIEW
            result.reply_subject, result.reply_html = render_reply(tier, result.is_upgrade, email, extracted)
            result.should_reply = decision.should_reply
            result.reply_skip_reason = decision.reason

            # ── 6. Upsert ─────────────────────────────────────────────
            if airtable:
                fields = lead_to_airtable_fields(extracted, tier, result.status, email)
                if human_status and not result.is_upgrade:
                    fields.pop("Status", None)  # keep a human-set status (e.g. Matched)
                if decision.should_reply:
                    fields["Reply Count"] = reply_count + 1
                    fields["Last Reply At"] = iso_utc(now)
                result.airtable_record_id = airtable.upsert_lead(
                    email.sender_email, fields, record_id=prior.record_id if prior else None
                )

        except Exception as e:  # noqa: BLE001 — never crash the webhook
            logger.error(f"Pipeline error for {email.sender_email}: {e}", exc_info=True)
            result.error = str(e)
            result.status = LeadStatus.MANUAL_REVIEW
            result.should_reply = False
            result.reply_skip_reason = "pipeline_error"
            result.match_request = None  # never hand n8n a match body after a failed run
            self.alert(
                f":rotating_light: Plexa pipeline error\n"
                f"From: {email.sender_email}\nSubject: {email.subject}\nError: {e}"
            )
        finally:
            result.processing_time_ms = (time.time() - start) * 1000
            if airtable and not result.is_duplicate:
                self._log_message(airtable, result, now)

        return result

    def _log_message(self, airtable, result: PipelineResult, now: datetime) -> None:
        fields = {
            "Message ID": result.email.message_id,
            "Email": result.email.sender_email.lower(),
            "Subject": result.email.subject or None,
            "Classification": result.classification.value,
            "Tier": result.tier.value if result.tier else None,
            "Status": result.status.value,
            "Should Reply": result.should_reply,
            "Match Ready": result.match_ready,
            "Skip Reason": result.reply_skip_reason,
            "Error": result.error,
            "Tokens": result.total_tokens,
            "Processed At": iso_utc(now),
        }
        fields = {k: v for k, v in fields.items() if v is not None}
        try:
            airtable.log_message(fields)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Could not log message {result.email.message_id}: {e}")

    def process_batch(self, emails: list, persist: bool = True) -> list:
        return [self.process_email(e, persist=persist) for e in emails]
