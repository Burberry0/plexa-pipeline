'use strict';
/**
 * The Slack-logging additions for the "Plexa Intake" n8n workflow, as one
 * function that applies them to any export of it. Same shape as the other two
 * adopters of the shared logger (RyanPlexa/confirm-send/logging-nodes.js and
 * RyanPlexa/pricing-config/logging-nodes.js); the logger itself is
 * RyanPlexa/n8n-logger/ and its contract is contract.schema.json here.
 *
 * What it does, and nothing else:
 *   1. Five Code nodes build the logger contract (plexa.n8n.log/v1), bodies in
 *      logging/*.node.js, each prefixed with logging/_prelude.js.
 *   2. Five Execute Workflow nodes hand the payloads to "Plexa — Slack Logger",
 *      fire-and-forget (never waits, never fails this run).
 *   3. Three nodes get `onError: continueErrorOutput` so an expected failure
 *      leaves on the error output instead of killing the run:
 *        POST /ingest    → Log: Ingest Failed          (Red)
 *        Gmail Reply     → Log: Reply Failed           (Red)
 *        HTTP Request    → Log: Hand-off, both outputs (Green / Red)
 *   4. The three ad-hoc Slack webhook posts are retired and replaced by logger
 *      calls carrying the same facts:
 *        Build log → Slack log    becomes  Log: Intake Result → Logger (intake)
 *        Slack declined           becomes  Log: Reply Declined → Logger (approval)
 *      After this the only Slack traffic left in the workflow is the
 *      interactive "Approve reply?" bot message. No webhook URL remains.
 *   5. Connections for the above. Every other existing connection is kept.
 *   6. settings.errorWorkflow, only when a real logger id is given; an id the
 *      export already carries is left alone otherwise.
 *   7. One gate fix found while wiring the hand-off log (2026-10-20): the live
 *      export POSTed to Property Matching for EVERY approved reply, including
 *      Tier 3 leads whose `match.request` is null, because the "If" before the
 *      POST checked only `approved`. A "Match ready?" IF now sits between
 *      them: true → "HTTP Request", false → "Log: Hand-off" (Green, "no match
 *      request was built"), which is what docs/n8n-workflow.md node 6d always
 *      described.
 *
 * Stage → message:
 *   POST /ingest error output        → Log: Ingest Failed    Red
 *   POST /ingest success output      → Log: Intake Result    Green / Yellow / Red, every email
 *   Approved? FALSE                  → Log: Reply Declined   Yellow
 *   Gmail Reply error output         → Log: Reply Failed     Red
 *   HTTP Request (matching) outputs  → Log: Hand-off         Green / Red
 *   anything unhandled               → Error Workflow (the logger's Error Trigger)
 *
 * The Code nodes run "once for each item": a Gmail poll can deliver several
 * emails in one execution and each gets its own message.
 */
const fs = require('fs'), path = require('path');

const BODIES = path.join(__dirname, 'logging');
const PRELUDE = fs.readFileSync(path.join(BODIES, '_prelude.js'), 'utf8');
const body = (file) => PRELUDE + '\n' + fs.readFileSync(path.join(BODIES, file), 'utf8');

const LOGGER_WORKFLOW_NAME = 'Plexa — Slack Logger';
const PLACEHOLDER_ID = 'REPLACE_ME';

// Existing nodes the additions hang off. Renaming one of these in n8n breaks
// the build loudly rather than silently logging nothing.
const CHAIN = {
  trigger: 'Gmail Trigger',
  payload: 'Build payload',
  ingest: 'POST /ingest',
  needsAttention: 'Needs attention?',
  approved: 'Approved?',
  gmailReply: 'Gmail Reply',
  labelProcessed: 'Label Processed',
  approvedGate: 'If',
  matchPost: 'HTTP Request',
};

// Nodes this replaces. Optional: absent on a second pass or on a build that
// never had them.
const RETIRED = ['Build log', 'Slack log', 'Slack declined'];

// name → { body file, logger node, stage, where it sits on the canvas }
const STAGES = [
  { name: 'Log: Ingest Failed', file: 'ingest-failed.node.js', logger: 'Logger (ingest)', stage: 'ingest',
    anchor: CHAIN.ingest, offset: [240, 560],
    notes: 'POST /ingest returned an error after 2 tries (401/403 = Plexa Webhook Secret credential, 503 = ' +
      'WEBHOOK_SECRET unset on Vercel, 5xx/timeout = the service). Nothing was classified; the email has ' +
      'no label and will not be re-polled. Red, always.' },
  { name: 'Log: Intake Result', file: 'intake-result.node.js', logger: 'Logger (intake)', stage: 'intake',
    anchor: CHAIN.ingest, offset: [240, -224],
    notes: 'Every processed email, the moment the service answers, in parallel with "Needs attention?". ' +
      'Replaced the old "Build log" → "Slack log" webhook post on 2026-10-20. Red = Manual Review, ' +
      'Yellow = lead the service chose not to answer (follow-up, cooldown, max replies, kill switch), ' +
      'Green = reply awaiting approval, JUNK, duplicate.' },
  { name: 'Log: Reply Declined', file: 'reply-declined.node.js', logger: 'Logger (approval)', stage: 'approval',
    anchor: CHAIN.approved, offset: [256, 176],
    notes: 'Declined in Slack, or the 24 h approval wait ran out. Nothing sent. Replaced the old ' +
      '"Slack declined" webhook post on 2026-10-20. "Label Processed" is reached directly from ' +
      '"Approved?" FALSE, not through this node, so a logging fault can never leave an email unlabelled. Yellow.' },
  { name: 'Log: Reply Failed', file: 'reply-failed.node.js', logger: 'Logger (reply)', stage: 'reply',
    anchor: CHAIN.gmailReply, offset: [256, -176],
    notes: 'Gmail refused to send an APPROVED reply. The success path (Label Processed → match hand-off) ' +
      'does not run for this item, so nothing downstream pretends it was sent. Red: someone approved an ' +
      'answer that never left.' },
  { name: 'Log: Hand-off', file: 'hand-off.node.js', logger: 'Logger (match)', stage: 'match',
    anchor: CHAIN.matchPost, offset: [240, 0],
    notes: 'End of an approved lead: fed by BOTH outputs of "HTTP Request" (the POST to Property Matching). ' +
      'Green: reply sent and match request accepted, or nothing to match. Red: the POST failed — the ' +
      'requester was promised a match that never started. Property Matching logs its own stages after this.' },
];
const LOGGER_NODES = STAGES.map(s => s.logger);
const MATCH_GATE = 'Match ready?';
const ADDED_NODES = STAGES.map(s => s.name).concat(LOGGER_NODES, MATCH_GATE);

// The gate between "If" (approved) and the POST to Property Matching. The
// service builds `match.request` only when zip, bedrooms and move-in are all
// known; before this node the POST went out with a null body for every
// approved Tier 3 lead.
function matchGateNode({ idFor, positionOf }) {
  const [ix, iy] = positionOf(CHAIN.matchPost);
  return {
    parameters: {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 3 },
        conditions: [{
          id: 'match-ready',
          leftValue: "={{ $('POST /ingest').item.json.match.ready === true }}",
          rightValue: '',
          operator: { type: 'boolean', operation: 'true', singleValue: true },
        }],
        combinator: 'and',
      },
      options: {},
    },
    id: idFor(MATCH_GATE),
    name: MATCH_GATE,
    type: 'n8n-nodes-base.if',
    typeVersion: 2.3,
    position: [ix - 32, iy + 192],
    notes: 'Added 2026-10-20 by n8n/intake-logging. Only approved leads reach here (the "If" before it). ' +
      'TRUE: match.request exists → POST to Property Matching. FALSE: Tier 3, nothing to match → ' +
      '"Log: Hand-off" still posts the Green "reply sent, no match request was built". Before this ' +
      'node every approved reply POSTed, with a null body for Tier 3.',
    notesInFlow: true,
  };
}

function loggingNodes({ loggerId, idFor, positionOf }) {
  const N = (name, type, typeVersion, position, parameters, extra) =>
    Object.assign({ parameters, id: idFor(name), name, type, typeVersion, position }, extra || {});

  const codeNode = (name, position, file, notes) =>
    N(name, 'n8n-nodes-base.code', 2, position, { mode: 'runOnceForEachItem', jsCode: body(file) }, {
      notes: 'GENERATED — do not edit here. Source: n8n/intake-logging/logging/' + file +
        ' (+ _prelude.js)\n\n' + notes,
      notesInFlow: true,
    });

  // Fire-and-forget. `waitForSubWorkflow:false` means a slow or failing logger
  // never holds up or fails this run; `continueRegularOutput` covers the node
  // itself erroring (unknown id, logger deactivated).
  const callLogger = (name, position) =>
    N(name, 'n8n-nodes-base.executeWorkflow', 1.2, position, {
      workflowId: { __rl: true, mode: 'id', value: loggerId },
      options: { waitForSubWorkflow: false },
    }, {
      notes: 'Shared logger: "' + LOGGER_WORKFLOW_NAME + '" (RyanPlexa/n8n-logger/). If this shows ' +
        PLACEHOLDER_ID + ', pick the logger from the list once after import, or rebuild with ' +
        'N8N_LOGGER_WORKFLOW_ID set. Fire-and-forget: a logger failure never fails this run.',
      notesInFlow: true,
      onError: 'continueRegularOutput',
    });

  const nodes = [];
  for (const s of STAGES) {
    const [ax, ay] = positionOf(s.anchor);
    const at = [ax + s.offset[0], ay + s.offset[1]];
    nodes.push(codeNode(s.name, at, s.file, s.notes), callLogger(s.logger, [at[0] + 240, at[1]]));
  }
  return nodes;
}

const to = name => ({ node: name, type: 'main', index: 0 });
const without = (list, names) => (list || []).filter(x => !names.includes(x.node));

/**
 * Mutates `workflow` in place and returns it. Idempotent: running it on a
 * workflow that already carries the logging nodes replaces them (by name) and
 * leaves everything else alone.
 */
function applyLogging(workflow, { loggerId = PLACEHOLDER_ID, idFor } = {}) {
  if (typeof idFor !== 'function') throw new Error('applyLogging: idFor(name) is required');
  const byName = name => workflow.nodes.find(n => n.name === name);
  for (const name of Object.values(CHAIN)) {
    if (!byName(name)) throw new Error('applyLogging: node "' + name + '" not found — is this the Plexa Intake workflow?');
  }

  // 1. error outputs on the three calls whose failure is expected and actionable
  byName(CHAIN.ingest).onError = 'continueErrorOutput';
  byName(CHAIN.gmailReply).onError = 'continueErrorOutput';
  byName(CHAIN.matchPost).onError = 'continueErrorOutput';

  // 2. nodes: drop the retired webhook posts, replace any previous copy of the
  //    additions by name (keeping its id if it had one)
  const retiredPositions = {};
  for (const name of RETIRED) if (byName(name)) retiredPositions[name] = byName(name).position;
  const existing = workflow.nodes.filter(n => !ADDED_NODES.includes(n.name) && !RETIRED.includes(n.name));
  const keepId = name => (byName(name) && byName(name).id) || idFor(name);
  const positionOf = name => byName(name).position;
  const additions = loggingNodes({ loggerId, idFor: keepId, positionOf })
    .concat(matchGateNode({ idFor: keepId, positionOf }));
  // The replacements take the retired nodes' places on the canvas when those exist.
  const seat = (name, retired) => { if (retiredPositions[retired]) additions.find(n => n.name === name).position = retiredPositions[retired]; };
  seat('Log: Intake Result', 'Build log');
  seat('Logger (intake)', 'Slack log');
  seat('Log: Reply Declined', 'Slack declined');
  if (retiredPositions['Slack declined']) {
    const [x, y] = retiredPositions['Slack declined'];
    additions.find(n => n.name === 'Logger (approval)').position = [x + 240, y];
  }
  workflow.nodes = existing.concat(additions);

  // 3. connections — every surviving existing connection stays exactly as it is
  const c = workflow.connections;
  for (const name of RETIRED.concat(ADDED_NODES)) delete c[name];
  const main = (name) => (c[name] = c[name] || { main: [] }).main;
  const output = (name, i) => { const m = main(name); while (m.length <= i) m.push([]); return m[i]; };

  // ingest: success → the intake log where "Build log" used to be (first, before
  // "Needs attention?", so the channel hears about the email before anything
  // else runs); error → the Red
  main(CHAIN.ingest)[0] = [to('Log: Intake Result')].concat(without(output(CHAIN.ingest, 0), ['Build log', 'Log: Intake Result']));
  main(CHAIN.ingest)[1] = [to('Log: Ingest Failed')];
  // approval declined: log first, then straight on to Label Processed
  const declined = without(output(CHAIN.approved, 1), ['Slack declined', 'Log: Reply Declined', CHAIN.labelProcessed]);
  main(CHAIN.approved)[1] = [to('Log: Reply Declined')].concat(declined, to(CHAIN.labelProcessed));
  // approved reply: success path untouched; error → the Red
  main(CHAIN.gmailReply)[1] = [to('Log: Reply Failed')];
  // approved → Match ready? → (true) POST to matching / (false) hand-off log.
  // "If" used to feed "HTTP Request" directly; that edge is re-pointed.
  main(CHAIN.approvedGate)[0] = output(CHAIN.approvedGate, 0).map(x => x.node === CHAIN.matchPost ? to(MATCH_GATE) : x);
  if (!main(CHAIN.approvedGate)[0].some(x => x.node === MATCH_GATE)) main(CHAIN.approvedGate)[0].push(to(MATCH_GATE));
  c[MATCH_GATE] = { main: [[to(CHAIN.matchPost)], [to('Log: Hand-off')]] };
  // match hand-off: both outputs close the loop in one node
  main(CHAIN.matchPost)[0] = without(output(CHAIN.matchPost, 0), ['Log: Hand-off']).concat(to('Log: Hand-off'));
  main(CHAIN.matchPost)[1] = [to('Log: Hand-off')];

  for (const s of STAGES) c[s.name] = { main: [[to(s.logger)]] };

  // 4. unhandled crashes → the logger's Error Trigger. Only with a real id:
  // n8n would otherwise look up a workflow called REPLACE_ME at the worst
  // possible moment. An id the export already has is kept as it is.
  workflow.settings = workflow.settings || {};
  if (loggerId !== PLACEHOLDER_ID) workflow.settings.errorWorkflow = loggerId;

  return workflow;
}

module.exports = { applyLogging, loggingNodes, body, CHAIN, RETIRED, STAGES, LOGGER_NODES, MATCH_GATE, ADDED_NODES, PLACEHOLDER_ID, LOGGER_WORKFLOW_NAME };
