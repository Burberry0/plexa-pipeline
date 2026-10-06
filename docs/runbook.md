# Plexa Pipeline Runbook

## Deploy to Vercel

```bash
vercel link
vercel env add OPENAI_API_KEY production
vercel env add WEBHOOK_SECRET production        # openssl rand -hex 32
vercel env add AIRTABLE_API_KEY production
vercel env add AIRTABLE_BASE_ID production
vercel env add AUTO_REPLY_ENABLED production    # false until go-live
vercel env add ALERT_WEBHOOK_URL production     # Slack incoming webhook
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

1. Activate the n8n workflow with `AUTO_REPLY_ENABLED=false`.
2. Daily: open the Messages table, filter `Status = Manual Review`, fix root causes.
3. Twice a week: review 20 random Messages rows against the original email.
   Log any wrong `Classification` or wrong `Tier` into `evals/golden_emails.jsonl`
   with the correct labels.
4. Run `python -m evals.run_eval --min-tier-accuracy 0.9` after each prompt change.
5. Go-live gate: 7 consecutive days with zero JUNK false negatives in the
   sample and tier accuracy ≥ 0.9 on the golden set.

## Go-live

```bash
vercel env rm AUTO_REPLY_ENABLED production
vercel env add AUTO_REPLY_ENABLED production    # true
vercel --prod
```

Send one real test inquiry from a personal address and confirm the reply lands
in-thread. Watch `Reply Count` on the Leads row increment to 1.

## Kill switch

Set `AUTO_REPLY_ENABLED=false` and redeploy. Classification and Airtable writes
continue; no replies are sent. To stop everything, deactivate the n8n workflow.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `/ingest` returns 503 | `WEBHOOK_SECRET` unset on Vercel | add env var, redeploy |
| `/ingest` returns 401 | n8n header mismatch | compare `PLEXA_WEBHOOK_SECRET` in n8n with Vercel |
| Many `Manual Review` with `422` in Error | Airtable field name or select option missing | match `docs/airtable-schema.md` exactly |
| Replies not sent but `should_send: true` | n8n Gmail node error | check n8n execution log |
| Same sender gets two replies in a minute | Cooldown relies on `Last Reply At`; check the Leads row has it | confirm field type is Date with time |

### Known limitations

- If the Messages log write fails after a successful Leads upsert, an n8n retry of the same message will be reprocessed (dedupe finds no log entry); the cooldown and max-replies cap are the only protection against a second reply.
- Duplicate and JUNK responses carry default `classification: "JUNK"` / `status: "New"` values; n8n must branch on `reply.should_send`, never on `classification`.
- The service passes the sender's subject through to `reply.subject` unmodified; header-injection safety (CR/LF stripping) is the Gmail node's responsibility.
