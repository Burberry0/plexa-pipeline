# Plexa Intake — Slack logging (shared logger adopter)

The n8n intake workflow (`Plexa Intake.json` at the repo root) reports to the
shared **Plexa — Slack Logger** (`RyanPlexa/n8n-logger/`) instead of posting
ad-hoc text to a Slack incoming webhook. Same pattern as the Landlord
Confirmation Send and Property Matching workflows: one builder function
(`logging-nodes.js`) applied to a live export, Code bodies in `logging/`,
offline tests against the n8n stub.

> `Plexa Intake.json` is **GENERATED** from `workflow/Plexa-Intake.before.json`
> by `add-logging-to-export.js`. The five `Log: …` Code nodes inside it are the
> files under `logging/` (each prefixed with `_prelude.js`). Edit a body here,
> rebuild, re-import. `logging.test.js` fails on drift.

## What gets logged

| Touch point | Node | Severity | When |
|---|---|---|---|
| `POST /ingest` error output | `Log: Ingest Failed` | 🔴 Red | The service call failed after 2 tries (401/403 secret, 503 unset secret, 5xx, 90 s timeout). The email is unlabelled and will not be re-polled. |
| `POST /ingest` success output | `Log: Intake Result` | 🟢 🟡 🔴 | **Every** processed email, the moment the service answers. Red = `Manual Review`. Yellow = a lead the service chose not to answer (`follow_up`, `cooldown_active`, `max_replies_reached`, `auto_reply_disabled`). Green = reply awaiting approval, JUNK, duplicate. |
| `Approved?` FALSE | `Log: Reply Declined` | 🟡 Yellow | Declined in Slack, or the 24 h approval wait ran out. Nothing sent. |
| `Gmail Reply` error output | `Log: Reply Failed` | 🔴 Red | A human approved the reply and Gmail refused to send it. No label, no match request. |
| `HTTP Request` (match POST) both outputs | `Log: Hand-off` | 🟢 / 🔴 | End of an approved lead: reply sent and match request accepted (or nothing to match) / the POST to Property Matching failed. |
| anything unhandled | *Settings → Error Workflow* | 🔴 Red | The logger's Error Trigger. |

Retired by the builder: `Build log` → `Slack log` and `Slack declined` (the
incoming-webhook posts). After the rebuild no webhook URL remains in the
workflow; the only other Slack traffic is the interactive `Approve reply?`
bot message.

The Code nodes run **once for each item**: one Gmail poll can deliver several
emails, and each gets its own message. They read `$json` plus the paired
`Build payload` / `POST /ingest` items, falling back to `.first()` when n8n
cannot pair.

Every Logger node is fire-and-forget (`waitForSubWorkflow: false`,
`onError: continueRegularOutput`). Three business nodes gain
`onError: continueErrorOutput` (`POST /ingest`, `Gmail Reply`, `HTTP Request`)
so an expected failure leaves on the error output into its Red message and the
execution stays green in n8n. Slack is the record.

## Build, test, import

```bash
node n8n/intake-logging/add-logging-to-export.js n8n/intake-logging/workflow/Plexa-Intake.before.json "Plexa Intake.json"
node --test n8n/intake-logging/logging.test.js
```

With the logger's workflow id (from its URL in n8n, `/workflow/<id>`):

```bash
N8N_LOGGER_WORKFLOW_ID=<id> node n8n/intake-logging/add-logging-to-export.js n8n/intake-logging/workflow/Plexa-Intake.before.json "Plexa Intake.json"
```

That wires all five `Logger (…)` nodes and sets *Settings → Error Workflow* to
the logger. Without it the nodes carry `REPLACE_ME` and the export's existing
Error Workflow setting is left as it is: open each `Logger (…)` node after
import and pick *Plexa — Slack Logger* from the list.

Import: open the existing *Plexa Intake* workflow in n8n → `…` → *Import from
File*. The builder keeps the workflow id, `versionId`, `meta.instanceId`, every
node id, bound credentials, pinned data and positions, so the import updates
the workflow in place.

Refreshing from a new live export: download it, copy it over
`workflow/Plexa-Intake.before.json`, rebuild. Re-running on an already-built
file is safe; the additions are replaced by name.

## Fixtures

`fixtures.json` holds real `/ingest` responses produced by the Python pipeline
with `tests/fakes.py` (Tier 1, Tier 3, JUNK, duplicate, Manual Review,
follow-up, kill switch). Regenerate it when `PipelineResult.to_dict()` changes.

## Test plan after import

Each case is one Slack message from the logger.

| # | Case | How | Expect |
|---|---|---|---|
| 1 | Green lead | Send a test inquiry with zip, bedrooms, move-in. | `🟢 Green · Plexa Intake · intake`, *Tier 1 lead from … reply awaiting approval in Slack; match ready.* Then the `Approve reply?` message. |
| 2 | Approve | Click *Approve & send*. | Reply lands in-thread; `🟢 Green · Plexa Intake · match` *Reply sent …; match request handed to Property Matching (zip …)*. |
| 3 | Decline | Send another, click *Decline*. | `🟡 Yellow · Plexa Intake · approval` *… declined in Slack. Nothing sent; email labelled Processed.* |
| 4 | JUNK | Forward a newsletter. | `🟢 Green … intake` *JUNK filtered — …* |
| 5 | Ingest down | Change the `Plexa Webhook Secret` credential value, send one, restore. | `🔴 Red … ingest` with `<!here>`, *POST /ingest failed … HTTP 401*. Execution green in n8n. |
| 6 | Manual Review | Rename an Airtable field for one run, send one, restore. | `🔴 Red … intake` *Manual Review — … Labelled Needs Attention*. |
