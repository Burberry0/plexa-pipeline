# n8n Workflow: Gmail → Plexa Pipeline → Reply → Property Matching

n8n owns all Gmail I/O and the hand-off to the Property Matching workflow; the
Python service never touches Gmail and never POSTs to matching. One Slack
approval covers both the reply and, when the lead is match-ready, the match
request.

## Response fields n8n uses

From `POST /ingest` (the full `PipelineResult.to_dict()`):

| Field | Use |
|---|---|
| `status` | node 4 (`Manual Review` → Needs Attention label) |
| `reply.should_send`, `reply.html`, `reply.subject`, `reply.skip_reason` | nodes 5, 5a, 6a |
| `match.ready` (bool) | node 6d; true only when zip, bedrooms and move-in are all known |
| `match.missing_fields` (list) | nodes 3b and 5a log text |
| `match.request` (object or null) | node 6e body: readable match fields (`zip_code`, `bedrooms`, `email`, …) for the matching workflow's Webhook node |
| `extraction.*` | node 3b log text (now includes `zip_code`, `bathrooms`, `amenities`, `phone`, `requester_type`) |
| `partner.known`, `partner.inventory_tier`, `partner.vendor`, `partner.matched_by` | Slack log / approval triage (known Full/Snap partner vs unknown sender) |

`match` is present on every response (JUNK, duplicate and error responses carry
`{ready: false, missing_fields: [], request: null}`), so node 6d never sees `undefined`.

## 1. Gmail Trigger
- Credential: Plexa inbox OAuth2
- Event: Message Received
- Poll: every 1 minute
- Filters: Label `INBOX`; Read status: Both (emails Ryan opens on his phone before the poll must still be processed; dedupe on message_id prevents repeats)
- Options: Download attachments OFF; Simplify OFF (we need html/text/threadId)

## 2. Set node — "Build payload"
Mode: Manual mapping, Keep only set fields. Fields (verify the exact input
paths against the trigger's output once; names below are the non-simplified
Gmail node output):

| Name | Type | Value |
|---|---|---|
| sender_email | String | `{{ $json.from.value[0].address }}` |
| sender_name | String | `{{ $json.from.value[0].name }}` |
| subject | String | `{{ $json.subject }}` |
| body_html | String | `{{ $json.html || '' }}` |
| body_plain | String | `{{ $json.text || '' }}` |
| message_id | String | `{{ $json.id }}` |
| thread_id | String | `{{ $json.threadId }}` |
| is_reply | Boolean | `{{ ($json.subject || '').toLowerCase().startsWith('re:') }}` |

## 3. HTTP Request — "POST /ingest"
- Method: POST
- URL: `https://<your-vercel-domain>/ingest`
- Authentication: Generic Credential Type → Header Auth; Name `X-Webhook-Secret`, Value = the WEBHOOK_SECRET. (Avoid `$env` expressions; many n8n instances block them.)
- Send Body: JSON, `{{ $json }}` (the Set node output)
- Options: Timeout 90000 ms; Retry on fail ON, 2 tries, 5000 ms wait.
  Retries are normally safe: the service dedupes on `message_id`. See the runbook's Known limitations for the one gap (a failed Messages-log write).
- Options: Batching: Items per Batch = 1, Batch Interval = 200 ms — requests from one Gmail poll run sequentially so a second message from the same sender sees the first one's Leads row and hits the cooldown.

The function's maxDuration is 60 s (vercel.json). The AI call budget is 2 calls × 20 s × 2 attempts = 80 s worst case; typical is under 10 s. Keep the n8n timeout above maxDuration so n8n never retries a call Vercel is still running.

## 3b. Code — "Build log" (parallel branch off node 3)
Connect node 3's output to this node *and* to node 4; both run on every email.
Mode: Run Once for All Items. Builds one Slack message per processed email so
the channel shows how the pipeline evaluated it:

- Duplicates and JUNK: one line each (`:repeat: Duplicate skipped — …`,
  `:wastebasket: JUNK — …`).
- Leads: classification, tier, status, sender, subject; then the extracted
  fields (location, zip, bedrooms, bathrooms, budget range, move-in, pets,
  occupants, duration, amenities), confidence, missing fields, extractor notes;
  then `Needs attention: YES/no` (with the error text when YES),
  `Reply decision: SEND → awaiting approval in Slack` or `skip (<skip_reason>)`,
  and `Match ready: yes` or `Match ready: no (missing: zip_code, move_in_date)`
  from `$json.match`.

Reads `$json` (the `/ingest` response) and `$('Build payload').item.json`.
Returns `{ text }`.

## 3c. HTTP Request — "Slack log"
- Method: POST, URL: the Slack incoming webhook (`ALERT_WEBHOOK_URL`)
- Send Body: JSON, Body: `{{ JSON.stringify({ text: $json.text }) }}`
- End of the logging branch; nothing downstream.

## 4. IF — "Needs attention?"
- Condition: String `{{ $json.status }}` equals `Manual Review`
- True branch → Gmail — Add Label: Operation Add Labels, Message ID
  `{{ $('Build payload').item.json.message_id }}`, Label `Plexa/Needs Attention`.
  Stop here: do NOT add the `Plexa/Processed` label (node 6b).
- False branch → node 5.

## 5. IF — "Should reply?"
- Condition: Boolean `{{ $json.reply.should_send }}` is true
- True → node 5a (human approval). False → node 6b.

## 5a. Code — "Build approval"
Mode: Run Once for All Items. Produces the approval request text: tier,
sender, subject; the inbound email as plain text (body_plain, or body_html
with tags stripped), quoted; the proposed reply with tags stripped, quoted;
and one last line so the approver knows what the click triggers:
`Approving will also send a property-match request: YES (zip 89052, 2BR, move-in 2026-11-01)`
or `Approving will also send a property-match request: no (missing: zip_code)`.
Reads `$('POST /ingest').item.json` (including `.match`) and
`$('Build payload').item.json`. Returns `{ text }`.

## 5b. Slack — "Approve reply?" (human in the loop)
- Credential: a Slack **bot** credential (the incoming webhook cannot wait for
  a click). Needs `chat:write` in the channel.
- Resource: Message, Operation: Send and Wait for Response
- Channel: the alerts channel
- Message: `{{ $json.text }}`
- Response Type: Approval; Type of Approval: Approve and Disapprove;
  labels `Approve & send` / `Decline`
- Options → Limit Wait Time: 24 hours. The execution pauses here until a
  button is clicked or the limit passes.

## 5c. IF — "Approved?"
- Condition: Boolean `{{ $json.data && $json.data.approved === true }}` is true
- True → node 6a. False (declined or timed out) → node 6c.

## 6a. (approved) Gmail — Reply
- Resource: Message, Operation: Reply
- Message ID: `{{ $('Build payload').item.json.message_id }}`
- Email Type: HTML
- Message: `{{ $('POST /ingest').item.json.reply.html }}`
- Options: Reply to Sender Only ON. Subject is inherited from the thread; if the
  node exposes a Subject field, set `{{ $('POST /ingest').item.json.reply.subject }}`.
- Output → node 6d.

## 6d. IF — "Match ready?"
- Condition: Boolean `{{ $('POST /ingest').item.json.match.ready === true }}` is true
- True → node 6e. False → node 6b.

Only approved messages reach this node, and approval only happens when
`reply.should_send` was true (first contact, or a follow-up from a Tier 3
sender). A follow-up from a sender who is already Tier 1/2 never auto-posts a
match request; a human handles it from `Needs Review`.

## 6e. HTTP Request — "POST matching"
- Method: POST
- URL: the Property Matching workflow's **Webhook node** production URL. Store
  it as an n8n variable `MATCHING_WEBHOOK_URL` (or paste it); it is not a
  Python env var and must not be added to the service.
- Send Body: JSON, Body: `{{ JSON.stringify($('POST /ingest').item.json.match.request) }}`
- Options: Timeout 30000 ms; Retry on fail ON, 1 retry, 5000 ms wait.
- The body uses readable keys (`first_name`, `last_name`, `email`, `zip_code`,
  `bedrooms`, `move_in_date` as `YYYY-MM-DD`, `pets`, `amenities`, …) plus
  `source: "email"`, `message_id`, `thread_id` for tracing — see
  `match_request.py`. The matching workflow's form-parse node must accept this
  shape (not only legacy JotForm `q*` keys). Verify once that it reads
  `$json.body` (or parses a stringified body) and that `amenities` arrives as
  an array.
- Output → node 6f.

## 6f. HTTP Request — "Slack match log"
- POST to the Slack webhook:
  `{{ JSON.stringify({ text: ':house: Match request sent to property matching for ' + $('Build payload').item.json.sender_email + ' (' + $('POST /ingest').item.json.tier + ', zip ' + $('POST /ingest').item.json.match.request.zip_code + ')' }) }}`
- Output → node 6b.

## 6c. (declined) HTTP Request — "Slack declined"
- POST to the Slack webhook:
  `{{ JSON.stringify({ text: ':no_entry: Reply declined (or approval timed out) for ' + $('Build payload').item.json.sender_email + ' — "' + $('Build payload').item.json.subject + '". Nothing sent.' }) }}`
- Output → node 6b.

## 6b. Gmail — Add Label (reached from 5 false, 6c, 6d false, and 6f)
- Operation: Add Labels, Message ID as above, Label: `Plexa/Processed`
- Do NOT mark as read; leave read state to Ryan.

Known limitation: the service increments the lead's `Reply Count` when it
*decides* to reply, not when the email is sent. A decline leaves the count one
high for that sender, which makes `MAX_AUTO_REPLIES` slightly stricter. This
fails safe and is left as is.

## Error handling
Enable the workflow's Error Workflow to post to Slack. The service itself also
alerts on `ALERT_WEBHOOK_URL` for `Manual Review` outcomes.

## Approval gate (replaces shadow mode)
The service runs with `AUTO_REPLY_ENABLED=true` so it produces real reply
decisions, and node 5b is the gate: nothing is sent until a human clicks
`Approve & send` in Slack. Every email is logged to Slack by node 3c regardless.

`AUTO_REPLY_ENABLED=false` remains available as a hard kill switch. With it set,
every response has `reply.should_send = false`, node 5a–6a never fire, and
`reply.skip_reason` is `auto_reply_disabled` for first-contact and Tier 3
follow-up messages, and `follow_up` for Tier 1/2 follow-ups. Leads and Messages
are still written to Airtable either way.

Possible `reply.skip_reason` values: `auto_reply_disabled`, `max_replies_reached`, `cooldown_active`, `follow_up`, `junk`, `duplicate`, `pipeline_error`.
`follow_up` means a sender whose stored extraction already satisfies the gate
(Tier 1 or Tier 2 under today's rules) wrote again; the service does not
auto-reply and sets the lead to `Needs Review` for a human.

## Property-matching hand-off (nodes 6d–6f)

The service only *builds* `match.request`; n8n sends it, and only after the
same human approval that gates the reply. Node names `POST /ingest` and
`Build payload` are referenced by expressions in 6d–6f; do not rename them.
To pause the hand-off without touching replies, disable node 6e.
