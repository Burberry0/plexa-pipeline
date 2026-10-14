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
 ├─ 3. AI extraction [glm-5.3-flash, strict JSON schema] → ExtractedLead (12 fields)
 │    └─ Merged over the sender's prior Leads record if one exists
 ├─ 4. Tier classification [validation.py] → Tier 1 / 2 / 3, upgrade detection
 ├─ 5. Reply decision [guardrails.py] + rendered reply [email_templates.py]
 └─ 6. Airtable upsert (all tiers) + Messages log
       n8n sends the reply when reply.should_send is true.
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key (or put it in .env). OPENCODE_API_KEY selects OpenCode Go;
# OPENAI_API_KEY alone falls back to api.openai.com with gpt-4o models.
export OPENCODE_API_KEY=...
export JUNK_FILTER_MODEL=glm-5.3-flash EXTRACTION_MODEL=glm-5.3-flash

# Run the demo (7 sample emails)
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
| `evals/` | Golden email set and eval runner. |

## Tier Classification

| Tier | Conditions | Action |
|------|-----------|--------|
| **Tier 1** | Location + Bedrooms + ≥1 bonus field | Auto-match immediately |
| **Tier 2** | Location + Bedrooms only | Match + soft follow-up |
| **Tier 3** | Missing location or bedrooms | Hold — ask for missing info |

## AI provider and cost

Production runs on an OpenCode Go subscription (flat $10/month, Go Plus $40)
through its OpenAI-compatible endpoint. Usage is capped per model in monthly
dollar terms with 5-hour and weekly windows; check the OpenCode console if
`Manual Review` rows show 429s. Only models served on OpenCode's
`/chat/completions` endpoint work (GLM, Kimi, DeepSeek, MiMo, LongCat).

Golden-set results on 2026-10-13 (`python -m evals.run_eval`):

| Model (both roles) | Classification | Tier | Notes |
|---|---|---|---|
| `glm-5.3-flash` | 7/7, 7/7 | 7/7, 7/7 | **Production.** Reasoning model: needs the default caps (`JUNK_FILTER_MAX_TOKENS=512`, `EXTRACTION_MAX_TOKENS=4096`) or output comes back empty. Leads take 3–20 s for both calls. Largest documented Go cap ($60/mo). |
| `mimo-v2.6-flash` | 7/7 | 7/7 on one run | Correct when it answers, but extraction exceeded the 20 s timeout in 2 of 3 runs. Fallback only. |
| `deepseek-v4-pro`, `deepseek-v4.1-flash` | — | — | Rejected until "Global regions" is enabled in the OpenCode workspace privacy settings. |
| `kimi-k2.7-code` | — | — | Rejects `temperature` other than 1; not supported by this client. |
| `glm-5.3` | — | — | Returned malformed or empty JSON. |

Without `OPENCODE_API_KEY` the service falls back to OpenAI (`gpt-4o-mini` / `gpt-4o`, roughly $0.01 per lead).

## Prompt evals

`evals/golden_emails.jsonl` holds labeled real emails. Add one JSON object per
line with `id`, `sender_name`, `sender_email`, `subject`, `body`,
`expected_classification` (`LEAD`/`JUNK`), `expected_tier` (`Tier 1`/`Tier 2`/
`Tier 3`/`null`), `expected_location` (substring, or `null`) and
`expected_bedrooms` (integer or `null`). Strip real names and phone numbers.

```bash
python -m evals.run_eval --min-tier-accuracy 0.9
```

Run this after any prompt change. Target: 30–50 real emails before go-live.

---
Built by Zautom · Technology & Automation Consulting
