# n8n Workflow: Gmail → Plexa Pipeline → Reply

Six nodes. n8n owns all Gmail I/O; the Python service never touches Gmail.

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

The function's maxDuration is 60 s (vercel.json). The OpenAI budget is 2 calls × 20 s × 2 attempts = 80 s worst case; typical is under 10 s. Keep the n8n timeout above maxDuration so n8n never retries a call Vercel is still running.

## 4. IF — "Needs attention?"
- Condition: String `{{ $json.status }}` equals `Manual Review`
- True branch → Gmail — Add Label: Operation Add Labels, Message ID
  `{{ $('Build payload').item.json.message_id }}`, Label `Plexa/Needs Attention`.
  Stop here: do NOT add the `Plexa/Processed` label (node 6b).
- False branch → node 5.

## 5. IF — "Should reply?"
- Condition: Boolean `{{ $json.reply.should_send }}` is true

## 6a. (true) Gmail — Reply
- Resource: Message, Operation: Reply
- Message ID: `{{ $('Build payload').item.json.message_id }}`
- Email Type: HTML
- Message: `{{ $json.reply.html }}`
- Options: Reply to Sender Only ON. Subject is inherited from the thread; if the
  node exposes a Subject field, set `{{ $json.reply.subject }}`.

## 6b. (both branches of node 5) Gmail — Add Label
- Operation: Add Labels, Message ID as above, Label: `Plexa/Processed`
- Do NOT mark as read; leave read state to Ryan.

## Error handling
Enable the workflow's Error Workflow to post to Slack. The service itself also
alerts on `ALERT_WEBHOOK_URL` for `Manual Review` outcomes.

## Shadow mode
With `AUTO_REPLY_ENABLED=false` on the service, every response has
`reply.should_send = false`, so node 6a never fires. `reply.skip_reason` is
`auto_reply_disabled` for first-contact and Tier 3 follow-up messages, and
`follow_up` for Tier 1/2 follow-ups. Leads and Messages are still written to Airtable.

Possible `reply.skip_reason` values: `auto_reply_disabled`, `max_replies_reached`, `cooldown_active`, `follow_up`, `junk`, `duplicate`, `pipeline_error`.
`follow_up` means a sender whose Leads row is already Tier 1 or Tier 2 wrote again;
the service does not auto-reply and sets the lead to `Needs Review` for a human.
