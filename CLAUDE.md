# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Branch state

`main` holds the production service (the `worktree-production-readiness` work was merged in PR #1 on 2026-10-13). Branch off `main` for new work.

## Commands

```bash
pip install -r requirements.txt -r requirements-dev.txt

# Unit tests: no network, AI and Airtable are injected fakes (tests/fakes.py)
pytest
pytest tests/test_pipeline.py -k follow_up        # one test by name

# Real model calls, nothing persisted. Keys are read from the environment or the nearest .env.
# OPENCODE_API_KEY selects OpenCode Go; with only OPENAI_API_KEY the service uses api.openai.com.
python demo.py            # 7 sample emails, human-readable
python demo.py --json
python -m evals.run_eval --min-tier-accuracy 0.9   # golden set in evals/golden_emails.jsonl; run after any prompt or model change
python -m evals.run_eval --junk-model glm-5.3-flash --extraction-model mimo-v2.6-flash   # compare models

# Local server (endpoints return 503 without WEBHOOK_SECRET)
WEBHOOK_SECRET=dev python server.py               # FLASK_DEBUG=1 for the debugger

# Deploy (project is linked; env vars live on Vercel, see docs/runbook.md)
vercel --prod && curl https://<domain>/health
```

## What this service is

A stateless decision engine for Plexa Housing's rental-inquiry inbox: one email in, one `PipelineResult` out. It never sends email, never calls other workflows, and never writes to disk.

- **n8n owns Gmail and the matching hand-off.** It polls the inbox, POSTs each message to `/ingest`, posts the proposed reply to Slack for a human to approve, sends it, and, when `match.ready` is true, POSTs `match.request` to the separate Property Matching workflow. See `docs/n8n-workflow.md` and `docs/monitoring.md`.
- **Airtable owns state.** Two tables, documented field-by-field in `docs/airtable-schema.md`. `Leads` is one row per sender (merged on `Email` via `performUpsert`, so concurrent requests cannot create duplicates). `Messages` is one row per processed message, keyed on `Message ID`, and is the dedupe and audit log. Field names in `airtable_client.py` must match that doc exactly; a mismatch surfaces as a 422 and a `Manual Review` row.

## Pipeline flow (`pipeline.py`)

```
dedupe on message_id → junk filter → extraction → merge over prior Leads row
→ tier + upgrade detection → match_request (if match-ready) → reply decision + render
→ Partners lookup (email, then domain) → Leads upsert + Messages log
```
Partner enrichment stamps `Known Partner` / `Partner Tier` / `Vendor` on Leads and
emits `partner: {known, inventory_tier, vendor, matched_by}` on every `/ingest`
response. Unknown senders still process; Inactive/DNC Partners rows are ignored.
Lookup failures are logged and treated as unknown (ingest continues).

Rules that span several files and are easy to break:

- **AI provider** (`config.py`, `ai_client.py`): one OpenAI SDK client, built by `build_openai_client()`, pointed at OpenCode Go when `OPENCODE_API_KEY` is set and at OpenAI otherwise. Only OpenCode models served on `/chat/completions` work (MiMo, GLM, DeepSeek, Kimi, LongCat); Claude, Qwen, GPT Luna and Grok use other endpoints. Every call sends `x-opencode-session` (the message ID) and a custom User-Agent, which OpenCode's usage policy asks for. Production models are `glm-5.3-flash` for both roles; see the README table for what else was tested and why it failed.
- **Junk filter** (`ai_client.py`): only a response starting with `JUNK` is junk; anything else, including empty, is `LEAD`. False negatives lose customers.
- **Extraction** (`ai_client.py`): strict `json_schema` output against `EXTRACTION_JSON_SCHEMA` by default; `EXTRACTION_RESPONSE_FORMAT=json_object|none` for providers that lack it. `coerce_extraction()` then forces types. Reasoning models count thinking against `max_tokens`, so the defaults are 512 for the one-word junk filter and 4096 for extraction; too low and the model returns empty content (which the junk filter treats as LEAD, with a warning). Contract is null over guess. Today's date is passed in the user message so relative dates resolve. Prompts live in the `PROMPTS` registry with version strings; bump the version and `last_updated` on any change (a test pins the current versions).
- **Merge and upgrade** (`validation.py`, `pipeline.py`): a returning sender's new extraction is merged over the stored `Extraction JSON` (new non-null wins, `pets=[]` and `amenities=[]` are values; `MERGEABLE_FIELDS` is derived from the dataclass), then re-tiered. The *prior* tier is also recomputed from the stored extraction under today's gate (the `Tier` column is only a fallback), so rows written under an older gate are judged by current rules. `is_upgrade` is true only when that effective prior tier was Tier 3 and the new one is not.
- **Tiers and match-readiness** (`models.py`, `validation.py`): gate fields are `zip_code`, `bedrooms`, `move_in_date` (`"ASAP"` counts). Tier 1 = all gates plus one bonus field (`budget_min/max`, `pets`, `occupants`, `duration_months`, `bathrooms`), Tier 2 = gates only, Tier 3 = a gate missing. Match-ready ⇔ gates present ⇔ Tier 1/2; there is no second notion. `location` free text is stored but does not gate (a bare zip is copied into it too, which is why it is not a bonus field). Tier 3 asks exactly the missing gate questions via `gate_questions()`; never keyword-match question text.
- **Match request** (`match_request.py`): a pure builder from `ExtractedLead` + `InboundEmail` to a readable match body (`zip_code`, `bedrooms`, `email`, … — not JotForm `q*` keys). The Property Matching workflow does geocoding, Request_ID and Priority. `"ASAP"` resolves to the pipeline's injected `now` as `YYYY-MM-DD`. Extra pets go into `special_requests`. Only built when match-ready; `to_dict()` always emits `match: {ready, missing_fields, request}`.
- **Reply decision** (`guardrails.py`, applied in `pipeline.py`): the service only proposes a reply on first contact or on a follow-up from a Tier 3 sender. Any other follow-up gets `skip_reason: follow_up` and status `Needs Review` for a human. Then the kill switch (`AUTO_REPLY_ENABLED`), max replies, and cooldown apply, read from the Leads row. The service increments `Reply Count` and `Last Reply At` when it decides to reply even though n8n does the sending.
- **Human-set status wins.** A `Status` not in `AUTOMATIC_STATUSES` (for example `Matched`) is not overwritten by a follow-up unless it is an upgrade.
- **Errors never raise.** Any exception sets `status: Manual Review`, `skip_reason: pipeline_error`, posts to `ALERT_WEBHOOK_URL`, and the Messages row is still written in `finally`. Duplicates and JUNK return default `classification`/`status` values, so n8n must branch on `reply.should_send` and `match.ready`, never on `classification`.

## Testing seams

`Pipeline(config, ai=, airtable=, alerter=, now=)` and `AIClient(config, client=)` accept injected doubles; `tests/fakes.py` has `FakeAI`, `FakeAirtable`, `FakeAlerter`. `process_email(email, persist=False)` runs the full chain without Airtable, which is what `/demo/classify`, `demo.py`, and the eval runner use. `PipelineConfig` is a frozen dataclass; build it directly in tests rather than through env vars.

## Server and deployment

`server.py` is an app factory (`create_app(config, pipeline)`); the module-level `app` is what `api/index.py` exports as `handler` for Vercel. `/ingest`, `/demo/classify`, and `/auth/check` require `X-Webhook-Secret` compared with `hmac.compare_digest`, and return 503 when `WEBHOOK_SECRET` is unset. CORS is only enabled when `ALLOWED_ORIGIN` is set.

`vercel.json` routes each API path explicitly and sends everything else to the static `ui.html`. A new endpoint must be added to `vercel.json` or it will serve the UI instead. The matching hand-off needed no new endpoint and no new env var: the matching webhook URL lives in n8n only. Function `maxDuration` is 60 s; the AI timeout and retry settings in `config.py` are sized so two calls fit inside it, and n8n's HTTP timeout must stay above it.

## Configuration

Everything comes from env vars through `PipelineConfig.from_env()`, which also loads the nearest `.env` (real env vars win; pass `load_env_file=False` in tests). `.env.example` is the full list. Secret fields are excluded from the dataclass repr, so a logged config never prints keys. `AUTO_REPLY_ENABLED` defaults to false. In production it is true and the Slack approval step in n8n is the gate; setting it false is the hard kill switch (classification and Airtable writes continue). `.env*` and `.vercel/` are gitignored.

## Docs

- `docs/runbook.md`: deploy, smoke test, shadow run, go-live gate, kill switch, failure table.
- `docs/n8n-workflow.md`, `docs/monitoring.md`: node-by-node n8n specs; node names are referenced by other nodes, so renaming one breaks the workflow.
- `n8n/intake-logging/`: generates the root `Plexa Intake.json` from `workflow/Plexa-Intake.before.json`, adding the Slack-logger stage reports (`node --test n8n/intake-logging/logging.test.js`). The logger itself lives in `RyanPlexa/n8n-logger/`.
- `docs/superpowers/specs/` and `docs/superpowers/plans/`: the design decisions and the task-by-task plans this branch implemented.
