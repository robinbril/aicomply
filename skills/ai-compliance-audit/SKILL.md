---
name: ai-compliance-audit
description: >
  Runs a structured compliance audit of an AI/LLM codebase or deployment against the
  EU AI Act, GDPR/AVG and 13 ISO standards (42001, 42005, 23894, 5338, 38507, 25059,
  24027, 27001, 27701, 27005, 27017, 27018, 22301), maps outbound data flows, and
  produces scores, a per-standard risk matrix and a treatment plan.
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

1. Fill the run brief from `prompts/audit-prompt.md`: target, system summary, role, evidence roots, own hosts.
2. Run `python -m aicomply changes` and note any open regulation change for an in-scope framework.

### Phase 2: Egress map

```bash
python -m aicomply egress <target> --own <your-domain> --out audit/egress.json
```

### Phase 3: Evidence and verdicts

One agent per framework, then one adversarial verifier, as in the prompt. Verdicts are `pass`, `fail`
(with `gap: violating` or `gap: absent`) or `na`. Only what exists today on the audited ref passes;
a plan, a roadmap or an unmerged fix is a `fail`.

### Phase 4: Score, matrix, report

```bash
python -m aicomply audit --findings audit/findings.json --egress audit/egress.json --system "<name>" --out audit
```

Hand the user `audit/risk-matrix.html` (tab per standard, sub-tab per part) and `audit/audit-report.md`,
with a completeness critic of what the audit could not see.
