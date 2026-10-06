# Plexa Pipeline — Deployment and Monitoring Design

**Date:** 2026-10-06
**Status:** Approved in conversation, pending written review
**Builds on:** `2026-10-05-production-readiness-spec.md` (architecture decisions 1–3 are unchanged)

## Goal

Get the pipeline running continuously against the live Plexa inbox with a
monitoring structure that reports the failures the current setup misses:
n8n stops polling, Vercel is down, Airtable rejects writes, or the OpenAI key
dies. Today the system only alerts when a single email hits Manual Review. It
is silent when nothing is being processed at all.

The pipeline code does not change. This is a wiring and operations design.

## Decisions

1. **n8n stays as the intake and send layer.** Gmail Trigger polls every
   minute, POSTs to `/ingest`, branches on the result, sends the reply or
   applies the Needs Attention label. Documented in `docs/n8n-workflow.md`.
2. **Monitoring reads from Airtable Messages.** Every processed email already
   has a row with `Processed At`, `Classification`, `Tier`, `Status`, and
   `Error`. No new storage is introduced.
3. **The watchdog runs in n8n, with an external dead-man's switch.** A
   watchdog on the same host it watches cannot report that host being down.
   healthchecks.io covers that one case.
4. **The status view is an Airtable Interface.** Ryan already needs Airtable
   for leads, so there is no new login or hosted page.
5. **One Slack channel receives everything:** real-time Manual Review alerts
   from the service (`ALERT_WEBHOOK_URL`), monitor alerts, the daily digest,
   and healthchecks.io alerts.
6. **No Python changes.** Vercel cron was rejected: Hobby plan runs daily only,
   and it would put the watchdog on the host it watches. A `/status` endpoint
   was rejected as duplicate code over data Airtable already exposes.

## Components

### Deployment order

1. Create the Airtable base from `docs/airtable-schema.md`.
2. Deploy the service to Vercel per `docs/runbook.md` with
   `AUTO_REPLY_ENABLED=false`. Verify `/health` and the runbook curl.
3. Build the six-node intake workflow in n8n from `docs/n8n-workflow.md`.
   Activate it.
4. Build the monitor workflow, the dead-man's switch, and the Interface
   (below).
5. Run the verification checklist (below).
6. Shadow period and go-live gate as in the runbook. Unchanged.

### Monitor workflow ("Plexa Monitor", n8n)

Schedule Trigger every 30 minutes. Each run performs three checks and posts to
Slack only when a check fails. Thresholds are node parameters, tuned after
real volume is observed.

| Check | Source | Alert condition | Default |
|---|---|---|---|
| Freshness | Airtable Messages, newest `Processed At` | Older than N hours, only inside the business window | 6 hours, Mon–Fri 08:00–20:00 local |
| Service health | GET `https://<vercel-domain>/health` | Non-200, or body `airtable` is false | — |
| Intake active | n8n REST API, `GET /workflows/<intake-id>` | `active` is false | — |

Outside the business window the freshness check is skipped so that a quiet
weekend does not page anyone. Health and intake-active checks run around the
clock.

**Daily digest.** A separate branch gated on time == 08:00 local, Mon–Fri.
Queries Messages where `Processed At` is within the previous calendar day and
posts one Slack message with:

- counts by `Classification` (LEAD / JUNK)
- counts by `Tier` for LEAD rows
- counts by `Status`
- one line per `Status = Manual Review` row: `Email`, `Subject`, first 120
  chars of `Error`

Manual Review alerts continue to fire in real time from the service. The
digest is a summary, not the only signal.

**Final node.** On every successful run, GET the healthchecks.io ping URL. If
any earlier node errors, the workflow's Error Workflow posts to Slack and the
ping is not sent.

### Dead-man's switch (healthchecks.io)

One check, period 30 minutes, grace 15 minutes, Slack integration pointing at
the same channel. If n8n is down, the monitor workflow is deactivated, or the
monitor itself errors, pings stop and healthchecks.io alerts within 45 minutes
of the last successful run.

### Status view (Airtable Interface)

Interface named "Plexa Pipeline" on the existing base, four blocks:

1. **Last processed** — number element, max of `Processed At` on Messages.
2. **Last 24 hours by tier** — chart or grid, Messages filtered to
   `Processed At` within 1 day, grouped by `Tier`.
3. **Manual Review, last 7 days** — grid on Messages filtered to
   `Status = Manual Review` and `Processed At` within 7 days, showing `Email`,
   `Subject`, `Error`, `Processed At`.
4. **Leads needing a human** — grid on Leads filtered to
   `Status = Needs Review`, showing `Email`, `Name`, `Tier`, `Last Subject`,
   `Last Contact`.

Fallback if Interfaces are unavailable on the plan: three saved grid views on
Messages with filters 2–3 above plus one on Leads with filter 4.

## Verification checklist

Done means all four pass.

1. Deactivate the intake workflow. A Slack alert from Plexa Monitor arrives
   within 30 minutes. Reactivate.
2. Deactivate Plexa Monitor. healthchecks.io alerts Slack within 45 minutes.
   Reactivate.
3. POST the runbook test email with a deliberately broken Airtable field to
   force Manual Review. Confirm the real-time alert, the row in the Interface's
   Manual Review block, and its line in the next morning's digest. Delete the
   test rows.
4. Temporarily set the freshness threshold to 1 minute during the business
   window. Confirm a freshness alert fires on the next run. Restore the
   threshold.

## Repo changes

- New: `docs/monitoring.md` — monitor workflow node-by-node (same style as
  `docs/n8n-workflow.md`), healthchecks.io setup, Interface layout, the
  verification checklist above.
- Edit: `docs/runbook.md` — one line under "Deploy to Vercel" pointing to
  `docs/monitoring.md` as the next step after the intake workflow is active.
- No changes to Python, tests, or `vercel.json`.

## Out of scope

- Gmail push notifications (Pub/Sub). Polling at 1 minute is sufficient.
- A hosted status page or `/status` endpoint.
- Alert routing beyond one Slack channel.
- Metrics retention beyond what Airtable holds.
