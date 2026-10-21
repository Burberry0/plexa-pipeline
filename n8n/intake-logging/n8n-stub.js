'use strict';
// Minimal stand-in for the n8n Code-node runtime so a node body can run under
// `node --test`. Derived from RyanPlexa/pricing-config/n8n-stub.js, extended
// for "Run Once for Each Item" mode, which is what every intake stage log uses:
//
//   $json                                      the current item's json
//   $itemIndex                                 its index
//   $input.item / .all() / .first() / .last()
//   $('Node Name').item                        the PAIRED item: nodes[name][$itemIndex]
//   $('Node Name').first() / .all() / .last()  (+ optional branch index)
//   $execution.id, $workflow.name / .id
//
// nodes[name] may be:
//   [items]                                  output 0 (the common case)
//   { outputs: [out0Items, out1Items] }      several outputs (an error output)
// A node body is the exact string that lives in the node's jsCode parameter.

function outputsOf(spec) {
  if (Array.isArray(spec)) return [spec];
  if (spec && spec.outputs) return spec.outputs;
  return [[spec]];
}

function makeNodeRef(name, spec, itemIndex) {
  if (!spec) {
    const noData = () => { throw new Error(`stub: node "${name}" has no data in this execution`); };
    return { first: noData, all: noData, last: noData, get item() { return noData(); } };
  }
  const outs = outputsOf(spec);
  const get = (branch) => outs[branch || 0] || [];
  const paired = get(0)[itemIndex];
  return {
    first: (b) => get(b)[0],
    all: (b) => get(b),
    last: (b) => { const l = get(b); return l[l.length - 1]; },
    get item() {
      if (!paired) throw new Error(`stub: node "${name}" has no paired item for index ${itemIndex}`);
      return paired;
    },
  };
}

// Runs `code` once per input item, as n8n does in "Run Once for Each Item"
// mode, and returns the items the node would emit (one per input item).
function runEachItem(code, {
  nodes = {}, input = [], execution = { id: 'test-exec' },
  workflow = { name: 'Plexa Intake', id: 'wf-test' }, quiet = true,
} = {}) {
  const logger = quiet ? { log() {}, warn() {}, error() {}, info() {} } : console;
  const out = [];
  input.forEach((item, i) => {
    const $ = (name) => makeNodeRef(name, nodes[name], i);
    const $input = makeNodeRef('$input', input, i);
    // eslint-disable-next-line no-new-func
    const fn = new Function('$', '$input', '$json', '$itemIndex', '$execution', 'console', '$workflow', code);
    const r = fn($, $input, item.json, i, execution, logger, workflow);
    if (r === undefined || r === null) throw new Error('stub: each-item node returned nothing for item ' + i);
    if (Array.isArray(r)) throw new Error('stub: each-item node returned an array for item ' + i + ' (n8n rejects that)');
    out.push(r.json ? r : { json: r });
  });
  return out;
}

module.exports = { runEachItem };
