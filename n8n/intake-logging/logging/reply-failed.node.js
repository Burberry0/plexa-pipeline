// ═══════════════════════════════════════════════════════════════════════════
// n8n — "Log: Reply Failed" · Code node · Mode: "Run Once for Each Item"
// Workflow: Plexa Intake · "Gmail Reply" ERROR output
//
// GENERATED into the workflow by n8n/intake-logging/logging-nodes.js. Edit this
// file, rebuild, re-import. Never edit the node in the n8n UI.
//
// A human approved the reply and Gmail refused to send it (token expired,
// quota, the original message gone). Before this node that was an n8n crash
// after the approval, which looked like success in Slack. The email is NOT
// labelled Processed and no match request goes out, because the success path
// never ran. Red: someone approved an answer that never left.
// ═══════════════════════════════════════════════════════════════════════════
const p = pairedJson('Build payload');
const r = pairedJson('POST /ingest');
const message = errMessage($json) || 'unknown Gmail error';
const status = httpStatus($json);
const error = { message, node: 'Gmail Reply' };
if (status !== undefined) error.http_status = status;

return contract({
  stage: 'reply',
  status: 'fail',
  severity: 'Red',
  summary: 'Approved reply to ' + who(p) + ' — "' + subjectOf(p) + '" was NOT sent: ' + message +
    '. Send it by hand; no label was applied and no match request went out.',
  error,
  details: {
    sender: p.sender_email,
    subject: subjectOf(p),
    tier: r.tier,
    reply_subject: r.reply && r.reply.subject,
    match: r.match && r.match.ready ? 'ready, not sent' : null,
    message_id: p.message_id,
    action: 'Reply from the inbox, then label Processed and, if match-ready, submit the match request by hand',
  },
});
