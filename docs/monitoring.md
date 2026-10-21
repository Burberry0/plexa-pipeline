# Plexa Monitoring: watchdog, digest, dead-man's switch, status view

Companion to `n8n-workflow.md`. Build this after the intake workflow is active.
Everything below reads from the Airtable Messages table and posts to the Slack
incoming webhook already used by the service (`ALERT_WEBHOOK_URL`).

## Workflow settings (both workflows)

- Timezone: `America/Los_Angeles`. The business-window logic uses `$now`,
  which follows this setting.
- Error Workflow: *Plexa — Slack Logger* (`RyanPlexa/n8n-logger/`), whose
  Error Trigger turns an unhandled crash into a Red Slack message naming the
  node. (Before 2026-10-20 this was a one-node `Plexa Errors` workflow posting
  `n8n error in {{ $json.workflow.name }}: …` to the incoming webhook.)

## Workflow: Plexa Monitor

Twelve nodes: a chain of checks, an alert branch, a digest branch, and a final
ping. Node names matter: later nodes reference earlier ones with `$('Node name')`.

### 1. Schedule Trigger
- Trigger Interval: Custom (Cron), expression `0,30 * * * *`
- Runs land on :00 and :30, which is what makes the digest gate in node 5
  (`hour === 8 && minute < 30`) fire exactly once a day.

### 2. Airtable — "Newest message"
- Credential: the same personal access token as the service
- Operation: Search
- Base / Table: `AIRTABLE_BASE_ID` / Messages
- Filter By Formula: `IS_AFTER({Processed At}, DATEADD(NOW(), -2, 'days'))`
- Return All: ON (bounded by two days of email volume)
- Sort: field `Processed At`, direction Descending
- Settings → Always Output Data: ON (an empty result must not stop the run)
- The Evaluate node takes the maximum `Processed At` across the returned rows,
  so the freshness check is correct even if the sort option is ignored.

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
const rows = $('Newest message').all().map(i => i.json).filter(r => r && r['Processed At']);
const processedAt = rows.length ? rows.map(r => r['Processed At']).sort().slice(-1)[0] : null;
if (inWindow) {
  if (!processedAt) {
    alerts.push('No email processed in the last 48 h.');
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
    lastProcessedAt: processedAt,
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
| 4 | Grid ("Leads needing a human") | Leads | `Status` is `Needs Review` | `Email`, `Name`, `Tier`, `Match Ready`, `Last Subject`, `Last Contact` |

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
