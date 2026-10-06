# Plexa Housing — AI Email Intake Pipeline

**Version 1.0 · Phase 1 Initial Build**

Automated junk/lead email classification, structured data extraction, and tier-based routing for Plexa Housing's rental inquiry inbox.

## Architecture

```
InboundEmail
 │
 ├─ 1. HTML → plaintext strip (ingestion.strip_html)
 │
 ├─ 2. Junk filter [claude-haiku] → LEAD / JUNK
 │    └─ JUNK: stop. No extraction. No Airtable write.
 │
 ├─ 3. AI extraction [claude-opus] → ExtractedLead (12 fields)
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
export ANTHROPIC_API_KEY=sk-ant-...

# Run the demo (7 sample emails)
python demo.py

# Run with JSON output
python demo.py --json

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
| Junk Filter (Haiku) | ~$0.0001 | $0.10 |
| Extraction (Opus) | ~$0.015 | $4.50 |
| **Total** | | **~$4.60/day (~$138/mo)** |

---
Built by Zautom · Technology & Automation Consulting
