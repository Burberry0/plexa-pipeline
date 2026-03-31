# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Set required env var
export ANTHROPIC_API_KEY=sk-ant-...

# Run demo (7 sample emails, human-readable output)
python demo.py

# Run demo with JSON output
python demo.py --json

# Start Flask API server (port 5000)
python server.py
```

No test suite exists — testing is done via `demo.py` or by POSTing to the running server.

## Architecture

This is a **6-step sequential email classification pipeline** for Plexa Housing. It processes inbound rental inquiry emails, filters junk, extracts structured lead data, and routes leads into a 3-tier system.

**Pipeline flow** (`pipeline.py` orchestrates all steps):

```
InboundEmail → strip_html → junk filter (Haiku) → extract fields (Opus) → classify tier → Airtable upsert → auto-reply
```

1. **Ingestion** (`ingestion.py`): HTML → plaintext. Two adapters: `DirectInputAdapter` (demo/API) and `parse_webhook_payload()` (n8n webhook).
2. **Junk filter** (`ai_client.py`): Claude Haiku binary classification — returns `"LEAD"` or `"JUNK"`. JUNK emails exit the pipeline immediately, no extraction performed.
3. **Extraction** (`ai_client.py`): Claude Opus structured JSON extraction — 12 fields including `location`, `bedrooms`, `budget_min/max`, `move_in_date`, `pets`, `occupants`, `duration_months`. Strict anti-hallucination contract: **null over guess**.
4. **Tier classification** (`validation.py`): Pure Python, no AI. Gate fields are `location` + `bedrooms`. Tier 1 = gates + ≥1 bonus field; Tier 2 = gates only; Tier 3 = missing a gate field.
5. **Airtable upsert** (`pipeline.py`): Currently stubbed — logs "Would upsert" for Tier 1/2 leads.
6. **Auto-reply** (`email_templates.py`): Currently stubbed — renders tier-specific HTML email. Guardrails: max 2 replies per sender, 5-min cooldown.

## Key Design Decisions

- **Two-model strategy**: Haiku (~$0.0001/email) for junk triage, Opus (~$0.015/email) for extraction. Haiku tiebreaker is "when in doubt, choose LEAD" — false negatives (missing a real lead) are worse than false positives.
- **`PipelineResult`** (`models.py`) is the canonical output object — carries classification, extracted lead, tier, status, token counts, and optional error. Errors set `status=MANUAL_REVIEW` and don't raise.
- **Prompt registry**: All prompts live in the `PROMPTS` dict in `ai_client.py`, not inline, for version control.
- **`validate_extraction()`** in `validation.py` is a pure function that checks the Opus JSON output against the 12-field schema before tier classification runs.

## Configuration

All secrets and tunables come from environment variables. See `.env.example` for the full list. `PipelineConfig` (`config.py`) is a frozen dataclass built via `PipelineConfig.from_env()`.

Key overrideable env vars: `JUNK_FILTER_MODEL`, `EXTRACTION_MODEL`, `MAX_AUTO_REPLIES`, `REPLY_COOLDOWN_MINUTES`, `PORT`.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| POST | `/ingest` | n8n webhook (production) |
| POST | `/demo/classify` | Single-email test |

All responses are `PipelineResult.to_dict()` JSON.
