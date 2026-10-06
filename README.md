# Plexa Housing — AI Email Intake Pipeline

**Version 1.0 · Phase 1 Initial Build**

Automated junk/lead email classification, structured data extraction, and tier-based routing for Plexa Housing's rental inquiry inbox.

## Architecture

```
InboundEmail
 │
 ├─ 1. HTML → plaintext strip (ingestion.strip_html)
 │
 ├─ 2. Junk filter [gpt-4o-mini] → LEAD / JUNK
 │    └─ JUNK: stop. No extraction. No Airtable write.
 │
 ├─ 3. AI extraction [gpt-4o] → ExtractedLead (12 fields)
 │
 ├─ 4. Tier classification [validation.py] → Tier 1 / 2 / 3
 │
 ├─ 5. Airtable upsert (Tier 1/2 only)
 │
 └─ 6. Auto-reply (with guardrails: max 2 replies, 5 min cooldown)
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key
export OPENAI_API_KEY=sk-...

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
| POST | `/ingest` | n8n webhook — production email ingestion |
| POST | `/demo/classify` | Demo — process a single email |

## Modules

| Module | Responsibility |
|--------|---------------|
| `models.py` | Canonical data shapes: InboundEmail, ExtractedLead, Tier, etc. |
| `config.py` | Frozen dataclass. All secrets from env vars. |
| `ingestion.py` | HTML stripping, adapter pattern, webhook parser. |
| `ai_client.py` | Haiku junk filter + Opus extraction. Anti-hallucination contract. |
| `validation.py` | Pure Python tier classifier. No I/O. Deterministic. |
| `pipeline.py` | Orchestrator. Calls every module in sequence. |
| `email_templates.py` | Tier-specific HTML auto-reply renderer. |
| `server.py` | Flask API server for webhook mode + demo. |
| `demo.py` | Demo runner with 7 sample emails. |

## Tier Classification

| Tier | Conditions | Action |
|------|-----------|--------|
| **Tier 1** | Location + Bedrooms + ≥1 bonus field | Auto-match immediately |
| **Tier 2** | Location + Bedrooms only | Match + soft follow-up |
| **Tier 3** | Missing location or bedrooms | Hold — ask for missing info |

## Cost Projection

| Component | Cost/Email | Daily (1000 emails, 30% leads) |
|-----------|-----------|-------------------------------|
| Junk Filter (gpt-4o-mini) | ~$0.0002 | $0.20 |
| Extraction (gpt-4o) | ~$0.01 | $3.00 |
| **Total** | | **~$3.20/day (~$96/mo)** |

---
Built by Zautom · Technology & Automation Consulting

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
