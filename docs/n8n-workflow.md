# n8n Workflow: Gmail → Plexa Pipeline → Reply

Five nodes. n8n owns all Gmail I/O; the Python service never touches Gmail.

## 1. Gmail Trigger
- Credential: Plexa inbox OAuth2
- Event: Message Received
- Poll: every 1 minute
- Filters: Label `INBOX`; Read status: Unread
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
- Send Headers: `X-Webhook-Secret` = `{{ $env.PLEXA_WEBHOOK_SECRET }}` (set in n8n env, not inline)
- Send Body: JSON, `{{ $json }}` (the Set node output)
- Options: Timeout 60000 ms; Retry on fail ON, 2 tries, 5000 ms wait.
  Retries are safe: the service dedupes on `message_id`.

## 4. IF — "Should reply?"
- Condition: Boolean `{{ $json.reply.should_send }}` is true

## 5a. (true) Gmail — Reply
- Resource: Message, Operation: Reply
- Message ID: `{{ $('Build payload').item.json.message_id }}`
- Email Type: HTML
- Message: `{{ $json.reply.html }}`
- Options: Reply to Sender Only ON. Subject is inherited from the thread; if the
  node exposes a Subject field, set `{{ $json.reply.subject }}`.

## 5b. (both branches) Gmail — Add Label
- Operation: Add Labels, Message ID as above, Label: `Plexa/Processed`
- Then Gmail — Mark as Read (optional).

## Error handling
Enable the workflow's Error Workflow to post to Slack. The service itself also
alerts on `ALERT_WEBHOOK_URL` for `Manual Review` outcomes.

## Shadow mode
With `AUTO_REPLY_ENABLED=false` on the service, every response has
`reply.should_send = false` and `reply.skip_reason = "auto_reply_disabled"`,
so node 5a never fires. Leads and Messages are still written to Airtable.
