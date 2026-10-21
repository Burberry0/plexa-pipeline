#!/usr/bin/env node
'use strict';
/**
 * Adds the Slack logging steps to a LIVE n8n export of the Plexa Intake
 * workflow, keeping everything that makes it that workflow: its id, versionId,
 * meta.instanceId, every node's id and bound credentials, pinData, positions.
 * Importing the result INTO the open workflow (… → Import from File) then
 * updates it in place instead of creating a second copy with unbound
 * credentials.
 *
 *   node n8n/intake-logging/add-logging-to-export.js <export.json> [out.json]
 *   N8N_LOGGER_WORKFLOW_ID=<id> node n8n/intake-logging/add-logging-to-export.js <export.json> [out.json]
 *
 * Default output: next to the input, with " + logging" before the extension.
 * Pass the input path again as out.json to rewrite it in place. Re-running on
 * an output is safe: the additions are replaced by name.
 */
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const { applyLogging, PLACEHOLDER_ID, RETIRED, LOGGER_NODES } = require('./logging-nodes.js');

const [,, inPath, outArg] = process.argv;
if (!inPath) {
  console.error('usage: add-logging-to-export.js <export.json> [out.json]');
  process.exit(2);
}
const loggerId = process.env.N8N_LOGGER_WORKFLOW_ID || PLACEHOLDER_ID;
const outPath = outArg || inPath.replace(/(\.json)?$/i, ' + logging.json');

const workflow = JSON.parse(fs.readFileSync(inPath, 'utf8'));

// Live exports use UUID node ids. New nodes get a stable UUID-shaped id
// derived from the name, so re-running on a fresh export yields the same ids.
const uuidFor = name => {
  const h = crypto.createHash('md5').update('plexa-intake-logging:' + name).digest('hex');
  return [h.slice(0, 8), h.slice(8, 12), '4' + h.slice(13, 16), '8' + h.slice(17, 20), h.slice(20, 32)].join('-');
};

const before = {
  id: workflow.id, instanceId: workflow.meta && workflow.meta.instanceId,
  errorWorkflow: workflow.settings && workflow.settings.errorWorkflow,
  pinData: JSON.stringify(workflow.pinData || null),
  nodes: workflow.nodes.filter(n => !RETIRED.includes(n.name))
    .map(n => [n.name, n.id, JSON.stringify(n.credentials || null)]),
  retired: workflow.nodes.filter(n => RETIRED.includes(n.name)).map(n => n.name),
};

applyLogging(workflow, { loggerId, idFor: uuidFor });

// Nothing that existed may have lost its id or credentials.
for (const [name, nid, creds] of before.nodes) {
  const n = workflow.nodes.find(x => x.name === name);
  if (!n || n.id !== nid || JSON.stringify(n.credentials || null) !== creds) {
    throw new Error('refusing to write: "' + name + '" changed id or credentials');
  }
}
if (workflow.id !== before.id || (workflow.meta && workflow.meta.instanceId) !== before.instanceId) {
  throw new Error('refusing to write: workflow id or instanceId changed');
}
if (JSON.stringify(workflow.pinData || null) !== before.pinData) {
  throw new Error('refusing to write: pinData changed');
}

fs.writeFileSync(outPath, JSON.stringify(workflow, null, 2) + '\n');
const added = workflow.nodes.length - before.nodes.length;
console.log('  wrote  ' + outPath);
console.log('         ' + workflow.nodes.length + ' nodes (' + before.nodes.length + ' kept, ' + added + ' added' +
  (before.retired.length ? ', retired: ' + before.retired.join(', ') : '') + ')');
console.log('         workflow id ' + workflow.id + ' · logger id ' + loggerId +
  (loggerId === PLACEHOLDER_ID
    ? '  ← pick "Plexa — Slack Logger" on the ' + LOGGER_NODES.length + ' Logger nodes after import' +
      (before.errorWorkflow ? '; Settings → Error Workflow kept as ' + before.errorWorkflow : '; set Settings → Error Workflow')
    : ' · Settings → Error Workflow set to it'));
