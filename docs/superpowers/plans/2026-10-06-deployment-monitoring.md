# Deployment and Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the Plexa pipeline running continuously against the live inbox with a monitor that reports silent failures, a dead-man's switch, and an Airtable status view.

**Architecture:** n8n polls Gmail and POSTs to the Flask service on Vercel; Airtable holds all state. A second n8n workflow ("Plexa Monitor") reads Airtable Messages and `/health` every 30 minutes, posts failures and an 8am digest to one Slack channel, and pings healthchecks.io on every clean run. An Airtable Interface is the human status view. No Python changes.

**Tech Stack:** Vercel (Python runtime, existing `vercel.json`), n8n (Gmail, Airtable, HTTP Request, Code, IF, Schedule nodes), Airtable Interfaces, healthchecks.io, Slack incoming webhook.

**Spec:** `docs/superpowers/specs/2026-10-06-deployment-monitoring-design.md`

## Global Constraints

- No changes to Python files, `tests/`, or `vercel.json`. Repo changes are `docs/monitoring.md` (new) and one line in `docs/runbook.md`.
- Airtable field names used in any doc or n8n node must match `docs/airtable-schema.md` exactly. The service writes by name.
- "Local" time means the n8n workflow timezone setting. Set it to `America/Los_Angeles` (Plexa is in Henderson, NV) on both the intake and monitor workflows.
- Freshness defaults: stale after 6 hours, checked only Mon–Fri 08:00–20:00 local. Health and intake-active checks run around the clock.
- healthchecks.io check: period 30 minutes, grace 15 minutes.
- Every Slack message goes to the one channel behind `ALERT_WEBHOOK_URL`. n8n posts with HTTP Request to that same webhook URL, not a Slack OAuth credential.
- `AUTO_REPLY_ENABLED=false` on Vercel for the entire duration of this plan. Go-live is the runbook's job, not this plan's.
- n8n expression and Code node syntax below targets n8n 1.x. Verify node option names against the version you are running once; the names are stable but UI labels drift.

## Review Focus

Failure modes the spec implies that no task's automated test can exercise, since every deliverable is configuration. Each has a manual check in the task that owns it.

1. **Freshness check fires on a quiet weekend.** The business window must be evaluated in `America/Los_Angeles`, not UTC. Task 6 Step 9 checks `$now.zoneName`.
2. **The newest Messages row is stale but the check reads an old row.** The Airtable Search must sort by `Processed At` descending with limit 1, not return an arbitrary row. Task 6 Step 3 verifies the returned row against the Airtable UI.
3. **Monitor errors mid-run and the healthchecks ping still fires.** The ping must be the last node and the check nodes must not use "Continue on fail". Task 7 Step 4 forces a node error and confirms no ping.
4. **Digest fires twice or never.** The 30-minute schedule lands on :00 and :30, so the digest gate is `hour == 8 && minute < 30`. If the schedule drifts, it misses. Task 6 Step 7 pins the Schedule node's trigger times.
5. **Health check passes while Airtable is actually unreachable.** `/health` reports `airtable: true` when config is present, not when writes succeed. The freshness check is what covers real Airtable failure; the Evaluate node in Task 1 documents this so nobody weakens the freshness check believing `/health` has it.

---

### Task 1: Write `docs/monitoring.md`

**Files:**
- Create: `docs/monitoring.md`

**Interfaces:**
- Consumes: field names from `docs/airtable-schema.md`; node naming style from `docs/n8n-workflow.md`.
- Produces: the node-by-node build instructions that Tasks 6, 7, 8, and 9 follow. Node names defined here (`Newest message`, `Health check`, `Intake status`, `Evaluate`, `Any alerts?`, `Slack alert`, `Digest time?`, `Digest rows`, `Build digest`, `Slack digest`, `Ping healthchecks`) are referenced by name in `$('...')` expressions, so they must be typed exactly.

- [ ] **Step 1: Write the file**

Create `docs/monitoring.md` with this content:

````markdown
# Plexa Monitoring: watchdog, digest, dead-man's switch, status view

Companion to `n8n-workflow.md`. Build this after the intake workflow is active.
Everything below reads from the Airtable Messages table and posts to the Slack
incoming webhook already used by the service (`ALERT_WEBHOOK_URL`).

## Workflow settings (both workflows)

- Timezone: `America/Los_Angeles`. The business-window logic uses `$now`,
  which follows this setting.
- Error Workflow: a one-node workflow named `Plexa Errors` with an HTTP Request
  POST to the Slack webhook, body
  `{"text": "n8n error in {{ $json.workflow.name }}: {{ $json.execution.error.message }}"}`.

## Workflow: Plexa Monitor

Twelve nodes: a chain of checks, an alert branch, a digest branch, and a final
ping. Node names matter: later nodes reference earlier ones with `$('Node name')`.

### 1. Schedule Trigger
- Trigger Interval: Minutes
- Minutes Between Triggers: 30
- Runs must land on :00 and :30 so the digest gate in node 5 (`minute < 30`)
  is reliable. If the next-execution preview shows other minutes, switch to
  Custom (Cron) with `0,30 * * * *`.

### 2. Airtable — "Newest message"
- Credential: the same personal access token as the service
- Operation: Search
- Base / Table: `AIRTABLE_BASE_ID` / Messages
- Options → Sort: field `Processed At`, direction Descending
- Options → Limit: 1
- Settings → Always Output Data: ON (an empty table must not stop the run)

### 3. HTTP Request — "Health check"
- Method: GET
- URL: `https://<your-vercel-domain>/health`
- Options → Response → Include Response Headers and Status: ON
- Options → Response → Never Error: ON (a 5xx must reach the Evaluate node,
  not abort the run)
- Options → Timeout: 15000

### 4. HTTP Request — "Intake status"
- Method: GET
- URL: `https://<your-n8n-host>/api/v1/workflows/<intake-workflow-id>`
  (the id is the last path segment of the intake workflow's editor URL)
- Authentication: Generic → Header Auth; Name `X-N8N-API-KEY`, Value: an API
  key from n8n Settings → n8n API
- Options → Response → Include Response Headers and Status: ON
- Options → Response → Never Error: ON
- Options → Timeout: 15000

### 5. Code — "Evaluate"
Mode: Run Once for All Items. Paste exactly:

```javascript
const STALE_HOURS = 6;
const WINDOW_START = 8;   // 08:00 local
const WINDOW_END = 20;    // 20:00 local
const now = $now;         // Luxon DateTime in the workflow timezone

const alerts = [];

// --- Freshness (only inside the business window) ---
// NOTE: /health reports airtable:true when config is present, not when
// writes succeed. This freshness check is the only signal for a real
// Airtable outage. Do not weaken it on the assumption /health covers it.
const inWindow = now.weekday <= 5 && now.hour >= WINDOW_START && now.hour < WINDOW_END;
const newest = $('Newest message').first().json;
const processedAt = newest && newest['Processed At'];
if (inWindow) {
  if (!processedAt) {
    alerts.push('No rows in Messages table at all.');
  } else {
    const ageHours = now.diff(DateTime.fromISO(processedAt), 'hours').hours;
    if (ageHours > STALE_HOURS) {
      alerts.push(`No email processed in ${ageHours.toFixed(1)} h (last: ${processedAt}).`);
    }
  }
}

// --- Service health ---
const health = $('Health check').first().json;
if (health.statusCode !== 200) {
  alerts.push(`/health returned ${health.statusCode}.`);
} else if (health.body && health.body.airtable !== true) {
  alerts.push('/health reports airtable: false (env vars missing on Vercel).');
}

// --- Intake workflow active ---
const intake = $('Intake status').first().json;
if (intake.statusCode !== 200) {
  alerts.push(`n8n API returned ${intake.statusCode} for the intake workflow.`);
} else if (intake.body && intake.body.active !== true) {
  alerts.push('Intake workflow is DEACTIVATED. No emails are being processed.');
}

const digestTime = now.weekday <= 5 && now.hour === 8 && now.minute < 30;

return [{
  json: {
    alerts,
    hasAlerts: alerts.length > 0,
    digestTime,
    tz: now.zoneName,
    checkedAt: now.toISO(),
  },
}];
```

### 6. IF — "Any alerts?"
- Condition: Boolean `{{ $json.hasAlerts }}` is true
- True → node 7, then node 8. False → node 8.

### 7. HTTP Request — "Slack alert"
- Method: POST, URL: the Slack incoming webhook
- Send Body: JSON
- Body: `{{ JSON.stringify({ text: ':rotating_light: Plexa Monitor\n' + $('Evaluate').first().json.alerts.map(a => '• ' + a).join('\n') }) }}`
- Connect its output to node 8.

### 8. IF — "Digest time?"
- Condition: Boolean `{{ $('Evaluate').first().json.digestTime }}` is true
- True → nodes 9–11, then 12. False → node 12.

### 9. Airtable — "Digest rows"
- Operation: Search, Table: Messages
- Filter By Formula: `IS_AFTER({Processed At}, DATEADD(NOW(), -2, 'days'))`
  (fetch two days; node 10 trims to the previous local calendar day)
- Options → Limit: 500
- Settings → Always Output Data: ON

### 10. Code — "Build digest"
Mode: Run Once for All Items. Paste exactly:

```javascript
const now = $now;
const dayStart = now.startOf('day').minus({ days: 1 });
const dayEnd = now.startOf('day');

const rows = $input.all()
  .map(i => i.json)
  .filter(r => r['Processed At'])
  .filter(r => {
    const t = DateTime.fromISO(r['Processed At']);
    return t >= dayStart && t < dayEnd;
  });

const count = (field) => rows.reduce((acc, r) => {
  const k = r[field] || '(blank)';
  acc[k] = (acc[k] || 0) + 1;
  return acc;
}, {});
const fmt = (obj) => Object.entries(obj).map(([k, v]) => `${k}: ${v}`).join(', ') || 'none';

const byClass = count('Classification');
const byTier = count('Tier');
const byStatus = count('Status');
const manual = rows.filter(r => r.Status === 'Manual Review');

const lines = [
  `:clipboard: Plexa daily digest for ${dayStart.toFormat('ccc d LLL')}`,
  `Processed: ${rows.length}`,
  `Classification — ${fmt(byClass)}`,
  `Tier — ${fmt(byTier)}`,
  `Status — ${fmt(byStatus)}`,
];
if (manual.length) {
  lines.push(`Manual Review (${manual.length}):`);
  for (const r of manual) {
    const err = (r.Error || '').replace(/\s+/g, ' ').slice(0, 120);
    lines.push(`• ${r.Email || '?'} — "${r.Subject || ''}" — ${err}`);
  }
}

return [{ json: { text: lines.join('\n') } }];
```

### 11. HTTP Request — "Slack digest"
- Method: POST, URL: the Slack incoming webhook
- Send Body: JSON, Body: `{{ JSON.stringify({ text: $json.text }) }}`
- Connect its output to node 12.

### 12. HTTP Request — "Ping healthchecks"
- Method: GET, URL: the healthchecks.io ping URL (see below)
- Options → Timeout: 10000
- This must be the last node. Both the false output of node 8 and the output
  of node 11 feed it. If any earlier node errors, the run aborts before this
  node, the Error Workflow posts to Slack, and healthchecks.io also alerts
  when the ping is missed.

## Dead-man's switch: healthchecks.io

1. Create a free account, add a check named `plexa-monitor`.
2. Period: 30 minutes. Grace: 15 minutes.
3. Integrations → Slack → the same channel as the webhook.
4. Copy the ping URL into node 12.

If n8n is down, the monitor is deactivated, or the monitor errors, pings stop
and healthchecks.io alerts within 45 minutes of the last clean run.

## Status view: Airtable Interface "Plexa Pipeline"

Interfaces → Create → start from blank. Four elements:

| # | Element | Table | Filter | Fields / grouping |
|---|---|---|---|---|
| 1 | Number ("Last processed") | Messages | none | Summary: Max of `Processed At` |
| 2 | Chart or Grid ("Last 24h by tier") | Messages | `Processed At` is within past 1 day | Group by `Tier` |
| 3 | Grid ("Manual Review, 7d") | Messages | `Status` is `Manual Review` AND `Processed At` within past 7 days | `Email`, `Subject`, `Error`, `Processed At` |
| 4 | Grid ("Leads needing a human") | Leads | `Status` is `Needs Review` | `Email`, `Name`, `Tier`, `Last Subject`, `Last Contact` |

Share the Interface with Ryan as a collaborator with read access to the base.

Fallback if Interfaces are unavailable on the plan: create saved grid views
with filters 2–4 above (views named `Last 24h`, `Manual Review 7d` on
Messages; `Needs Review` on Leads).

## Verification checklist

Done means all four pass. Record pass/fail and date in the shadow-run notes.

1. Deactivate the intake workflow. Within 30 minutes a Slack alert reads
   "Intake workflow is DEACTIVATED". Reactivate.
2. Deactivate Plexa Monitor. Within 45 minutes healthchecks.io posts
   "plexa-monitor is DOWN" to Slack. Reactivate; confirm it posts "is UP".
3. Force a Manual Review: temporarily rename the Messages field `Tokens` to
   `Tokenz`, POST the runbook test email, confirm the real-time Slack alert.
   Rename the field back. Confirm a subsequent successful test row appears in
   the next morning's digest. Delete the test rows.
4. Set `STALE_HOURS = 0` in the Evaluate node during the business window.
   On the next run Slack reads "No email processed in ... h". Set it back to 6.

## Tuning

`STALE_HOURS`, `WINDOW_START`, `WINDOW_END` live at the top of the Evaluate
node. Revisit after the first week of real volume. If inquiries are rare
enough that 6 hours alerts daily with nothing wrong, raise it rather than
widening the window.
````

- [ ] **Step 2: Verify every Airtable field name in the doc exists in the schema**

Run:
```bash
for f in "Processed At" "Classification" "Tier" "Status" "Error" "Email" "Subject" "Tokens" "Name" "Last Subject" "Last Contact"; do
  grep -q "^| $f " docs/airtable-schema.md && echo "ok   $f" || echo "MISSING $f"
done
```
Expected: eleven `ok` lines, zero `MISSING`.

- [ ] **Step 3: Verify every node referenced by `$('...')` has a heading**

Run:
```bash
grep -o "\$('[^']*')" docs/monitoring.md | sort -u
grep -o '— "[^"]*"' docs/monitoring.md | sort -u
```
Expected: the first list is `Evaluate`, `Health check`, `Intake status`, `Newest message`. Each name appears in the second list as a node heading.

- [ ] **Step 4: Commit**

```bash
git add docs/monitoring.md
git commit -m "docs: monitor workflow, dead-man's switch, status interface, verification"
```

---

### Task 2: Point the runbook at the monitoring doc

**Files:**
- Modify: `docs/runbook.md` (the "Shadow run" section, step 1)

**Interfaces:**
- Consumes: `docs/monitoring.md` from Task 1.
- Produces: nothing downstream.

- [ ] **Step 1: Add the pointer**

In `docs/runbook.md`, under `## Shadow run (1–2 weeks)`, change step 1 from:

```
1. Activate the n8n workflow with `AUTO_REPLY_ENABLED=false`.
```
to:
```
1. Activate the n8n workflow with `AUTO_REPLY_ENABLED=false`. Then build the
   monitor, dead-man's switch, and status interface per `docs/monitoring.md`
   and run its verification checklist before counting shadow days.
```

- [ ] **Step 2: Verify**

Run: `grep -n "monitoring.md" docs/runbook.md`
Expected: one match inside the Shadow run section.

- [ ] **Step 3: Commit**

```bash
git add docs/runbook.md
git commit -m "docs: runbook points to monitoring setup before shadow run"
```

---

### Task 3: Create the Airtable base

**Files:** none. External configuration.

**Interfaces:**
- Consumes: `docs/airtable-schema.md`.
- Produces: `AIRTABLE_BASE_ID` (starts with `app`) and `AIRTABLE_API_KEY` for Task 4; the Messages table that Tasks 6 and 8 read.

- [ ] **Step 1: Create the base and both tables**

Follow `docs/airtable-schema.md` exactly. For each single-select field, add every listed option before saving. `Email` must be the primary field on Leads; `Message ID` on Messages. `Last Contact`, `Last Reply At`, `Processed At` are Date fields with "Include time" ON and timezone set to UTC.

- [ ] **Step 2: Create the token**

At https://airtable.com/create/tokens: scopes `data.records:read`, `data.records:write`, `schema.bases:read`, access limited to this base. Copy the token and the base id.

- [ ] **Step 3: Verify the schema through the API**

Run (replace the two values):
```bash
curl -s "https://api.airtable.com/v0/meta/bases/<BASE_ID>/tables" -H "Authorization: Bearer <TOKEN>" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(t['name'], sorted(f['name'] for f in t['fields'])) for t in d['tables']]"
```
Expected: two lines. `Leads` lists all 20 fields from the schema doc; `Messages` lists all 11.

---

### Task 4: Deploy the service to Vercel and smoke test

**Files:** none. Uses existing `vercel.json`.

**Interfaces:**
- Consumes: Airtable token and base id from Task 3; a Slack incoming webhook URL (create one at api.slack.com/apps → Incoming Webhooks if none exists).
- Produces: `https://<vercel-domain>` and the `WEBHOOK_SECRET` value for Task 5; the `/health` URL for Task 6.

- [ ] **Step 1: Link and set env vars**

Run from the worktree root:
```bash
vercel link
vercel env add OPENAI_API_KEY production
vercel env add WEBHOOK_SECRET production        # value: openssl rand -hex 32
vercel env add AIRTABLE_API_KEY production
vercel env add AIRTABLE_BASE_ID production
vercel env add AUTO_REPLY_ENABLED production    # value: false
vercel env add ALERT_WEBHOOK_URL production     # Slack incoming webhook
```

- [ ] **Step 2: Deploy**

```bash
vercel --prod
```
Note the production URL. Then:
```bash
vercel env add ALLOWED_ORIGIN production        # value: https://<vercel-domain>
vercel --prod
```

- [ ] **Step 3: Health check**

Run: `curl -s https://<vercel-domain>/health`
Expected JSON contains `"status": "ok"`, `"airtable": true`, `"auto_reply_enabled": false`.

- [ ] **Step 4: Smoke test the ingest path**

```bash
curl -s -X POST https://<vercel-domain>/ingest \
  -H "Content-Type: application/json" -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -d '{"sender_email":"runbook@test.com","sender_name":"Run Book","subject":"2BR Henderson","body_plain":"Need a 2 bedroom in Henderson, $1800 budget","message_id":"runbook-1"}'
```
Expected: `"tier": "Tier 1"`, `"reply": {"should_send": false, "skip_reason": "auto_reply_disabled", ...}`. In Airtable: one new row in Leads (Email `runbook@test.com`) and one in Messages (Message ID `runbook-1`). Leave these rows; Task 6 uses the Messages row as the "newest". Delete them at the end of Task 9.

- [ ] **Step 5: Confirm auth fails closed**

Run: `curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<vercel-domain>/ingest -H "Content-Type: application/json" -d '{}'`
Expected: `401`.

---

### Task 5: Build and activate the intake workflow in n8n

**Files:** none. External configuration.

**Interfaces:**
- Consumes: `docs/n8n-workflow.md`; Vercel URL and `WEBHOOK_SECRET` from Task 4.
- Produces: the intake workflow's id (last segment of its editor URL) for Task 6 node 4.

- [ ] **Step 1: Create the error workflow and settings**

First create `Plexa Errors`: one HTTP Request node, POST to the Slack webhook, Send Body JSON, body `{"text": "n8n error in {{ $json.workflow.name }}: {{ $json.execution.error.message }}"}`. Save.

Then a new workflow named `Plexa Intake`. Settings → Timezone `America/Los_Angeles`. Settings → Error Workflow → `Plexa Errors`.

- [ ] **Step 2: Build the six nodes**

Follow `docs/n8n-workflow.md` nodes 1–6b exactly, including the Header Auth credential, 90000 ms timeout, retry 2 × 5000 ms, and batching 1 item / 200 ms.

- [ ] **Step 3: Create the Gmail labels**

In Gmail, create labels `Plexa/Needs Attention` and `Plexa/Processed`. Re-open the two Add Label nodes and select them.

- [ ] **Step 4: Test with one real email**

Activate the workflow. From a personal address, send an email to the Plexa inbox with subject `Test 1BR Las Vegas` and body `Looking for a 1 bedroom in Las Vegas, moving in December, budget 1400.` Wait up to 2 minutes.

Expected: in n8n Executions, one successful run. In Airtable Messages, a new row with that Gmail message id, `Classification` LEAD, `Tier` Tier 1, `Should Reply` unchecked, `Skip Reason` `auto_reply_disabled`. In Gmail, the email carries label `Plexa/Processed` and no reply was sent.

- [ ] **Step 5: Record the workflow id**

Copy the id from the editor URL (`/workflow/<id>`). Task 6 needs it.

---

### Task 6: Build the Plexa Monitor workflow

**Files:** none. Follows `docs/monitoring.md` from Task 1.

**Interfaces:**
- Consumes: Airtable credential (Task 3), Vercel URL (Task 4), intake workflow id (Task 5), Slack webhook URL, `Plexa Errors` workflow (Task 5).
- Produces: a running monitor with a `Ping healthchecks` node whose URL Task 7 fills in.

- [ ] **Step 1: Create the workflow and settings**

New workflow `Plexa Monitor`. Settings → Timezone `America/Los_Angeles`. Error Workflow → `Plexa Errors`.

- [ ] **Step 2: Create an n8n API key**

n8n Settings → n8n API → Create. Store it as a Header Auth credential named `n8n API` with header name `X-N8N-API-KEY`.

- [ ] **Step 3: Add nodes 1–2 and test the Airtable read**

Add Schedule Trigger and the Airtable `Newest message` node per the doc. Click "Test step" on `Newest message`.
Expected: exactly one item, and its `Processed At` equals the most recent row visible when you sort the Messages table by `Processed At` descending in the Airtable UI.

- [ ] **Step 4: Add nodes 3–4 and test**

Add `Health check` and `Intake status`. Test step each.
Expected: `Health check` output has `statusCode: 200` and `body.airtable: true`. `Intake status` output has `statusCode: 200` and `body.active: true`. If `Intake status` returns 401, the API key header is wrong.

- [ ] **Step 5: Add node 5 (Evaluate) and test**

Paste the Evaluate code exactly from the doc. Test step.
Expected output: `hasAlerts: false`, `alerts: []`, `tz: "America/Los_Angeles"`, `digestTime` true or false depending on the current time.

- [ ] **Step 6: Add nodes 6–8 and test the alert path**

Wire `Any alerts?` true → `Slack alert` → `Digest time?`, false → `Digest time?`. Temporarily set `const STALE_HOURS = 0;` in Evaluate and run the workflow manually during the business window.
Expected: a Slack message beginning `:rotating_light: Plexa Monitor` with one bullet about no email processed. Restore `STALE_HOURS = 6`.

- [ ] **Step 7: Pin the schedule times**

Open the Schedule Trigger. Confirm the next-execution preview shows times at `:00` and `:30`. If it shows other minutes, switch Trigger Interval to Custom (Cron) with expression `0,30 * * * *`.

- [ ] **Step 8: Add nodes 9–11 and test the digest**

Add `Digest rows`, `Build digest`, `Slack digest`. Wire `Digest time?` true → `Digest rows` → `Build digest` → `Slack digest`. To test, temporarily replace Evaluate's `digestTime` line with `const digestTime = true;` and run manually.
Expected: a Slack message beginning `:clipboard: Plexa daily digest for` with counts. If yesterday had no rows, `Processed: 0` and `none` for each line is correct. Restore the original `digestTime` line.

- [ ] **Step 9: Confirm timezone**

Run the workflow manually. Open the Evaluate output.
Expected: `tz` is `America/Los_Angeles` and `checkedAt` shows a `-07:00` or `-08:00` offset. If `tz` is `UTC`, the workflow setting did not save.

- [ ] **Step 10: Add node 12 placeholder and activate**

Add `Ping healthchecks` with URL `https://hc-ping.com/PLACEHOLDER`. Wire the false output of `Digest time?` and the output of `Slack digest` into it. Set this node's Settings → On Error → Continue, so the placeholder does not fail runs until Task 7 fills the URL. Activate the workflow.

---

### Task 7: Dead-man's switch

**Files:** none.

**Interfaces:**
- Consumes: the `Ping healthchecks` node from Task 6.
- Produces: a healthchecks.io check that alerts Slack when the monitor stops running.

- [ ] **Step 1: Create the check**

At healthchecks.io: new check `plexa-monitor`, Period 30 minutes, Grace 15 minutes. Integrations → add Slack, pick the same channel.

- [ ] **Step 2: Wire the ping URL**

Paste the ping URL into `Ping healthchecks`. Set its Settings → On Error back to "Stop Workflow". Save.

- [ ] **Step 3: Confirm the first ping**

Run the monitor manually. In healthchecks.io the check status turns green and "Last ping" is seconds ago.

- [ ] **Step 4: Confirm a mid-run error suppresses the ping**

Temporarily change `Health check`'s URL to `https://<vercel-domain>/nope` and turn its Never Error option OFF. Run manually.
Expected: the run fails at `Health check`, `Plexa Errors` posts to Slack, and healthchecks.io "Last ping" does not update. Restore the URL and turn Never Error back ON. Run once more and confirm the ping resumes.

---

### Task 8: Airtable Interface

**Files:** none.

**Interfaces:**
- Consumes: the base from Task 3 with at least the Task 4 and Task 5 rows in it.
- Produces: the "Plexa Pipeline" Interface Ryan uses.

- [ ] **Step 1: Build the four elements**

Follow the Status view table in `docs/monitoring.md`. Name the Interface `Plexa Pipeline`.

- [ ] **Step 2: Verify against known data**

Expected: element 1 shows the `Processed At` of the Task 5 test email. Element 2 shows Tier 1 with a count of at least 2 (Task 4 curl plus Task 5 email). Element 3 is empty. Element 4 is empty.

- [ ] **Step 3: Share**

Add Ryan to the base as a read-only collaborator and send the Interface link. Record the Interface URL in the shadow-run notes.

---

### Task 9: Run the verification checklist

**Files:** none. Executes the checklist in `docs/monitoring.md`.

**Interfaces:**
- Consumes: everything from Tasks 4–8.
- Produces: a pass on all four checks. Record pass/fail with timestamps in the shadow-run notes.

- [ ] **Step 1: Intake deactivation alert**

Deactivate `Plexa Intake`. Wait for the next monitor run (at most 30 minutes).
Expected: Slack alert with bullet `Intake workflow is DEACTIVATED. No emails are being processed.` Reactivate `Plexa Intake`.

- [ ] **Step 2: Dead-man's switch**

Deactivate `Plexa Monitor`. Wait up to 45 minutes.
Expected: healthchecks.io posts `plexa-monitor is DOWN` to Slack. Reactivate and run once manually; healthchecks.io posts `plexa-monitor is UP`.

- [ ] **Step 3: Manual Review end to end**

In Airtable, rename the Messages field `Tokens` to `Tokenz`. Run the Task 4 smoke-test curl with `"message_id":"runbook-2"`.
Expected: response `"status": "Manual Review"` and a real-time Slack alert from the service. No `runbook-2` row appears in Messages, because the write failed. Rename `Tokenz` back to `Tokens`. Run the curl again with `"message_id":"runbook-3"` and confirm `"tier": "Tier 1"` and a Messages row. Tomorrow at 8am, confirm the digest counts `runbook-3` under `Processed`. For a visual check of Interface element 3, set the `runbook-3` row's `Status` to `Manual Review` by hand, confirm it appears, then revert.

- [ ] **Step 4: Freshness alert**

During the business window, set `STALE_HOURS = 0` in Evaluate. Wait for the next run.
Expected: Slack alert `No email processed in ... h`. Set `STALE_HOURS = 6`.

- [ ] **Step 5: Clean up test rows**

Delete Leads row `runbook@test.com` and Messages rows `runbook-1`, `runbook-3`. Leave the Task 5 real test email rows; they are legitimate shadow data.

- [ ] **Step 6: Mark the shadow period start**

Note today's date as shadow day 1 in the team channel. The shadow period runs per `docs/runbook.md`.
