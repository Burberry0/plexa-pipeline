# Plexa Housing — AI Email Intake Pipeline

**Version 1.0 · Phase 1 Initial Build**

Automated junk/lead email classification, structured data extraction, and tier-based routing for Plexa Housing's rental inquiry inbox.

## Architecture

```
InboundEmail (from n8n webhook)
 │
 ├─ 0. Dedupe on message_id (Airtable Messages)
 ├─ 1. HTML → plaintext strip (ingestion.strip_html)
 ├─ 2. Junk filter [glm-5.3-flash via OpenCode Go] → LEAD / JUNK
 │    └─ JUNK: stop. Logged to Messages. No extraction.
 ├─ 3. AI extraction [glm-5.3-flash, strict JSON schema] → ExtractedLead (26 fields)
 │    └─ Merged over the sender's prior Leads record if one exists
 ├─ 4. Tier classification [validation.py] → Tier 1 / 2 / 3, upgrade detection
 │    └─ Match-ready (Tier 1/2) → match.request [match_request.py], readable
 │       fields for the Property Matching workflow
 ├─ 5. Reply decision [guardrails.py] + rendered reply [email_templates.py]
 └─ 6. Airtable upsert (all tiers) + Messages log
       n8n sends the reply when reply.should_send is true and, after the same
       Slack approval, POSTs match.request to property matching when match.ready is true.
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key (or put it in .env). OPENCODE_API_KEY selects OpenCode Go;
# OPENAI_API_KEY alone falls back to api.openai.com with gpt-4o models.
export OPENCODE_API_KEY=...
export JUNK_FILTER_MODEL=glm-5.3-flash EXTRACTION_MODEL=glm-5.3-flash

# Run the demo (9 sample emails)
python demo.py

# Run with JSON output
python demo.py --json

# Run tests
pip install -r requirements-dev.txt
pytest

# Start the API server
python server.py
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/auth/check` | Secret check for the demo UI |
| POST | `/ingest` | n8n webhook — production email ingestion |
| POST | `/demo/classify` | Demo — process a single email |

`/ingest` and `/demo/classify` require the `X-Webhook-Secret` header.

See also: [`docs/n8n-workflow.md`](docs/n8n-workflow.md), [`docs/airtable-schema.md`](docs/airtable-schema.md), [`docs/runbook.md`](docs/runbook.md).

## Modules

| Module | Responsibility |
|--------|---------------|
| `models.py` | Canonical data shapes: InboundEmail, ExtractedLead, Tier, etc. |
| `config.py` | Frozen dataclass. All secrets from env vars. |
| `ingestion.py` | HTML stripping, adapter pattern, webhook parser. |
| `ai_client.py` | Junk filter + structured extraction over the OpenAI chat protocol (OpenCode Go or OpenAI). Anti-hallucination contract. |
| `validation.py` | Pure Python tier classifier. No I/O. Deterministic. |
| `pipeline.py` | Orchestrator. Calls every module in sequence. |
| `email_templates.py` | Tier-specific HTML auto-reply renderer. |
| `server.py` | Flask API server for webhook mode + demo. |
| `demo.py` | Demo runner with 7 sample emails. |
| `airtable_client.py` | Airtable REST client. Leads upsert, Messages log, field mapping. |
| `guardrails.py` | Reply decision: kill switch, max replies, cooldown. Pure. |
| `alerts.py` | Slack-compatible webhook alert on pipeline errors. |
| `match_request.py` | Pure builder: ExtractedLead → readable match body for the Property Matching workflow. |
| `evals/` | Golden email set and eval runner. |

## Tier Classification

Gate fields are the minimum the Property Matching workflow needs: **ZIP code,
bedrooms, move-in date** (`"ASAP"` counts). A lead with all three is
match-ready and the response carries `match.request`.

| Tier | Conditions | Action |
|------|-----------|--------|
| **Tier 1** | ZIP + Bedrooms + Move-in + ≥1 bonus field (budget, pets, occupants, lease length, bathrooms) | Match-ready; sent to property matching on Slack approval; full confirmation |
| **Tier 2** | ZIP + Bedrooms + Move-in only | Match-ready; sent to property matching on Slack approval; soft follow-up |
| **Tier 3** | Any gate field missing | Hold — ask for exactly the missing ones |

A neighborhood or city without a ZIP code does not satisfy the gate; the
reply asks for one.

## AI provider and cost

Production runs on an OpenCode Go subscription (flat $10/month, Go Plus $40)
through its OpenAI-compatible endpoint. Usage is capped per model in monthly
dollar terms with 5-hour and weekly windows; check the OpenCode console if
`Manual Review` rows show 429s. Only models served on OpenCode's
`/chat/completions` endpoint work (GLM, Kimi, DeepSeek, MiMo, LongCat).

Golden-set results on 2026-10-13 (`python -m evals.run_eval`, 7-case set; the
10-case set with zip and match-readiness scoring is re-run below under
"Extraction v2.0.0"):

| Model (both roles) | Classification | Tier | Notes |
|---|---|---|---|
| `glm-5.3-flash` | 7/7, 7/7 | 7/7, 7/7 | **Production.** Reasoning model: needs the default caps (`JUNK_FILTER_MAX_TOKENS=512`, `EXTRACTION_MAX_TOKENS=4096`) or output comes back empty. Leads take 3–20 s for both calls. Largest documented Go cap ($60/mo). |
| `mimo-v2.6-flash` | 7/7 | 7/7 on one run | Correct when it answers, but extraction exceeded the 20 s timeout in 2 of 3 runs. Fallback only. |
| `deepseek-v4-pro`, `deepseek-v4.1-flash` | — | — | Rejected until "Global regions" is enabled in the OpenCode workspace privacy settings. |
| `kimi-k2.7-code` | — | — | Rejects `temperature` other than 1; not supported by this client. |
| `glm-5.3` | — | — | Returned malformed or empty JSON. |

### Extraction v2.0.0 (10-case set, 2026-10-14)

Two runs of `python -m evals.run_eval --junk-model glm-5.3-flash --extraction-model glm-5.3-flash`
during an unstable OpenCode window:

| Metric | Run A | Run B |
|---|---|---|
| Cases answered by the provider | 8/10 | 6/10 |
| Classification correct (of answered) | 8/8 | 6/6 |
| Tier, zip, match-ready correct (of answered) | 8/8 | 6/6 |
| Provider timeouts / connection errors | 2 | 4 |

Every case that received a response was scored correctly on classification, tier,
zip and match-readiness; across the two runs each of the 10 cases succeeded at
least once. Re-run on a quiet provider window before go-live to get a clean
10/10 row. Note the local `.env` must set both model names: with only
`OPENCODE_API_KEY` the defaults are OpenAI names and OpenCode returns
`Model is unavailable`.

Without `OPENCODE_API_KEY` the service falls back to OpenAI (`gpt-4o-mini` / `gpt-4o`, roughly $0.01 per lead).

## Prompt evals

`evals/golden_emails.jsonl` holds labeled real emails. Add one JSON object per
line with `id`, `sender_name`, `sender_email`, `subject`, `body`,
`expected_classification` (`LEAD`/`JUNK`), `expected_tier` (`Tier 1`/`Tier 2`/
`Tier 3`/`null`), `expected_location` (substring, or `null`),
`expected_bedrooms` (integer or `null`), `expected_zip_code` (5-digit string
or `null`) and `expected_match_ready` (bool, true only for Tier 1/2). Strip
real names and phone numbers.

```bash
python -m evals.run_eval --min-tier-accuracy 0.9
```

Run this after any prompt change. Target: 30–50 real emails before go-live.

---
Built by Zautom · Technology & Automation Consulting
