# Hook installation

Add the following block to your `.claude/settings.json` (project-local) or
`~/.claude/settings.json` (user-global). Adjust the absolute path prefix to
match where you cloned this kit.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "WebFetch|web_fetch|SendMessage|send_message|mcp__ms365__send.*|mcp__ms365__reply.*|mcp__ms365__forward.*|mcp__ms365__create-draft.*|mcp__slack__.*|Write|write_file|mcp__filesystem__write_file",
        "hooks": [
          {
            "type": "command",
            "command": "node /ABSOLUTE/PATH/TO/aicomply/hooks/pii-redact.js"
          }
        ]
      },
      {
        "matcher": "WebFetch|web_fetch|Write|Edit|write_file|edit_file|mcp__filesystem__write_file|mcp__filesystem__edit_file|Bash|bash|mcp__terminal__send_command",
        "hooks": [
          {
            "type": "command",
            "command": "node /ABSOLUTE/PATH/TO/aicomply/hooks/compliance-guard.js"
          }
        ]
      }
    ]
  }
}
```

Replace `/ABSOLUTE/PATH/TO/aicomply` with the real path, for example
`C:/Users/you/aicomply` on Windows or `/home/you/aicomply`
on Linux/macOS.

## What these hooks do

Both hooks are pure Node.js scripts: no network calls, no LLM invocations, no
external dependencies beyond the Node standard library. They run synchronously
on every matching tool call, typically completing in under 5ms.

**pii-redact.js** intercepts tool calls that send data outward (WebFetch
posts, mail sends, cloud-synced file writes) and redacts high-confidence PII
(email, phone, IBAN, credit card with Luhn check, Dutch BSN with 11-proef)
from the payload before it leaves the machine. It fails open on any internal
error so a hook bug never blocks the user. The one exception is raw secrets
(OpenAI keys, GitHub tokens, AWS access keys, Slack tokens, JWTs, Bearer
tokens): those cause a hard block with a clear error message, since sending a
credential to an external service is always unrecoverable.

**compliance-guard.js** is an advisory layer. It runs cheap regex heuristics
on every matched tool call and prints a one-line warning to stderr referencing
the relevant framework control (ISO 27001:2022, GDPR) when it
detects a likely-noncompliant action: PII keywords heading to an external LLM
endpoint, audit logging being disabled, permission escalation commands, or
unencrypted temp-path writes containing sensitive data. The only hard block in
this hook is the same secret-to-VCS/public-path case, as belt-and-suspenders
over pii-redact.

## False-positive guards

Both hooks import `pii_patterns.js`, which applies structural guards before
any PII match: UUIDs, ISO 8601 dates, URLs, Bearer tokens, JWTs, and long
hex/base64 strings are excluded from BSN, credit-card, and phone detection,
preventing the most common false-positive patterns seen in API payloads and
log files.

The hook matcher above uses globs like `mcp__ms365__send.*` to cover dynamically
named send tools. The outward-tool check in pii-redact.js uses `isOutwardTool()`
from `pii_patterns.js` as the single source of truth; keep that function in sync
when adding new send tool patterns.
