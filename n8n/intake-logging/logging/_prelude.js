// ═══════════════════════════════════════════════════════════════════════════
// Shared helpers, prepended to every Code body in this folder by
// logging-nodes.js. Not a node on its own.
//
// All five intake stage logs run in "Run Once for Each Item" mode: a Gmail
// poll can deliver several emails in one execution and every one of them gets
// its own message. `$json` is the current item; `$('Build payload').item` is
// the email it came from (paired item, which n8n keeps across HTTP Request and
// Gmail error outputs).
// ═══════════════════════════════════════════════════════════════════════════
function str(v) { return v === null || v === undefined ? '' : String(v); }
function has(v) { return v !== null && v !== undefined && str(v).trim() !== ''; }
function clip(s, n) { s = str(s); return s.length <= n ? s : s.slice(0, n - 1) + '…'; }
function compact(o) { const out = {}; for (const k of Object.keys(o)) if (has(o[k])) out[k] = o[k]; return out; }

// Paired item first; the first item of that node when pairing is unavailable
// (a manual run with pinned data, or an item n8n could not trace); {} when the
// node never ran in this execution.
function pairedJson(name) {
  try { const j = $(name).item.json; if (j) return j; } catch (e) { /* fall through */ }
  try { return $(name).first().json || {}; } catch (e) { return {}; }
}

// The n8n error-output item shape is { error: { message, httpCode|status|statusCode, … } }
// for HTTP Request and { error: "message" } for Gmail. Read both.
function errMessage(j) {
  const e = j && j.error;
  if (typeof e === 'string') return e;
  if (e && typeof e === 'object') return str(e.message || e.description || JSON.stringify(e));
  return e ? str(e) : '';
}
function httpStatus(j) {
  const e = j && j.error;
  const s = e && typeof e === 'object' ? (e.httpCode || e.status || e.statusCode) : undefined;
  const n = Number(s);
  return Number.isInteger(n) && n >= 100 && n <= 599 ? n : undefined;
}

// "Jane Doe <jane@example.com>" / "<jane@example.com>", from the Build payload item.
function who(p) {
  const email = str(p.sender_email || 'unknown sender');
  return (has(p.sender_name) ? str(p.sender_name).trim() + ' ' : '') + '<' + email + '>';
}
function subjectOf(p) { return has(p.subject) ? clip(str(p.subject).trim(), 80) : '(no subject)'; }

// One contract item (plexa.n8n.log/v1). `stage`, `status`, `severity`,
// `summary` are required; `details` and `error` optional.
function contract(fields) {
  const out = {
    workflow_name: $workflow.name,
    workflow_id: $workflow.id,
    execution_id: String($execution.id),
    stage: fields.stage,
    status: fields.status,
    severity: fields.severity,
    summary: clip(fields.summary, 300),
    details: compact(fields.details || {}),
    timestamp: new Date().toISOString(),
  };
  if (fields.error && has(fields.error.message)) out.error = fields.error;
  return { json: out };
}
