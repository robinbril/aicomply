'use strict';

// ---------------------------------------------------------------------------
// pii-redact.js: Claude Code PreToolUse hook
// Reads a JSON tool-call from stdin, writes a decision to stdout.
// Fail-OPEN on internal errors (never blocks on hook bug).
// Fail-CLOSED only on detected raw secrets/credentials about to leave machine.
// ---------------------------------------------------------------------------

const { redact, findSecrets, isOutwardTool, WRITE_TOOLS } = require('./pii_patterns');

// Cloud-synced path patterns (OneDrive, Dropbox, Google Drive on Windows)
const CLOUD_PATH_RE = /(?:OneDrive|Dropbox|Google\s*Drive|iCloudDrive)[/\\]/i;

function isCloudPath(toolInput) {
  const path = toolInput.file_path || toolInput.path || '';
  return CLOUD_PATH_RE.test(path);
}

// Extract all string payload fields from a tool input object (recursively, depth-limited)
function extractStrings(obj, depth = 0) {
  if (depth > 5) return [];
  if (typeof obj === 'string') return [obj];
  if (Array.isArray(obj)) return obj.flatMap((v) => extractStrings(v, depth + 1));
  if (obj && typeof obj === 'object') {
    return Object.values(obj).flatMap((v) => extractStrings(v, depth + 1));
  }
  return [];
}

// Replace a value within a nested object/array (shallow path-based, returns new copy)
function redactInputFields(input) {
  const allHits = [];

  function walk(obj) {
    if (typeof obj === 'string') {
      const { redacted, hits } = redact(obj);
      allHits.push(...hits);
      return redacted;
    }
    if (Array.isArray(obj)) return obj.map(walk);
    if (obj && typeof obj === 'object') {
      const out = {};
      for (const [k, v] of Object.entries(obj)) {
        out[k] = walk(v);
      }
      return out;
    }
    return obj;
  }

  const redactedInput = walk(input);
  return { redactedInput, allHits };
}

// Current PreToolUse contract: hookSpecificOutput.permissionDecision is
// "allow" | "deny" | "ask"; updatedInput supplies a mutated tool input.
function decision(allow, message, modifiedInput) {
  const hookSpecificOutput = {
    hookEventName: 'PreToolUse',
    permissionDecision: allow ? 'allow' : 'deny',
  };
  if (message) hookSpecificOutput.permissionDecisionReason = message;
  if (modifiedInput !== undefined) hookSpecificOutput.updatedInput = modifiedInput;
  return { hookSpecificOutput };
}

async function main() {
  let raw = '';
  try {
    for await (const chunk of process.stdin) raw += chunk;
  } catch (e) {
    process.stdout.write(JSON.stringify(decision(true)) + '\n');
    process.stderr.write(`[pii-redact] stdin read error: ${e.message}\n`);
    return;
  }

  let call;
  try {
    call = JSON.parse(raw);
  } catch (e) {
    process.stdout.write(JSON.stringify(decision(true)) + '\n');
    process.stderr.write(`[pii-redact] JSON parse error: ${e.message}\n`);
    return;
  }

  try {
    const toolName = call.tool_name || call.name || '';
    const toolInput = call.tool_input || call.input || {};

    // isOutwardTool covers exact Set members + pattern-based send tools
    // (see pii_patterns.js for the source of truth used by install.md globs)
    const isOutward = isOutwardTool(toolName);
    const isCloudWrite = WRITE_TOOLS.has(toolName) && isCloudPath(toolInput);

    if (!isOutward && !isCloudWrite) {
      process.stdout.write(JSON.stringify(decision(true)) + '\n');
      return;
    }

    // Hard block: raw secrets detected anywhere in the payload
    const allStrings = extractStrings(toolInput);
    const combinedPayload = allStrings.join('\n');
    const secretHits = findSecrets(combinedPayload);
    if (secretHits.length) {
      const types = [...new Set(secretHits.map((h) => h.type))].join(', ');
      process.stdout.write(
        JSON.stringify(decision(false,
          `[pii-redact] BLOCKED: raw secret(s) detected in outbound payload (${types}). Remove credentials before sending.`
        )) + '\n'
      );
      return;
    }

    // Redact PII from payload
    const { redactedInput, allHits } = redactInputFields(toolInput);

    if (allHits.length) {
      const summary = allHits.map((h) => `${h.type}:${h.count}`).join(', ');
      process.stderr.write(`[pii-redact] Redacted PII in ${toolName}: ${summary}\n`);
      process.stdout.write(
        JSON.stringify(decision(true,
          `PII redacted (${summary})`,
          redactedInput
        )) + '\n'
      );
      return;
    }

    process.stdout.write(JSON.stringify(decision(true)) + '\n');
  } catch (e) {
    // Fail-open: log and allow on unexpected internal error
    process.stderr.write(`[pii-redact] Unexpected error (fail-open): ${e.message}\n`);
    process.stdout.write(JSON.stringify(decision(true)) + '\n');
  }
}

main();
