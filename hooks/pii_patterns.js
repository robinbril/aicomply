'use strict';

// ---------------------------------------------------------------------------
// pii_patterns.js: regex/util library for PII + secret detection/redaction
// No network, no LLM. Pure deterministic regex only.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Shared tool sets (single source of truth; import instead of duplicating)
// ---------------------------------------------------------------------------

// Tools that route data outward (send to external services or other sessions).
// NOTE: the install.md hook matcher uses globs like mcp__ms365__send.*  — any
// new send-style tool that matches those globs will trigger the hook but will
// only pass the PII check if isOutwardTool() covers it. Keep isOutwardTool()
// in sync with the matcher when adding new send tools.
const OUTWARD_TOOLS = new Set([
  'WebFetch',
  'web_fetch',
  // MS365 outbound mail
  'mcp__ms365__send-mail',
  'mcp__ms365__send-draft-message',
  'mcp__ms365__create-draft-email',
  'mcp__ms365__reply-mail-message',
  'mcp__ms365__reply-all-mail-message',
  'mcp__ms365__forward-mail-message',
  'SendMessage',
  'send_message',
  // Slack
  'mcp__slack__post_message',
  'mcp__slack__send_message',
]);

// Tools that write files (union of all inline sets from compliance-guard.js).
const WRITE_TOOLS = new Set([
  'Write',
  'write_file',
  'mcp__filesystem__write_file',
  'Edit',
  'edit_file',
  'mcp__filesystem__edit_file',
]);

// ---------------------------------------------------------------------------
// isOutwardTool: safe outward-tool check used by pii-redact.js.
// Matches exact Set members AND pattern-based send tools not yet in the Set
// (covering the glob mcp__ms365__send.* and similar patterns used in install.md).
// ---------------------------------------------------------------------------
const _OUTWARD_PATTERN = /__send|send-?mail|slack.*post|mcp__.*__send/i;

function isOutwardTool(name) {
  return OUTWARD_TOOLS.has(name) || _OUTWARD_PATTERN.test(name);
}

// ---------------------------------------------------------------------------
// Structural guards: these patterns must NOT trigger PII matches
// ---------------------------------------------------------------------------
const STRUCTURAL_GUARDS = [
  // UUID v1-v5  (8-4-4-4-12 hex)
  /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i,
  // ISO 8601 date/datetime (YYYY-MM-DD[T...])
  /\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:[Z]|[+-]\d{2}:?\d{2})?)?\b/,
  // URL (anything with a scheme)
  /https?:\/\/\S+/i,
  // Bearer tokens / Authorization headers
  /Bearer\s+\S+/i,
  // JWT (three base64url segments)
  /\bey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/,
  // API-key prefixes
  /\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{10,})\b/,
  // Long hex run >= 32 chars (API key / hash)
  /\b[0-9a-f]{32,}\b/i,
  // Long base64 run >= 32 printable chars without spaces (e.g. RSA key material)
  /[A-Za-z0-9+/]{32,}={0,2}/,
];

function isStructurallyGuarded(value) {
  return STRUCTURAL_GUARDS.some((re) => re.test(value));
}

// ---------------------------------------------------------------------------
// BSN  (Dutch citizen service number, 9 digits, 11-proef)
// ---------------------------------------------------------------------------
function isBSN(digits) {
  if (digits.length !== 9) return false;
  // first digit must be > 0 for valid BSN
  if (digits[0] === '0') return false;
  let sum = 0;
  for (let i = 0; i < 9; i++) {
    const weight = i === 8 ? -1 : 9 - i;
    sum += weight * parseInt(digits[i], 10);
  }
  return sum > 0 && sum % 11 === 0;
}

// Match 9 consecutive digits that are NOT part of a longer digit string
// and NOT inside a UUID/date/URL context (structural guard applied separately)
const BSN_RE = /(?<!\d)(\d{9})(?!\d)/g;

function findBSNs(text) {
  const hits = [];
  let m;
  BSN_RE.lastIndex = 0;
  while ((m = BSN_RE.exec(text)) !== null) {
    const digits = m[1];
    // Guard: reject if the surrounding 30-char window contains a UUID/date/URL
    const window = text.slice(Math.max(0, m.index - 10), m.index + 19);
    if (isStructurallyGuarded(window)) continue;
    if (isBSN(digits)) hits.push({ value: digits, index: m.index });
  }
  return hits;
}

// ---------------------------------------------------------------------------
// Credit card  (Luhn check, 13-19 digits, optional spaces/hyphens as separators)
// ---------------------------------------------------------------------------
function luhn(digits) {
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let n = parseInt(digits[i], 10);
    if (alt) { n *= 2; if (n > 9) n -= 9; }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

// Matches card-like sequences: 13-19 digits optionally grouped by spaces or hyphens
const CC_RE = /\b(\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{1,7}|\d{13,19})\b/g;

function findCards(text) {
  const hits = [];
  let m;
  CC_RE.lastIndex = 0;
  while ((m = CC_RE.exec(text)) !== null) {
    const digits = m[1].replace(/[\s-]/g, '');
    if (digits.length < 13 || digits.length > 19) continue;
    const window = text.slice(Math.max(0, m.index - 10), m.index + m[1].length + 10);
    if (isStructurallyGuarded(window)) continue;
    if (luhn(digits)) hits.push({ value: m[1], index: m.index });
  }
  return hits;
}

// ---------------------------------------------------------------------------
// IBAN  (basic structure check: country code + 2 check digits + up to 30 chars)
// ---------------------------------------------------------------------------
const IBAN_RE = /\b([A-Z]{2}\d{2}[A-Z0-9]{4,30})\b/g;

function ibanMod97(iban) {
  const rearranged = iban.slice(4) + iban.slice(0, 4);
  const numeric = rearranged.split('').map((c) =>
    c >= 'A' && c <= 'Z' ? (c.charCodeAt(0) - 55).toString() : c
  ).join('');
  let remainder = 0;
  for (const ch of numeric) {
    remainder = (remainder * 10 + parseInt(ch, 10)) % 97;
  }
  return remainder === 1;
}

function findIBANs(text) {
  const hits = [];
  let m;
  IBAN_RE.lastIndex = 0;
  while ((m = IBAN_RE.exec(text)) !== null) {
    const candidate = m[1];
    if (ibanMod97(candidate)) hits.push({ value: candidate, index: m.index });
  }
  return hits;
}

// ---------------------------------------------------------------------------
// Email
// ---------------------------------------------------------------------------
const EMAIL_RE = /\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b/g;

function findEmails(text) {
  const hits = [];
  let m;
  EMAIL_RE.lastIndex = 0;
  while ((m = EMAIL_RE.exec(text)) !== null) {
    hits.push({ value: m[0], index: m.index });
  }
  return hits;
}

// ---------------------------------------------------------------------------
// Phone  (NL: 06-XXXXXXXX, +31 variants; international E.164 +XX... 7-15 digits)
// ---------------------------------------------------------------------------
// Leading (?<!\d) on each branch keeps the matcher from biting into a longer
// plain numeric ID (e.g. "200000003"), which would corrupt it to "2[REDACTED:phone]".
const PHONE_RE = /(?<!\d)(?:\+\d{1,3}[\s\-]?)?(?:\(0\d{1,4}\)|0\d{1,4})[\s\-]?\d{3,4}[\s\-]?\d{3,4}(?:\s*(?:ext|x)\s*\d{1,6})?|(?<!\d)\+\d{7,15}\b/g;

function findPhones(text) {
  const hits = [];
  let m;
  PHONE_RE.lastIndex = 0;
  while ((m = PHONE_RE.exec(text)) !== null) {
    const raw = m[0];
    const digits = raw.replace(/\D/g, '');
    if (digits.length < 7 || digits.length > 15) continue;
    // Reject a match that sits inside a longer digit run (a plain numeric id),
    // not a phone number. The match must not be flanked by digits on either side.
    const before = m.index > 0 ? text[m.index - 1] : '';
    const after = text[m.index + raw.length] || '';
    if (/\d/.test(before) || /\d/.test(after)) continue;
    const window = text.slice(Math.max(0, m.index - 5), m.index + raw.length + 5);
    if (isStructurallyGuarded(window)) continue;
    hits.push({ value: raw, index: m.index });
  }
  return hits;
}

// ---------------------------------------------------------------------------
// Secret patterns (high-confidence credentials)
// Pre-compiled once at module load for efficiency.
// ---------------------------------------------------------------------------
const SECRET_PATTERNS = [
  { type: 'openai_key',    re: /\bsk-[A-Za-z0-9]{20,}\b/g },
  { type: 'github_token',  re: /\bghp_[A-Za-z0-9]{36,}\b/g },
  { type: 'aws_key',       re: /\bAKIA[A-Z0-9]{16}\b/g },
  { type: 'slack_token',   re: /\bxox[baprs]-[A-Za-z0-9\-]{10,}\b/g },
  { type: 'jwt',           re: /\bey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g },
  { type: 'bearer_token',  re: /Bearer\s+([A-Za-z0-9._~+/\-]{16,})/gi },
];

function findSecrets(text) {
  const hits = [];
  for (const { type, re } of SECRET_PATTERNS) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      hits.push({ type, value: m[0], index: m.index });
    }
  }
  return hits;
}

// ---------------------------------------------------------------------------
// redact(text) -> { redacted: string, hits: [{type, count}] }
// ---------------------------------------------------------------------------
function redact(text) {
  if (typeof text !== 'string') return { redacted: text, hits: [] };

  const counts = {};
  function replace(t, finder, label, replacement) {
    const found = finder(t);
    if (!found.length) return t;
    counts[label] = (counts[label] || 0) + found.length;
    // Replace from back to front to preserve indices
    let result = t;
    for (let i = found.length - 1; i >= 0; i--) {
      const { value, index } = found[i];
      result = result.slice(0, index) + replacement + result.slice(index + value.length);
    }
    return result;
  }

  let out = text;
  // Secrets first (before other redactions shift indices)
  const secretHits = findSecrets(out);
  if (secretHits.length) {
    for (let i = secretHits.length - 1; i >= 0; i--) {
      const { type, value, index } = secretHits[i];
      counts[type] = (counts[type] || 0) + 1;
      out = out.slice(0, index) + `[REDACTED:${type}]` + out.slice(index + value.length);
    }
  }
  // Order matters: the phone matcher is the greediest digit-eater, so structured
  // numerics (IBAN, card, BSN) must be redacted to their full span BEFORE phones.
  // Otherwise findPhones nibbles an IBAN's trailing digits and corrupts the value.
  out = replace(out, findEmails, 'email', '[REDACTED:email]');
  out = replace(out, findIBANs, 'iban', '[REDACTED:iban]');
  out = replace(out, findCards, 'credit_card', '[REDACTED:credit_card]');
  out = replace(out, findBSNs, 'bsn', '[REDACTED:bsn]');
  out = replace(out, findPhones, 'phone', '[REDACTED:phone]');

  const hits = Object.entries(counts).map(([type, count]) => ({ type, count }));
  return { redacted: out, hits };
}

// ---------------------------------------------------------------------------
// flagNames(text) -> string[]  (warns only; does NOT redact)
// Heuristic: capitalized word pairs not at sentence start, excluding known
// stop words and common non-name patterns.
// ---------------------------------------------------------------------------
const NAME_STOP = new Set([
  'The','A','An','This','That','These','Those','It','He','She','They','We',
  'I','You','Me','Him','Her','Us','Them','My','Your','His','Its','Our',
  'January','February','March','April','May','June','July','August',
  'September','October','November','December','Monday','Tuesday','Wednesday',
  'Thursday','Friday','Saturday','Sunday','API','URL','HTTP','HTTPS','JSON',
  'XML','SQL','UUID','ID','OK','EU','NL','DE','EN',
]);

const NAME_PAIR_RE = /(?<![.!?]\s)(?<![.!?]\t)\b([A-Z][a-z]{1,20})\s([A-Z][a-z]{1,20})\b/g;

function flagNames(text) {
  const warnings = [];
  let m;
  NAME_PAIR_RE.lastIndex = 0;
  while ((m = NAME_PAIR_RE.exec(text)) !== null) {
    const first = m[1];
    const second = m[2];
    if (NAME_STOP.has(first) || NAME_STOP.has(second)) continue;
    warnings.push(`Possible name: "${m[0]}" at position ${m.index}`);
  }
  return warnings;
}

// ---------------------------------------------------------------------------
// PII keyword detection (used in compliance-guard.js advisory checks)
// Split into universal and NL-specific terms for clarity; combined into one regex.
// ---------------------------------------------------------------------------

// UNIVERSAL_PII_TERMS: locale-agnostic sensitive field names
const UNIVERSAL_PII_TERMS = [
  'passport',
  'patient',
  'diagnos',
  'medisch',
  'medical',
  'date\\.of\\.birth',
];

// NL_PII_TERMS: Dutch-specific PII identifiers
const NL_PII_TERMS = [
  'bsn',
  'burgerservicenummer',
  'sofinummer',
  'iban',
  'paspoort',
  'geboortedatum',
];

const PII_KEYWORD_RE = new RegExp(
  '\\b(?:' + [...UNIVERSAL_PII_TERMS, ...NL_PII_TERMS].join('|') + ')\\b',
  'i'
);

module.exports = {
  OUTWARD_TOOLS,
  WRITE_TOOLS,
  isOutwardTool,
  PII_KEYWORD_RE,
  redact,
  flagNames,
  findSecrets,
  findEmails,
  findPhones,
  findIBANs,
  findCards,
  findBSNs,
  isBSN,
  luhn,
  isStructurallyGuarded,
};
