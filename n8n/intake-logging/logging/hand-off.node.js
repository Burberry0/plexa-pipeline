// ═══════════════════════════════════════════════════════════════════════════
// n8n — "Log: Hand-off" · Code node · Mode: "Run Once for Each Item"
// Workflow: Plexa Intake · "HTTP Request" (POST to Property Matching) BOTH
// outputs — success and error — plus "Match ready?" FALSE, all into this one node
//
// GENERATED into the workflow by n8n/intake-logging/logging-nodes.js. Edit this
// file, rebuild, re-import. Never edit the node in the n8n UI.
//
// The last step of an approved lead: the reply has gone out, the email is
// labelled Processed, and the match request has been POSTed to the Property
// Matching workflow's webhook. One message closes the loop for that email.
//
//   Green   reply sent and the match request accepted by the webhook
//   Green   reply sent; the lead was not match-ready, so "Match ready?" sent it
//           here instead of to the POST (the service built no request)
//   Red     reply sent but the POST to the matching webhook failed: the
//           requester got an answer promising a match that never started
//
// The Property Matching workflow posts its own validate / search / pricing /
// run messages once it has the request, so this node says nothing about what
// matching did with it.
// ═══════════════════════════════════════════════════════════════════════════
const p = pairedJson('Build payload');
const r = pairedJson('POST /ingest');
const m = r.match || {};
const req = m.request || {};
const failed = $json && $json.error !== undefined && $json.error !== null;
const sender = who(p), subject = subjectOf(p);

const matchBrief = m.ready
  ? 'zip ' + str(req.zip_code || '?') + ', ' + str(req.bedrooms || '?') + 'BR, move-in ' + str(req.move_in_date || '?')
  : 'not match-ready' + (Array.isArray(m.missing_fields) && m.missing_fields.length ? ' (missing: ' + m.missing_fields.join(', ') + ')' : '');

let severity = 'Green', status = 'success', summary, error;
if (failed) {
  const message = errMessage($json) || 'unknown error';
  const httpCode = httpStatus($json);
  severity = 'Red'; status = 'fail';
  summary = 'Reply sent to ' + sender + ' — "' + subject + '", but the match request POST to Property Matching failed: ' +
    message + '. Submit the match request by hand (' + matchBrief + ').';
  error = { message, node: 'HTTP Request' };
  if (httpCode !== undefined) error.http_status = httpCode;
} else if (m.ready) {
  summary = 'Reply sent to ' + sender + ' — "' + subject + '"; match request handed to Property Matching (' + matchBrief + ').';
} else {
  summary = 'Reply sent to ' + sender + ' — "' + subject + '"; ' + matchBrief + ', so no match request was built.';
}

return contract({
  stage: 'match',
  status,
  severity,
  summary,
  error,
  details: {
    sender: p.sender_email,
    subject,
    tier: r.tier,
    match: failed ? 'FAILED' : (m.ready ? 'sent' : 'none'),
    zip_code: m.ready ? req.zip_code : null,
    bedrooms: m.ready ? req.bedrooms : null,
    move_in_date: m.ready ? req.move_in_date : null,
    reply_subject: r.reply && r.reply.subject,
    partner: r.partner && r.partner.known ? (r.partner.inventory_tier || 'known') : null,
  },
});
