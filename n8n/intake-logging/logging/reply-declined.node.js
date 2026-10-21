// ═══════════════════════════════════════════════════════════════════════════
// n8n — "Log: Reply Declined" · Code node · Mode: "Run Once for Each Item"
// Workflow: Plexa Intake · "Approved?" FALSE output
//
// GENERATED into the workflow by n8n/intake-logging/logging-nodes.js. Edit this
// file, rebuild, re-import. Never edit the node in the n8n UI.
//
// Replaces the old "Slack declined" webhook post. A human clicked Decline on
// the approval message, or nobody clicked within the 24 h wait. Nothing was
// sent; the email is labelled Processed by the parallel connection. Yellow:
// the system worked, but a requester is not getting an answer from it.
//
// $json is the "Approve reply?" output: { data: { approved: false } } on a
// click; no `data.approved` when the wait timed out.
// ═══════════════════════════════════════════════════════════════════════════
const p = pairedJson('Build payload');
const r = pairedJson('POST /ingest');
const d = ($json && $json.data) || {};
const timedOut = d.approved !== false;
const outcome = timedOut ? 'nobody approved within 24 h' : 'declined in Slack';

return contract({
  stage: 'approval',
  status: 'success',
  severity: 'Yellow',
  summary: 'Reply to ' + who(p) + ' — "' + subjectOf(p) + '" ' + outcome +
    '. Nothing sent; email labelled Processed. Answer by hand if the lead is real.',
  details: {
    sender: p.sender_email,
    subject: subjectOf(p),
    outcome: timedOut ? 'timed out' : 'declined',
    tier: r.tier,
    match: r.match && r.match.ready ? 'was ready (not sent)' : null,
    reply_subject: r.reply && r.reply.subject,
  },
});
