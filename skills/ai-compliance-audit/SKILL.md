---
name: ai-compliance-audit
description: >
  Runs a structured compliance audit of an AI/LLM codebase or deployment against
  EU AI Act, GDPR/AVG, ISO 42001, ISO 23894, and ISO 27001/27701.
  Use when: the user asks for a compliance check, audit, or gap analysis of an AI system;
  before a product launch or procurement review; when preparing for a regulatory inspection;
  when asked "are we GDPR-compliant?" or "do we meet the AI Act?" in an AI context.
---

## Trigger

Invoked by: `/ai-compliance-audit`, "run a compliance audit", "check AI Act compliance",
"GDPR audit for this AI system", or any request for a structured gap analysis of an AI/LLM deployment.

## Workflow

Follow `prompts/audit-prompt.md` as the canonical audit workflow. That file defines the
evidence-gathering steps, control mapping, and output format in detail. This skill sets
the frame; the prompt drives execution.

### Phase 1: Scope

1. Ask (or infer from codebase): which frameworks apply? Load all `frameworks/*.yaml`.
2. Determine actor role: provider / deployer / both. Record the AI risk tier if relevant.
3. Identify what is in scope: models used, data pipelines, user-facing surfaces, third-party APIs.

### Phase 2: Evidence gathering

For each in-scope framework, for each control:
- Read the `check` field to know what to look for.
- Search the codebase, docs, and config for evidence (code, comments, README, env vars, CI config).
- Mark each control: `pass` / `fail` / `na` with a one-line note.

Run searches in parallel where independent. Be surgical: only read files relevant to a control.

### Phase 3: Score

Call `scripts/score.py` with the findings JSON:

```bash
python scripts/score.py findings.json
```

The script reads `frameworks/*.yaml` and prints a per-framework score table plus a machine-readable
JSON block. A single critical fail caps the framework score at 39 and surfaces in the critical-fails list.

### Phase 4: Report

Produce a findings report with:
- Per-framework score (0-100) and pass/fail/na count
- Critical fails listed first, each with the control title and a one-line remediation
- High-severity gaps, then medium, then low
- A "next actions" list ordered by severity

Keep the report concise: one row per finding, remediation in the `advice` field of the YAML.
Do not pad. Link the evidence location (file:line) where found.
