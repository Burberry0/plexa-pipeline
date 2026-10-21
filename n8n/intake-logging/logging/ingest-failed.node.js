// ═══════════════════════════════════════════════════════════════════════════
// n8n — "Log: Ingest Failed" · Code node · Mode: "Run Once for Each Item"
// Workflow: Plexa Intake · "POST /ingest" ERROR output
//
// GENERATED into the workflow by n8n/intake-logging/logging-nodes.js. Edit this
// file, rebuild, re-import. Never edit the node in the n8n UI.
//
// The service call failed after its 2 tries: 401/403 (webhook secret), 503
// (WEBHOOK_SECRET unset on Vercel), 5xx, or a timeout past the 90 s budget.
// Nothing was classified, nothing was written to Airtable, no reply was
// proposed, and the email sits in the inbox with no label. Before this node
// that was an n8n crash; now the run stays green and Slack is the record.
// Red, always: a person wrote in and nobody will answer until someone looks.
// ═══════════════════════════════════════════════════════════════════════════
const p = pairedJson('Build payload');
const message = errMessage($json) || 'unknown error';
const status = httpStatus($json);
const error = { message, node: 'POST /ingest' };
if (status !== undefined) error.http_status = status;

return contract({
  stage: 'ingest',
  status: 'fail',
  severity: 'Red',
  summary: 'POST /ingest failed for ' + who(p) + ' — "' + subjectOf(p) + '": ' + message +
    '. The email was not classified or replied to and carries no label.',
  error,
  details: {
    sender: p.sender_email,
    subject: subjectOf(p),
    message_id: p.message_id,
    endpoint: '/ingest',
    tries: 2,
    action: 'Check the Vercel function logs and the Plexa Webhook Secret credential; the message will not be re-polled, handle it by hand',
  },
});
