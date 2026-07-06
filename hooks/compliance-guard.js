'use strict';

// ---------------------------------------------------------------------------
// compliance-guard.js: Claude Code PreToolUse advisory hook
// Cheap heuristics (regex/string), no LLM, no network.
// Prints one-line advisories with framework control IDs.
// Only hard-blocks on secret-egress (same as pii-redact, belt-and-suspenders).
// ---------------------------------------------------------------------------

const { findSecrets, isStructurallyGuarded, WRITE_TOOLS, PII_KEYWORD_RE } = require('./pii_patterns');

// ---------------------------------------------------------------------------
// Control reference map: id -> short label
// Draws from ISO 27001:2022 (A.x.x) and GDPR articles.
// Only the ids in SCORABLE_IDS below exist in frameworks/iso-27001-27701.yaml
// under that exact id; the rest are background references for context and
// are printed with a "(not scored)" suffix so they aren't mistaken for a
// lookup-able control id.
// ---------------------------------------------------------------------------
const CTRL = {
  'ISO27001-A.8.12':  'Data leakage prevention',
  'ISO27001-A.8.20':  'Network security controls',
  'A.8.24-SECRETS':   'Secrets and key management',
  'A.8.25-SECURE-DEV': 'Secure development lifecycle',
  'ISO27001-A.8.3':   'Information access restriction',
  'ISO27001-A.5.10':  'Acceptable use of information assets',
  'GDPR-Art.5.1f':    'Integrity and confidentiality',
  'GDPR-Art.25':      'Data protection by design',
  'GDPR-Art.32':      'Security of processing',
  // ISO 27001:2022 Annex A controls (scorable via iso-27001-27701.yaml):
  'A.5.15-ACCESS':    'Access control',
  'A.8.15-LOGGING':   'Logging',
};

// ids that exist verbatim as `id:` in frameworks/iso-27001-27701.yaml and can
// therefore be scored; everything else in CTRL is advisory-only context.
const SCORABLE_IDS = new Set(['A.5.15-ACCESS', 'A.8.15-LOGGING', 'A.8.24-SECRETS', 'A.8.25-SECURE-DEV']);

function ctrl(id) {
  const label = CTRL[id] || id;
  const suffix = SCORABLE_IDS.has(id) ? '' : ', not scored';
  return `[${id}: ${label}${suffix}]`;
}

// ---------------------------------------------------------------------------
// Module-scope tool-set consts (hoist out of per-call new Set([...]))
// ---------------------------------------------------------------------------
const CMD_TOOLS = new Set(['Bash', 'bash', 'mcp__terminal__send_command', 'computer_use']);

// checkSecretsToRepo needs Write + Edit tools (WRITE_TOOLS from pii_patterns)
// checkSensitiveToTemp needs only the write-creating subset
const TEMP_WRITE_TOOLS = new Set(['Write', 'write_file', 'mcp__filesystem__write_file']);

// ---------------------------------------------------------------------------
// Heuristic checks
// Each returns null (clean) or a { block, message } object.
// ---------------------------------------------------------------------------

// 1. PII or sensitive keywords heading to an external LLM endpoint
const EXTERNAL_LLM_RE = /(?:api\.openai\.com|anthropic\.com\/v\d|generativelanguage\.googleapis|api\.mistral\.ai|api\.cohere\.ai|openrouter\.ai)/i;

function checkPIIToLLM(toolName, toolInput) {
  if (toolName !== 'WebFetch' && toolName !== 'web_fetch') return null;
  const url = toolInput.url || '';
  if (!EXTERNAL_LLM_RE.test(url)) return null;
  const body = JSON.stringify(toolInput.body || toolInput.content || '');
  if (!PII_KEYWORD_RE.test(body)) return null;
  return {
    block: false,
    message: `ADVISORY ${ctrl('GDPR-Art.5.1f')} ${ctrl('ISO27001-A.8.12')}: Possible PII keyword in request body to external LLM endpoint (${url.split('/')[2]}). Verify data minimisation before sending.`,
  };
}

// 2. Logging disabled / audit trail tampered
const LOG_DISABLE_RE = /(?:audit.?log(?:ging)?|event.?log(?:ging)?|CloudTrail|Splunk|Siem)\s*(?:=|:)\s*(?:false|off|disabled|0)|--no-?log|DisableLogging|logging\s*=\s*false/i;

// Cheap guard: only stringify and run LOG_DISABLE_RE if the tool name suggests
// it could carry a config payload (Bash/write tools) or we have no name.
const _LOG_CHECK_TOOLS = new Set([
  'Bash', 'bash', 'mcp__terminal__send_command',
  'Write', 'write_file', 'mcp__filesystem__write_file',
  'Edit', 'edit_file', 'mcp__filesystem__edit_file',
  'WebFetch', 'web_fetch',
]);

function checkLoggingDisabled(toolName, toolInput) {
  if (toolName && !_LOG_CHECK_TOOLS.has(toolName)) return null;
  const payload = JSON.stringify(toolInput);
  if (!LOG_DISABLE_RE.test(payload)) return null;
  return {
    block: false,
    message: `ADVISORY ${ctrl('ISO27001-A.5.10')} ${ctrl('A.8.15-LOGGING')}: Payload appears to disable audit logging. Confirm this is intentional and documented.`,
  };
}

// 3. Secrets about to be written to a version-controlled or public path
const VCS_PATH_RE = /(?:\.git(?:hub)?[/\\]|\.gitlab[/\\]|bitbucket[/\\])/i;
const PUBLIC_PATH_RE = /(?:public[/\\]|www[/\\]|dist[/\\]|build[/\\]|static[/\\])/i;

function checkSecretsToRepo(toolName, toolInput) {
  if (!WRITE_TOOLS.has(toolName)) return null;
  const path = toolInput.file_path || toolInput.path || '';
  if (!VCS_PATH_RE.test(path) && !PUBLIC_PATH_RE.test(path)) return null;
  const content = toolInput.content || toolInput.new_string || '';
  if (!content) return null;
  const secrets = findSecrets(content);
  if (!secrets.length) return null;
  const types = [...new Set(secrets.map((s) => s.type))].join(', ');
  return {
    block: true,
    message: `BLOCKED ${ctrl('A.8.24-SECRETS')} ${ctrl('GDPR-Art.32')}: Secret(s) detected (${types}) about to be written to a VCS or public path (${path}). Remove credentials.`,
  };
}

// 4. Sensitive personal data written to an unencrypted or world-readable path
const UNPROTECTED_PATH_RE = /(?:\/tmp\/|\\Temp\\|\\AppData\\Local\\Temp\\|\/var\/tmp\/)/i;

function checkSensitiveToTemp(toolName, toolInput) {
  if (!TEMP_WRITE_TOOLS.has(toolName)) return null;
  const path = toolInput.file_path || toolInput.path || '';
  if (!UNPROTECTED_PATH_RE.test(path)) return null;
  const content = toolInput.content || '';
  if (!PII_KEYWORD_RE.test(content)) return null;
  return {
    block: false,
    message: `ADVISORY ${ctrl('GDPR-Art.25')} ${ctrl('ISO27001-A.8.3')}: PII keywords detected in content written to a temp/unprotected path (${path}). Prefer encrypted or access-controlled storage.`,
  };
}

// 5. Permission escalation or security control bypass patterns
const PERM_ESCALATION_RE = /(?:chmod\s+[0-7]*7[0-7]{2}|chmod\s+a\+(?:rwx?|w)|sudo\s+chmod|icacls.*\/grant.*Everyone|--no-verify|--skip-hooks|dangerouslyDisableSandbox)/i;

function checkPermEscalation(toolName, toolInput) {
  if (!CMD_TOOLS.has(toolName)) return null;
  const cmd = toolInput.command || toolInput.cmd || '';
  if (!PERM_ESCALATION_RE.test(cmd)) return null;
  return {
    block: false,
    message: `ADVISORY ${ctrl('ISO27001-A.8.3')} ${ctrl('A.5.15-ACCESS')}: Command contains permission escalation or hook-bypass pattern. Confirm this is intended and documented.`,
  };
}

// 6. Data egress to unexpected external hosts via WebFetch POST
const INTERNAL_RE = /^https?:\/\/(?:localhost|127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|::1)/;

function checkExternalPost(toolName, toolInput) {
  if (toolName !== 'WebFetch' && toolName !== 'web_fetch') return null;
  const method = (toolInput.method || 'GET').toUpperCase();
  if (method !== 'POST' && method !== 'PUT' && method !== 'PATCH') return null;
  const url = toolInput.url || '';
  if (INTERNAL_RE.test(url) || EXTERNAL_LLM_RE.test(url)) return null; // LLM handled above
  const body = JSON.stringify(toolInput.body || toolInput.content || '');
  if (body.length < 50) return null;
  return {
    block: false,
    message: `ADVISORY ${ctrl('ISO27001-A.8.20')} ${ctrl('GDPR-Art.32')}: Outbound ${method} to external host (${url.split('/')[2]}). Verify data classification and transfer agreement.`,
  };
}

// ---------------------------------------------------------------------------
// All checks in priority order (block-capable first)
// ---------------------------------------------------------------------------
const CHECKS = [
  checkSecretsToRepo,    // hard block
  checkPIIToLLM,         // advisory
  checkLoggingDisabled,  // advisory
  checkSensitiveToTemp,  // advisory
  checkPermEscalation,   // advisory
  checkExternalPost,     // advisory
];

// Current PreToolUse contract: hookSpecificOutput.permissionDecision is
// "allow" | "deny" | "ask".
function decision(allow, message) {
  const hookSpecificOutput = {
    hookEventName: 'PreToolUse',
    permissionDecision: allow ? 'allow' : 'deny',
  };
  if (message) hookSpecificOutput.permissionDecisionReason = message;
  return { hookSpecificOutput };
}

async function main() {
  let raw = '';
  try {
    for await (const chunk of process.stdin) raw += chunk;
  } catch (e) {
    process.stdout.write(JSON.stringify(decision(true)) + '\n');
    process.stderr.write(`[compliance-guard] stdin error: ${e.message}\n`);
    return;
  }

  let call;
  try {
    call = JSON.parse(raw);
  } catch (e) {
    process.stdout.write(JSON.stringify(decision(true)) + '\n');
    process.stderr.write(`[compliance-guard] JSON parse error: ${e.message}\n`);
    return;
  }

  try {
    const toolName = call.tool_name || call.name || '';
    const toolInput = call.tool_input || call.input || {};

    for (const check of CHECKS) {
      const result = check(toolName, toolInput);
      if (!result) continue;
      if (result.block) {
        process.stdout.write(JSON.stringify(decision(false, result.message)) + '\n');
        return;
      }
      // Advisory: print to stderr (visible in hook output), allow the call
      process.stderr.write(`[compliance-guard] ${result.message}\n`);
    }

    process.stdout.write(JSON.stringify(decision(true)) + '\n');
  } catch (e) {
    // Fail-open on unexpected errors
    process.stderr.write(`[compliance-guard] Unexpected error (fail-open): ${e.message}\n`);
    process.stdout.write(JSON.stringify(decision(true)) + '\n');
  }
}

main();
