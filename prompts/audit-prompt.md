# AI Compliance Audit Prompt

Paste this into Claude Code (or any agent that supports the `/workflows` command and parallel subagents) from the root of the repo or product you want audited. It runs a full EU/ISO AI-compliance audit against the five frameworks in `frameworks/`, then scores it deterministically with `scripts/score.py`.

The prompt drives a three-stage workflow: fan-out gather (one agent per framework), then adversarial verify (a skeptic re-checks every verdict), then synthesis (run the scorer, write the report). The scorer decides the number, not the model.

---

## How to invoke

This kit ships a workflow. Two ways to run it:

- **Slash command:** `/workflows` lists available workflows. Run `/workflows ai-compliance-audit` (or pick it from the list), then paste the **Run brief** below as the argument.
- **Inline:** if your harness has no workflow registry, paste the whole **Workflow definition** block plus the **Run brief** as one message. The agent will execute the stages in order.

Either way, fill the **Run brief** first. The brief is the only thing you edit per audit.

---

## Run brief (edit this)

```
TARGET: <repo path or product name, e.g. ./ or "AcmeChat assistant">
SYSTEM SUMMARY: <2-4 sentences: what the AI system does, who the users are, what data it touches, which models/providers it calls, deployment region>
ROLE: <provider | deployer | importer | distributor, and controller | processor for GDPR>
EVIDENCE ROOTS: <where to look: source dirs, /docs, /infra, README, DPA folder, model config, .env.example, IaC>
FRAMEWORKS: all          # or a subset: eu-ai-act, gdpr-avg, iso-42001, iso-23894, iso-27001-27701
OUT: ./findings.json     # machine verdicts, consumed by scripts/score.py
REPORT: ./audit-report.md
```

If `SYSTEM SUMMARY` or `ROLE` is blank, **stop and ask** before gathering. Scope drives the `na` verdicts, and a wrong role silently invalidates half the EU AI Act controls.

---

## Workflow definition

A workflow here is a named pipeline of stages. Each stage names the agents it spawns, the model, the inputs, and a strict output schema. Stages run in order; agents inside a stage run in parallel.

### Stage 1: Gather (parallel fan-out, one agent per framework)

Spawn N agents, one per in-scope framework yaml. Each agent is **scoped to its own framework only** so contexts stay small and parallel.

Each gather agent does exactly this:

1. Read its framework yaml from `frameworks/<file>.yaml`. The schema per control is:
   `id, title, requirement, applies_when, severity, weight, check, evidence, advice`.
2. For each control, decide scope first: does `applies_when` hold for this TARGET given ROLE and SYSTEM SUMMARY? If not, verdict is `na` with a one-line reason. Do not hunt for evidence on out-of-scope controls.
3. For in-scope controls, search EVIDENCE ROOTS for the artifact named in `check`/`evidence`. Use grep/glob and read only the relevant lines. **Never dump whole files.** Cite `path:line` or a config key, not a paragraph.
4. Emit `pass` only with a concrete citation. No citation, no pass: it is a `fail`. `pass` on assumption is the cardinal sin here.

**Token discipline (enforced):** each agent returns only the JSON array below, max ~25 words of evidence per control. No prose preamble, no restating the requirement, no summary. The yaml already holds the requirement text; do not echo it.

Gather output schema (per agent, JSON only):

```json
[
  {
    "id": "GDPR-PII-TO-EXTERNAL-LLM",
    "framework": "gdpr-avg",
    "severity": "critical",
    "status": "fail",
    "evidence": "prompts in src/llm/client.ts:42 send full user record; no DPA file found under /legal",
    "citation": "src/llm/client.ts:42",
    "confidence": "high"
  }
]
```

Allowed `status`: `pass` | `fail` | `na`. Nothing else.

### Stage 2: Adversarial verify (skeptic, fresh context)

Spawn one verifier agent. It does **not** see Stage 1's reasoning, only the merged findings array and the same EVIDENCE ROOTS. Its job is to break the verdicts:

- For every `pass`: re-open the cited `path:line`. Does the evidence actually satisfy the control's `check`, or is it adjacent/aspirational (a TODO, a comment, a policy that says "we should")? Downgrade unsupported passes to `fail`.
- For every `fail`: spend one honest search for evidence the gatherer missed (a differently-named DPA, a config flag, a policy doc). Upgrade only with a real citation.
- For every `na`: re-test `applies_when` against ROLE and SYSTEM SUMMARY. A wrongly-scoped-out critical (e.g. marking AIA-PROHIB `na` without screening) flips back to in-scope.

Verifier output: the **same schema** as Stage 1 plus a `verify` field per changed control:

```json
{ "id": "...", "status": "fail", "verify": "downgraded: src/llm/client.ts:42 comment is a TODO, not an implemented redaction", "...": "..." }
```

The verifier's array is authoritative. Write it to `OUT` (findings.json).

### Stage 3: Synthesis (deterministic score + report)

1. Run the scorer. Do not compute the score yourself:

   ```
   python scripts/score.py --findings ./findings.json --frameworks ./frameworks --report ./audit-report.md
   ```

   The model from `frameworks/scoring.md`: weighted mean per framework (critical=5, high=3, medium=2, low=1), `na` dropped from the denominator, any failed in-scope **critical** caps that framework at 39, overall = unweighted mean of non-null frameworks.

2. The report (written by the agent on top of the scorer's numbers) must contain, in this order:
   - **Scored table:** framework, score, band, failed-critical count. Numbers come from the scorer verbatim.
   - **Failed criticals first:** every `fail` with `severity: critical`, its citation, and the one-line `advice` from the yaml. These are the cap drivers.
   - **High/medium fails:** grouped by framework, each with citation and advice.
   - **Remediation, prioritised:** order by (severity desc, then weight desc). For each, the control id, what to do (from `advice`), and the artifact to produce.
   - **Completeness critic (mandatory last section):** what was NOT checked. Name every modality and source the audit could not reach: runtime behaviour vs static code, training-data provenance you could not see, infra/IaC not in the repo, model-card claims taken on trust, third-party DPAs assumed-signed. List any control marked `na` whose scope you were less than sure about. An audit that claims full coverage without this section is lying.

---

## Determinism and honesty rules (apply to every stage)

- The **scorer owns the number.** Agents produce verdicts; `score.py` produces the score. If the agent and the scorer disagree, the scorer wins and the agent has a bug in its findings.
- **One verdict per control id.** Deduplicate before scoring. Same `id` twice means the merge is wrong.
- **Cite or fail.** Every `pass` carries a `path:line` or config key. Plausibility is not evidence.
- **Scope is a decision, not a default.** `na` needs a reason tied to `applies_when`. Blanket `na` to inflate a score is the failure mode the verifier exists to catch.
- **No whole-file reads in output.** Grep to the line, cite the line. Keeps the audit token-cheap and the evidence checkable.

---

## Framework reference

| file | shortcode prefix | scope |
|------|------------------|-------|
| `eu-ai-act.yaml`        | `AIA-`   | EU AI Act 2024/1689: risk tiers, prohibited practices, high-risk obligations, GPAI, transparency |
| `gdpr-avg.yaml`         | `GDPR-`  | personal data in training/prompts/outputs, external-LLM egress, DSR, DPIA |
| `iso-42001.yaml`        | `AI-` / `AIMS-` | AI management system: policy, roles, risk, impact, lifecycle, monitoring |
| `iso-23894.yaml`        | `RID-` / `TRT-` / `MON-` etc. | AI risk management process: identification, analysis, treatment, monitoring |
| `iso-27001-27701.yaml`  | `A.` / `P.` | infosec + privacy controls for AI software: secrets, encryption, supplier, prompt-input, PIMS |

Cross-framework note: GDPR-PII-TO-EXTERNAL-LLM, P.8.5-PROCESSOR and AIA-DEPLOYER overlap on third-party model use. Verify once, reference across. Do not let one missing DPA fail silently in one framework and pass in another.
