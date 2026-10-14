# Plexa Pipeline — Production Readiness Spec

**Date:** 2026-10-05
**Status:** Draft, derived from the 2026-10-05 code assessment

## Goal

Take the Phase 1 prototype (4 of 6 pipeline steps implemented, no tests, no
state, no auth) to a service that can run against Plexa Housing's live inbox:
classify, extract, tier, persist to Airtable, decide on and render auto-replies
with guardrails, handle Tier 3 follow-up replies, and be observable enough to
run a shadow period before replies go live.

## Architecture decisions

1. **The Python service stays stateless.** It holds no database and no files.
   All state lives in Airtable. The service is a pure decision engine: email in,
   `PipelineResult` out.
2. **n8n owns Gmail I/O.** n8n polls Gmail, POSTs each message to `/ingest`,
   and sends the reply the service rendered when `should_reply` is true. The
   Python service never talks to Gmail. The Gmail OAuth file approach is removed.
3. **Airtable owns state.** Two tables:
   - `Leads`, one record per sender email. Holds the latest merged extraction,
     tier, status, `Reply Count`, `Last Reply At`, and an `Extraction JSON`
     field for exact round-trip.
   - `Messages`, one record per processed message (including JUNK and errors).
     Primary field `Message ID`. Used for idempotency and audit.
4. **All tiers are upserted**, not just Tier 1/2 as the README said. The Tier 3
   upgrade flow needs the prior record.
5. **Upgrade flow:** when a sender with an existing Leads record writes again,
   the new extraction is merged over the prior one (new non-null wins), re-tiered,
   and if the prior tier was Tier 3 and the new tier is not, `is_upgrade` is true
   and the upgrade template is used.
6. **Guardrails are enforced in Python** from the Leads record: max replies per
   sender, cooldown, and a global `AUTO_REPLY_ENABLED` kill switch (default
   false) for the shadow period. The service increments `Reply Count` when it
   decides to reply; n8n is responsible for actually sending.
7. **Security:** `/ingest` and `/demo/classify` require an `X-Webhook-Secret`
   header matching `WEBHOOK_SECRET`. The service fails closed if the secret is
   unset. CORS is restricted to `ALLOWED_ORIGIN`. The demo UI prompts for the
   secret instead of shipping hardcoded credentials.
8. **AI hardening:** OpenAI structured outputs (strict JSON schema) for
   extraction, explicit timeout and retries, type coercion of every numeric
   field, today's date passed into the prompt, and the junk filter only returns
   JUNK on an explicit JUNK response (LEAD bias preserved).
9. **Rendered replies are HTML-escaped.** Every value from the sender or the
   model is escaped before interpolation.
10. **Observability:** every message is logged to the Messages table; any
    `MANUAL_REVIEW` outcome POSTs to `ALERT_WEBHOOK_URL` (Slack-compatible)
    when configured.
11. **Evals:** a JSONL golden set and a runner script that reports
    classification, tier, and gate-field accuracy. Seeded with the 7 demo emails;
    Ryan supplies real ones.

## Out of scope

- Property matching against inventory.
- A Gmail adapter inside Python (polling mode). n8n replaces it.
- Multi-tenant or multi-inbox support.
- A real user login for the demo UI beyond the shared secret.

## Non-functional

- Python 3.11+. Flat module layout as today (`from models import ...`).
- `pytest` for tests, no network in unit tests.
- Demo (`python demo.py`, `/demo/classify`) must keep working with only
  `OPENAI_API_KEY` and `WEBHOOK_SECRET` set, no Airtable.
- Prompts stay in the `PROMPTS` registry in `ai_client.py` with versions.
