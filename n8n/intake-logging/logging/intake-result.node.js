// ═══════════════════════════════════════════════════════════════════════════
// n8n — "Log: Intake Result" · Code node · Mode: "Run Once for Each Item"
// Workflow: Plexa Intake · "POST /ingest" success output, parallel to
// "Needs attention?" (both run on every email)
//
// GENERATED into the workflow by n8n/intake-logging/logging-nodes.js. Edit this
// file, rebuild, re-import. Never edit the node in the n8n UI.
//
// Replaces the old "Build log" → "Slack log" webhook post. One message per
// processed email, the moment the service answers, so the channel shows how
// each email was judged before anyone is asked to approve anything.
//
//   Red     status "Manual Review" (pipeline_error, Airtable 422, …): a person
//           wrote in and the service could not finish. Labelled Needs Attention.
//   Yellow  a lead the service decided NOT to answer: follow-up from a Tier 1/2
//           sender (Needs Review), cooldown, max replies, kill switch off.
//   Green   reply proposed and waiting for approval; JUNK filtered; duplicate
//           skipped.
//
// $json is the full /ingest response (PipelineResult.to_dict()). Never branch
// on `classification` alone: duplicates and JUNK carry default values.
// ═══════════════════════════════════════════════════════════════════════════
const r = $json || {};
const p = pairedJson('Build payload');
const e = r.extraction || {};
const rep = r.reply || {};
const m = r.match || {};
const partner = r.partner || {};
const sender = who(p), subject = subjectOf(p);

const fmt = v => (v === null || v === undefined || v === '') ? null
  : (Array.isArray(v) ? (v.length ? v.join(', ') : 'none') : String(v));
const money = (a, b) => (a != null && b != null) ? '$' + a + '–$' + b + '/mo'
  : b != null ? 'up to $' + b + '/mo' : a != null ? 'from $' + a + '/mo' : null;

const requirements = [
  e.bedrooms != null ? e.bedrooms + 'BR' : null,
  e.bathrooms != null ? e.bathrooms + 'BA' : null,
  money(e.budget_min, e.budget_max),
  has(e.move_in_date) ? 'move-in ' + e.move_in_date : null,
  Array.isArray(e.pets) ? 'pets: ' + (e.pets.length ? e.pets.join(', ') : 'none') : null,
  e.occupants != null ? e.occupants + ' occupant' + (e.occupants === 1 ? '' : 's') : null,
  e.duration_months != null ? e.duration_months + ' mo' : null,
].filter(Boolean).join(' · ');
const location = [fmt(e.location), has(e.zip_code) ? 'zip ' + e.zip_code : null].filter(Boolean).join(' · ');
const extraction = [
  e.confidence != null ? 'confidence ' + e.confidence : null,
  Array.isArray(e.missing_fields) && e.missing_fields.length ? 'missing: ' + e.missing_fields.join(', ') : null,
  has(e.notes) ? clip(e.notes, 200) : null,
].filter(Boolean).join(' · ');
const matchText = m.ready ? 'ready' : 'not ready' +
  (Array.isArray(m.missing_fields) && m.missing_fields.length ? ' (missing: ' + m.missing_fields.join(', ') + ')' : '');
const partnerText = partner.known
  ? 'known' + (has(partner.inventory_tier) ? ' · ' + partner.inventory_tier : '') +
    (has(partner.vendor) ? ' · ' + partner.vendor : '') + (has(partner.matched_by) ? ' (by ' + partner.matched_by + ')' : '')
  : null;

let severity = 'Green', status = 'success', summary, error;
if (r.is_duplicate) {
  summary = 'Duplicate skipped — ' + sender + ' — "' + subject + '" was already processed.';
} else if (r.classification === 'JUNK') {
  summary = 'JUNK filtered — ' + sender + ' — "' + subject + '". Nothing stored, nothing sent.';
} else if (r.status === 'Manual Review') {
  severity = 'Red'; status = 'fail';
  const why = has(r.error) ? str(r.error) : (has(rep.skip_reason) ? str(rep.skip_reason) : 'pipeline error');
  summary = 'Manual Review — ' + sender + ' — "' + subject + '": ' + why +
    '. Labelled Needs Attention; nothing was sent, reply by hand.';
  error = { message: clip(why, 600), node: 'POST /ingest' };
} else {
  const tier = has(r.tier) ? str(r.tier) : 'untiered';
  const upgrade = r.is_upgrade ? ' (upgrade from Tier 3)' : '';
  if (rep.should_send) {
    summary = tier + ' lead' + upgrade + ' from ' + sender + ' — "' + subject +
      '": reply awaiting approval in Slack; match ' + matchText + '.';
  } else {
    severity = 'Yellow';
    const reason = has(rep.skip_reason) ? str(rep.skip_reason) : 'no reason given';
    const hint = reason === 'follow_up' ? 'follow-up from a sender already past the gate; lead set to Needs Review for a human'
      : reason === 'cooldown_active' ? 'cooldown still active for this sender'
      : reason === 'max_replies_reached' ? 'this sender already had the maximum automatic replies'
      : reason === 'auto_reply_disabled' ? 'AUTO_REPLY_ENABLED is off (kill switch)'
      : reason;
    summary = tier + ' lead' + upgrade + ' from ' + sender + ' — "' + subject +
      '": no auto-reply (' + hint + '). Status ' + str(r.status || 'unknown') + '.';
  }
}

return contract({
  stage: 'intake',
  status,
  severity,
  summary,
  error,
  details: {
    sender: p.sender_email,
    subject,
    tier: r.is_duplicate || r.classification === 'JUNK' ? null : r.tier,
    status: r.status,
    reply: rep.should_send ? 'awaiting approval' : (has(rep.skip_reason) ? 'skip (' + rep.skip_reason + ')' : null),
    match: r.is_duplicate || r.classification === 'JUNK' ? null : matchText,
    location: location || null,
    requirements: requirements || null,
    extraction: extraction || null,
    partner: partnerText,
  },
});
