# Plexa Pipeline Runbook

## Deploy to Vercel

```bash
vercel link
vercel env add OPENAI_API_KEY production
vercel env add WEBHOOK_SECRET production        # openssl rand -hex 32
vercel env add AIRTABLE_API_KEY production
vercel env add AIRTABLE_BASE_ID production
vercel env add AUTO_REPLY_ENABLED production    # true; n8n's Slack approval step is the gate (see n8n-workflow.md 5b)
vercel env add ALERT_WEBHOOK_URL production     # Slack incoming webhook; required in production (Manual Review alerts are the only record when Airtable is down)
vercel env add ALLOWED_ORIGIN production        # https://<your-vercel-domain>
vercel --prod
curl https://<your-vercel-domain>/health
```

`/health` must show `"airtable": true`. Then:

```bash
curl -X POST https://<your-vercel-domain>/ingest \
  -H "Content-Type: application/json" -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -d '{"sender_email":"runbook@test.com","sender_name":"Run Book","subject":"2BR Henderson","body_plain":"Need a 2 bedroom in Henderson, $1800 budget","message_id":"runbook-1"}'
```

Expected: `tier: "Tier 1"`, `reply.should_send: false`, `reply.skip_reason: "auto_reply_disabled"`, and a new row in both Airtable tables. Delete the test rows afterwards.

## Shadow run (1–2 weeks)

1. Activate the n8n workflow with `AUTO_REPLY_ENABLED=true`. Replies only go
   out when someone clicks `Approve & send` on the Slack approval message
   (n8n-workflow.md node 5b), so the shadow period is "approve nothing you
   would not have written yourself". Then build the monitor, dead-man's
   switch, and status interface per `docs/monitoring.md` and run its
   verification checklist before counting shadow days.
2. Daily: open the Messages table, filter `Status = Manual Review`, fix root causes.
3. Twice a week: review 20 random Messages rows against the original email.
   Log any wrong `Classification` or wrong `Tier` into `evals/golden_emails.jsonl`
   with the correct labels.
4. Run `python -m evals.run_eval --min-tier-accuracy 0.9` after each prompt change.
5. Go-live gate: 7 consecutive days with zero JUNK false negatives in the
   sample and tier accuracy ≥ 0.9 on the golden set.
6. Sample 20 From addresses in the Messages table. If inquiries arrive via listing-site relay addresses (Zillow, Apartments.com), the one-record-per-sender design and Reply-to-Sender both key on the relay address; raise this with Ryan before go-live.

## Go-live

Go-live is a decision about the approval step, not an env var. Once the gate
in the Shadow run section is met, keep approving in Slack; there is no
unattended mode in this design. If Ryan later wants fully automatic replies,
that is a workflow change (bypass nodes 5a–5c) and a new sign-off, not a flag.

To confirm the send path works end to end: send one real test inquiry from a
personal address, click `Approve & send` on the Slack message, and confirm the
reply lands in-thread. Watch `Reply Count` on the Leads row increment to 1.

## Kill switch

Two levels:

- **Soft:** stop clicking Approve. Requests time out after 24 hours and are
  labeled Processed with a "declined" note in Slack. Nothing is sent.
- **Hard:** set `AUTO_REPLY_ENABLED=false` and redeploy. The service never
  decides to reply, so the approval step is never reached. Classification and
  Airtable writes continue.

To stop everything, deactivate the n8n intake workflow.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `/ingest` returns 503 | `WEBHOOK_SECRET` unset on Vercel | add env var, redeploy |
| `/ingest` returns 401 | n8n header mismatch | compare the Header Auth credential value in n8n with Vercel |
| Many `Manual Review` with `422` in Error | Airtable field name or select option missing | match `docs/airtable-schema.md` exactly |
| Replies not sent but `should_send: true` | n8n Gmail node error | check n8n execution log |
| Same sender gets two replies in a minute | Cooldown relies on `Last Reply At`; check the Leads row has it | confirm field type is Date with time |
| Email labeled Needs Attention / Manual Review in Messages | Airtable or OpenAI failure | fix the cause, then re-run the execution from n8n's execution history (the Gmail trigger will not re-poll it) |

### Known limitations

- If the Messages log write fails after a successful Leads upsert, an n8n retry of the same message will be reprocessed (dedupe finds no log entry); the cooldown and max-replies cap are the only protection against a second reply.
- If Vercel kills a function at maxDuration, no Messages row is written and n8n sees a 5xx; n8n's retry reprocesses the message from scratch.
- Duplicate and JUNK responses carry default `classification: "JUNK"` / `status: "New"` values; n8n must branch on `reply.should_send`, never on `classification`.
- The service passes the sender's subject through to `reply.subject` unmodified; header-injection safety (CR/LF stripping) is the Gmail node's responsibility.
