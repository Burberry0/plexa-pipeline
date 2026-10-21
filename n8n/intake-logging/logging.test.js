'use strict';
// The Slack-logging additions to the Plexa Intake workflow: the wiring in the
// shipped "Plexa Intake.json", and the five Code-node bodies run under the
// n8n stub against real /ingest responses (fixtures.json, produced by the
// pipeline with tests/fakes.py).
//
//   node --test n8n/intake-logging/logging.test.js
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { runEachItem } = require('./n8n-stub.js');
const { applyLogging, body, CHAIN, RETIRED, STAGES, LOGGER_NODES, MATCH_GATE, ADDED_NODES, PLACEHOLDER_ID } = require('./logging-nodes.js');

const DIR = __dirname;
const ROOT = path.join(DIR, '..', '..');
const AFTER = path.join(ROOT, 'Plexa Intake.json');
const BEFORE = path.join(DIR, 'workflow', 'Plexa-Intake.before.json');
const CONTRACT = JSON.parse(fs.readFileSync(path.join(DIR, 'contract.schema.json'), 'utf8'));
const FX = JSON.parse(fs.readFileSync(path.join(DIR, 'fixtures.json'), 'utf8'));

const wf = () => JSON.parse(fs.readFileSync(AFTER, 'utf8'));
const before = () => JSON.parse(fs.readFileSync(BEFORE, 'utf8'));
const node = (w, name) => w.nodes.find(n => n.name === name);
const stage = (name) => STAGES.find(s => s.name === name);

// What the logger's Normalize node would accept without a "malformed" Red.
function assertContract(item, label) {
  const j = item.json;
  CONTRACT.required.forEach(k => assert.ok(j[k] !== undefined && j[k] !== '', label + ' lacks ' + k));
  assert.ok(CONTRACT.properties.status.enum.includes(j.status), label + ' status ' + j.status);
  assert.ok(CONTRACT.properties.severity.enum.includes(j.severity), label + ' severity ' + j.severity);
  assert.ok(j.summary.length <= 300, label + ' summary > 300 chars: ' + j.summary.length);
  assert.strictEqual(typeof j.execution_id, 'string', label);
  assert.ok(!Number.isNaN(Date.parse(j.timestamp)), label + ' timestamp');
  if (j.error) assert.strictEqual(typeof j.error.message, 'string', label + ' error.message');
  if (j.status === 'fail') assert.notStrictEqual(j.severity, 'Green', label + ' a failure can never be Green');
  assert.ok(Object.keys(j.details || {}).length <= 10, label + ' more than 10 detail fields');
  // Nothing an Airtable column is called may be a payload KEY (values are fine).
  Object.keys(j.details || {}).forEach(k => assert.ok(!/[A-Z]/.test(k), label + ' details key looks like a column: ' + k));
  // No secret and no webhook URL may ever ride along.
  const flat = JSON.stringify(j);
  assert.ok(!/hooks\.slack\.com|xoxb-|X-Webhook-Secret/i.test(flat), label + ' leaks a secret or webhook URL');
}

// ───────────────────────────────────────────────────────────────── wiring
test('the shipped Plexa Intake.json is exactly the builder applied to the before export', () => {
  const out = path.join(require('node:os').tmpdir(), 'plexa-intake-logging-check.json');
  execFileSync(process.execPath, [path.join(DIR, 'add-logging-to-export.js'), BEFORE, out], { stdio: 'pipe' });
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(out, 'utf8')), wf());
});

test('every connection target is a real node and no retired node remains', () => {
  const w = wf();
  const names = new Set(w.nodes.map(n => n.name));
  RETIRED.forEach(r => assert.ok(!names.has(r), r + ' should have been retired'));
  for (const [from, outs] of Object.entries(w.connections)) {
    assert.ok(names.has(from), 'connection from unknown node ' + from);
    outs.main.forEach(branch => branch.forEach(c => assert.ok(names.has(c.node), from + ' → unknown node ' + c.node)));
  }
  // The incoming-webhook URL is gone from the workflow altogether.
  assert.ok(!JSON.stringify(w).includes('hooks.slack.com'), 'a Slack incoming webhook URL is still in the workflow');
});

test('every stage log is its vendored Code body, runs per item, and feeds its own Logger node', () => {
  const w = wf();
  for (const s of STAGES) {
    const n = node(w, s.name);
    assert.ok(n, s.name + ' missing');
    assert.strictEqual(n.type, 'n8n-nodes-base.code');
    assert.strictEqual(n.parameters.mode, 'runOnceForEachItem', s.name);
    assert.strictEqual(n.parameters.jsCode, body(s.file), s.name + ' drifted from logging/' + s.file);
    assert.ok(!n.credentials, s.name);
    assert.deepStrictEqual(w.connections[s.name].main[0].map(c => c.node), [s.logger]);
  }
});

test('the logger is called fire-and-forget and can never fail this run', () => {
  const w = wf();
  LOGGER_NODES.forEach(name => {
    const n = node(w, name);
    assert.ok(n, name);
    assert.strictEqual(n.type, 'n8n-nodes-base.executeWorkflow', name);
    assert.strictEqual(n.onError, 'continueRegularOutput', name);
    assert.strictEqual(n.parameters.options.waitForSubWorkflow, false, name);
    assert.strictEqual(n.parameters.workflowId.mode, 'id', name);
    assert.ok(!n.credentials, name);
    assert.deepStrictEqual(w.connections[name], undefined, name + ' must be a leaf');
  });
  const ids = new Set(LOGGER_NODES.map(name => node(w, name).parameters.workflowId.value));
  assert.strictEqual(ids.size, 1);
});

test('each stage hangs off the right outcome', () => {
  const w = wf();
  const c = w.connections;
  // ingest: the intake log takes "Build log"'s place, first, before "Needs attention?"
  assert.deepStrictEqual(c[CHAIN.ingest].main[0].map(x => x.node), ['Log: Intake Result', 'Needs attention?']);
  assert.deepStrictEqual(c[CHAIN.ingest].main[1].map(x => x.node), ['Log: Ingest Failed']);
  assert.strictEqual(node(w, CHAIN.ingest).onError, 'continueErrorOutput');
  // approval declined: log first, Label Processed straight from the IF (not through the log)
  assert.deepStrictEqual(c[CHAIN.approved].main[0].map(x => x.node), ['Gmail Reply'], 'approved path untouched');
  assert.deepStrictEqual(c[CHAIN.approved].main[1].map(x => x.node), ['Log: Reply Declined', 'Label Processed']);
  // approved reply: success path untouched, error → Red
  assert.deepStrictEqual(c[CHAIN.gmailReply].main[0].map(x => x.node), ['Label Processed']);
  assert.deepStrictEqual(c[CHAIN.gmailReply].main[1].map(x => x.node), ['Log: Reply Failed']);
  assert.strictEqual(node(w, CHAIN.gmailReply).onError, 'continueErrorOutput');
  // match hand-off: both outputs into one node
  assert.deepStrictEqual(c[CHAIN.matchPost].main[0].map(x => x.node), ['Log: Hand-off']);
  assert.deepStrictEqual(c[CHAIN.matchPost].main[1].map(x => x.node), ['Log: Hand-off']);
  assert.strictEqual(node(w, CHAIN.matchPost).onError, 'continueErrorOutput');
});

test('the match POST only fires for match-ready leads; not-ready approved leads still close the loop', () => {
  const w = wf();
  const c = w.connections;
  const gate = node(w, MATCH_GATE);
  assert.ok(gate, MATCH_GATE + ' missing');
  assert.strictEqual(gate.type, 'n8n-nodes-base.if');
  const cond = gate.parameters.conditions.conditions;
  assert.strictEqual(cond.length, 1);
  assert.strictEqual(cond[0].leftValue, "={{ $('POST /ingest').item.json.match.ready === true }}");
  assert.deepStrictEqual(cond[0].operator, { type: 'boolean', operation: 'true', singleValue: true });
  // approved → gate → POST; the old direct edge If → HTTP Request is gone
  assert.deepStrictEqual(c[CHAIN.approvedGate].main[0].map(x => x.node), [MATCH_GATE]);
  assert.deepStrictEqual(c[MATCH_GATE].main[0].map(x => x.node), [CHAIN.matchPost]);
  assert.deepStrictEqual(c[MATCH_GATE].main[1].map(x => x.node), ['Log: Hand-off']);
  // nothing else reaches the POST
  const feeders = Object.entries(c).filter(([, o]) => o.main.some(b => b.some(x => x.node === CHAIN.matchPost))).map(([n]) => n);
  assert.deepStrictEqual(feeders, [MATCH_GATE]);
  // the IF before it is untouched (approved check only, as exported)
  assert.deepStrictEqual(node(w, CHAIN.approvedGate).parameters, node(before(), CHAIN.approvedGate).parameters);
});

test('every surviving exported node keeps its id, credentials, position and parameters', () => {
  const b = before(), a = wf();
  const kept = b.nodes.filter(n => !RETIRED.includes(n.name));
  assert.strictEqual(a.nodes.length, kept.length + ADDED_NODES.length);
  for (const bn of kept) {
    const an = node(a, bn.name);
    assert.ok(an, bn.name + ' vanished');
    assert.strictEqual(an.id, bn.id, bn.name + ' id');
    assert.deepStrictEqual(an.credentials, bn.credentials, bn.name + ' credentials');
    assert.deepStrictEqual(an.position, bn.position, bn.name + ' position');
    assert.deepStrictEqual(an.parameters, bn.parameters, bn.name + ' parameters');
    const expectOnError = [CHAIN.ingest, CHAIN.gmailReply, CHAIN.matchPost].includes(bn.name) ? 'continueErrorOutput' : bn.onError;
    assert.strictEqual(an.onError, expectOnError, bn.name + ' onError');
  }
  assert.strictEqual(a.id, b.id);
  assert.deepStrictEqual(a.meta, b.meta);
  assert.deepStrictEqual(a.pinData, b.pinData);
  assert.deepStrictEqual(a.settings, b.settings, 'settings (incl. the existing errorWorkflow) untouched with a placeholder id');
  // Every connection the export had between surviving nodes is still there, in order.
  for (const [from, outs] of Object.entries(b.connections)) {
    if (RETIRED.includes(from)) continue;
    outs.main.forEach((branch, i) => {
      // One edge is re-pointed on purpose: If → HTTP Request becomes If → Match ready? → HTTP Request.
      const was = branch.map(c => c.node).filter(n => !RETIRED.includes(n))
        .map(n => from === CHAIN.approvedGate && i === 0 && n === CHAIN.matchPost ? MATCH_GATE : n);
      const now = (a.connections[from].main[i] || []).map(c => c.node);
      assert.deepStrictEqual(now.filter(n => was.includes(n)), was, from + ' output ' + i);
    });
  }
  // The replacements sit where the retired nodes sat.
  assert.deepStrictEqual(node(a, 'Log: Intake Result').position, node(b, 'Build log').position);
  assert.deepStrictEqual(node(a, 'Logger (intake)').position, node(b, 'Slack log').position);
  assert.deepStrictEqual(node(a, 'Log: Reply Declined').position, node(b, 'Slack declined').position);
});

test('applyLogging is idempotent, keeps ids on a second pass, and wires a real logger id through', () => {
  const once = wf();
  const twice = applyLogging(JSON.parse(JSON.stringify(once)), { idFor: () => 'WRONG' });
  assert.deepStrictEqual(twice, once);
  const withId = applyLogging(JSON.parse(JSON.stringify(once)), { loggerId: 'LOG123', idFor: () => 'WRONG' });
  assert.strictEqual(withId.settings.errorWorkflow, 'LOG123');
  LOGGER_NODES.forEach(n => assert.strictEqual(node(withId, n).parameters.workflowId.value, 'LOG123'));
  assert.strictEqual(node(withId, 'Log: Hand-off').id, node(once, 'Log: Hand-off').id);
  assert.strictEqual(node(once, 'Logger (intake)').parameters.workflowId.value, PLACEHOLDER_ID);
});

test('applyLogging refuses a workflow that is not Plexa Intake', () => {
  assert.throws(() => applyLogging({ nodes: [{ name: 'Sweep', position: [0, 0] }], connections: {} }, { idFor: n => n }),
    /node "Gmail Trigger" not found/);
});

// ─────────────────────────────────────────────────────── the Code bodies
const WORKFLOW = { name: 'Plexa Intake', id: 'SHDoClNVDjqFQtC3' };
const PAYLOAD = (over) => ({ json: Object.assign({
  sender_email: 'jane@example.com', sender_name: 'Jane Doe', subject: 'Looking for a 2BR in Henderson',
  body_html: '<p>hi</p>', body_plain: 'hi', message_id: 'msg-1', thread_id: 'thr-1', is_reply: false,
}, over || {}) });
const run = (name, opts) => runEachItem(body(stage(name).file), { workflow: WORKFLOW, execution: { id: '4471' }, ...opts });
const one = (name, opts) => { const items = run(name, opts); assert.strictEqual(items.length, 1); assertContract(items[0], name); return items[0].json; };
const nodesFor = (fixture, payloadOver) => ({ 'Build payload': [PAYLOAD(payloadOver)], 'POST /ingest': [{ json: FX[fixture] }] });

test('every body embeds the prelude and names the workflow stage it documents', () => {
  for (const s of STAGES) {
    const src = fs.readFileSync(path.join(DIR, 'logging', s.file), 'utf8');
    assert.ok(src.includes('"' + s.name + '"'), s.file + ' header does not name its node');
    assert.ok(body(s.file).startsWith('// ═'), s.file + ' prelude missing');
    assert.ok(src.includes("stage: '" + s.stage + "'"), s.file + ' stage differs from logging-nodes.js');
  }
});

test('Log: Ingest Failed — Red, names the endpoint, carries the HTTP status', () => {
  const j = one('Log: Ingest Failed', {
    nodes: { 'Build payload': [PAYLOAD()] },
    input: [{ json: { error: { message: 'The service was not able to process your request', httpCode: '503' } } }],
  });
  assert.strictEqual(j.stage, 'ingest');
  assert.strictEqual(j.status, 'fail');
  assert.strictEqual(j.severity, 'Red');
  assert.match(j.summary, /POST \/ingest failed for Jane Doe <jane@example.com>/);
  assert.match(j.summary, /not able to process/);
  assert.deepStrictEqual(j.error, { message: 'The service was not able to process your request', node: 'POST /ingest', http_status: 503 });
  assert.strictEqual(j.details.message_id, 'msg-1');
  assert.strictEqual(j.details.endpoint, '/ingest');
});

test('Log: Ingest Failed — a timeout has no status code and still logs', () => {
  const j = one('Log: Ingest Failed', { nodes: { 'Build payload': [PAYLOAD()] }, input: [{ json: { error: { message: 'timeout of 90000ms exceeded' } } }] });
  assert.strictEqual(j.error.http_status, undefined);
  assert.match(j.summary, /timeout of 90000ms/);
});

test('Log: Intake Result — Tier 1 first contact is Green with the reply awaiting approval and match ready', () => {
  const j = one('Log: Intake Result', { nodes: nodesFor('tier1'), input: [{ json: FX.tier1 }] });
  assert.strictEqual(j.stage, 'intake');
  assert.strictEqual(j.severity, 'Green');
  assert.strictEqual(j.status, 'success');
  assert.match(j.summary, /^Tier 1 lead from Jane Doe <jane@example.com> — "Looking for a 2BR in Henderson": reply awaiting approval in Slack; match ready\./);
  assert.strictEqual(j.details.tier, 'Tier 1');
  assert.strictEqual(j.details.reply, 'awaiting approval');
  assert.strictEqual(j.details.match, 'ready');
  assert.match(j.details.location, /Henderson · zip 89052/);
  assert.match(j.details.requirements, /^2BR · up to \$1800\/mo · move-in ASAP$/);
  assert.match(j.details.extraction, /confidence 0\.9/);
  assert.strictEqual(j.details.partner, undefined, 'unknown sender: no partner field');
  assert.strictEqual(j.error, undefined);
});

test('Log: Intake Result — Tier 3 first contact is Green and lists the missing gate fields', () => {
  const j = one('Log: Intake Result', { nodes: nodesFor('tier3'), input: [{ json: FX.tier3 }] });
  assert.strictEqual(j.severity, 'Green');
  assert.match(j.summary, /Tier 3 lead/);
  assert.match(j.summary, /match not ready \(missing: zip_code, move_in_date\)/);
  assert.match(j.details.match, /missing: zip_code, move_in_date/);
});

test('Log: Intake Result — JUNK and duplicates are Green one-liners with no tier', () => {
  const junk = one('Log: Intake Result', { nodes: nodesFor('junk', { sender_email: 'promo@spam.io', sender_name: '', subject: '50% off' }), input: [{ json: FX.junk }] });
  assert.strictEqual(junk.severity, 'Green');
  assert.strictEqual(junk.summary, 'JUNK filtered — <promo@spam.io> — "50% off". Nothing stored, nothing sent.');
  assert.strictEqual(junk.details.tier, undefined);
  assert.strictEqual(junk.details.match, undefined);
  const dup = one('Log: Intake Result', { nodes: nodesFor('duplicate'), input: [{ json: FX.duplicate }] });
  assert.strictEqual(dup.severity, 'Green');
  assert.match(dup.summary, /^Duplicate skipped — Jane Doe <jane@example.com>/);
  assert.strictEqual(dup.details.tier, undefined, 'a duplicate response carries default classification values; never show them as facts');
});

test('Log: Intake Result — Manual Review is Red with the service error', () => {
  const j = one('Log: Intake Result', { nodes: nodesFor('manual_review'), input: [{ json: FX.manual_review }] });
  assert.strictEqual(j.severity, 'Red');
  assert.strictEqual(j.status, 'fail');
  assert.match(j.summary, /^Manual Review — Jane Doe <jane@example.com> — "Looking for a 2BR in Henderson": /);
  assert.match(j.summary, /Labelled Needs Attention/);
  assert.strictEqual(j.error.node, 'POST /ingest');
  assert.ok(j.error.message.length > 0);
  assert.strictEqual(j.details.status, 'Manual Review');
});

test('Log: Intake Result — a follow-up the service will not answer is Yellow and says why', () => {
  const j = one('Log: Intake Result', { nodes: nodesFor('follow_up', { subject: 'Re: Looking for a 2BR in Henderson', is_reply: true }), input: [{ json: FX.follow_up }] });
  assert.strictEqual(j.severity, 'Yellow');
  assert.strictEqual(j.status, 'success');
  assert.match(j.summary, /no auto-reply \(follow-up from a sender already past the gate; lead set to Needs Review for a human\)/);
  assert.strictEqual(j.details.reply, 'skip (follow_up)');
  assert.strictEqual(j.details.status, 'Needs Review');
});

test('Log: Intake Result — the kill switch is Yellow and named', () => {
  const j = one('Log: Intake Result', { nodes: nodesFor('auto_reply_disabled'), input: [{ json: FX.auto_reply_disabled }] });
  assert.strictEqual(j.severity, 'Yellow');
  assert.match(j.summary, /AUTO_REPLY_ENABLED is off \(kill switch\)/);
});

test('Log: Intake Result — a known partner shows up as one field', () => {
  const r = JSON.parse(JSON.stringify(FX.tier1));
  r.partner = { known: true, inventory_tier: 'Full', vendor: 'Acme Relocation', matched_by: 'domain' };
  const j = one('Log: Intake Result', { nodes: { 'Build payload': [PAYLOAD()], 'POST /ingest': [{ json: r }] }, input: [{ json: r }] });
  assert.strictEqual(j.details.partner, 'known · Full · Acme Relocation (by domain)');
});

test('Log: Intake Result — one message per email when a poll delivers several', () => {
  const payloads = [PAYLOAD(), PAYLOAD({ sender_email: 'promo@spam.io', sender_name: '', subject: '50% off', message_id: 'msg-3' })];
  const items = run('Log: Intake Result', { nodes: { 'Build payload': payloads }, input: [{ json: FX.tier1 }, { json: FX.junk }] });
  assert.strictEqual(items.length, 2);
  items.forEach(i => assertContract(i, 'multi'));
  assert.match(items[0].json.summary, /^Tier 1 lead from Jane Doe/);
  assert.match(items[1].json.summary, /^JUNK filtered — <promo@spam.io>/);
});

test('Log: Intake Result — never longer than 300 characters even with a long subject and notes', () => {
  const r = JSON.parse(JSON.stringify(FX.tier1));
  r.extraction.notes = 'x'.repeat(500);
  const j = one('Log: Intake Result', { nodes: { 'Build payload': [PAYLOAD({ subject: 'S'.repeat(400) })], 'POST /ingest': [{ json: r }] }, input: [{ json: r }] });
  assert.ok(j.summary.length <= 300);
  assert.ok(j.details.subject.length <= 80);
});

test('Log: Reply Declined — a click is "declined", no click is "timed out"; both Yellow', () => {
  const clicked = one('Log: Reply Declined', { nodes: nodesFor('tier1'), input: [{ json: { data: { approved: false } } }] });
  assert.strictEqual(clicked.stage, 'approval');
  assert.strictEqual(clicked.severity, 'Yellow');
  assert.strictEqual(clicked.status, 'success');
  assert.match(clicked.summary, /declined in Slack\. Nothing sent; email labelled Processed/);
  assert.strictEqual(clicked.details.outcome, 'declined');
  assert.strictEqual(clicked.details.match, 'was ready (not sent)');
  const timedOut = one('Log: Reply Declined', { nodes: nodesFor('tier1'), input: [{ json: { text: 'the approval message, passed through' } }] });
  assert.match(timedOut.summary, /nobody approved within 24 h/);
  assert.strictEqual(timedOut.details.outcome, 'timed out');
});

test('Log: Reply Failed — Red, names Gmail Reply, says what to do by hand', () => {
  const j = one('Log: Reply Failed', { nodes: nodesFor('tier1'), input: [{ json: { error: 'Invalid grant: account not found' } }] });
  assert.strictEqual(j.stage, 'reply');
  assert.strictEqual(j.severity, 'Red');
  assert.strictEqual(j.status, 'fail');
  assert.match(j.summary, /Approved reply to Jane Doe <jane@example.com> — "Looking for a 2BR in Henderson" was NOT sent: Invalid grant/);
  assert.deepStrictEqual(j.error, { message: 'Invalid grant: account not found', node: 'Gmail Reply' });
  assert.strictEqual(j.details.match, 'ready, not sent');
  assert.match(j.details.action, /Reply from the inbox/);
});

test('Log: Hand-off — match-ready and accepted is Green with the match brief', () => {
  const j = one('Log: Hand-off', { nodes: nodesFor('tier1'), input: [{ json: { success: true } }] });
  assert.strictEqual(j.stage, 'match');
  assert.strictEqual(j.severity, 'Green');
  assert.strictEqual(j.status, 'success');
  assert.match(j.summary, /Reply sent to Jane Doe <jane@example.com> — "Looking for a 2BR in Henderson"; match request handed to Property Matching \(zip 89052, 2BR, move-in 2026-10-20\)\./);
  assert.strictEqual(j.details.match, 'sent');
  assert.strictEqual(j.details.zip_code, '89052');
  assert.strictEqual(String(j.details.bedrooms), '2', 'match.request carries form-shaped strings');
});

test('Log: Hand-off — not match-ready (from "Match ready?" FALSE, a Gmail label item) is Green and says nothing was built', () => {
  const j = one('Log: Hand-off', { nodes: nodesFor('tier3'), input: [{ json: { id: 'msg-2', threadId: 'thr-1', labelIds: ['Label_6663289192800495718'] } }] });
  assert.strictEqual(j.severity, 'Green');
  assert.match(j.summary, /not match-ready \(missing: zip_code, move_in_date\), so no match request was built\./);
  assert.strictEqual(j.details.match, 'none');
  assert.strictEqual(j.details.zip_code, undefined);
});

test('Log: Hand-off — a failed POST to the matching webhook is Red with the status', () => {
  const j = one('Log: Hand-off', { nodes: nodesFor('tier1'), input: [{ json: { error: { message: 'Request failed with status code 404', status: 404 } } }] });
  assert.strictEqual(j.severity, 'Red');
  assert.strictEqual(j.status, 'fail');
  assert.match(j.summary, /but the match request POST to Property Matching failed: Request failed with status code 404\. Submit the match request by hand \(zip 89052/);
  assert.deepStrictEqual(j.error, { message: 'Request failed with status code 404', node: 'HTTP Request', http_status: 404 });
  assert.strictEqual(j.details.match, 'FAILED');
});

test('bodies fall back to the first item when n8n cannot pair, and never throw on an empty upstream', () => {
  // Pairing unavailable: stub throws on .item when the index has no partner; .first() still works.
  const items = runEachItem(body('reply-declined.node.js'), {
    workflow: WORKFLOW, execution: { id: '1' },
    nodes: { 'Build payload': [PAYLOAD()], 'POST /ingest': [{ json: FX.tier1 }] },
    input: [{ json: {} }, { json: {} }],
  });
  assert.strictEqual(items.length, 2);
  items.forEach(i => assert.match(i.json.summary, /Jane Doe/));
  // Upstream never ran: unknown sender, still a valid contract.
  const j = one('Log: Ingest Failed', { nodes: {}, input: [{ json: { error: { message: 'boom' } } }] });
  assert.match(j.summary, /<unknown sender> — "\(no subject\)"/);
});
