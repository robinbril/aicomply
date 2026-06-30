# AIComply

A paste-and-run audit kit for EU/ISO AI compliance. Point it at a repo or product, an agent fans out one checker per framework, a skeptic re-checks every verdict, and a deterministic scorer produces a 0-100 score per framework plus an overall. The number comes from a script, not from model vibes.

## What it covers

Five frameworks, ~90 controls total, each with an id, a `check`, the `evidence` to look for, and one line of `advice`:

| framework | file | shortcode | what it checks |
|-----------|------|-----------|----------------|
| EU AI Act 2024/1689 | `frameworks/eu-ai-act.yaml` | `AIA-` | risk tiers, prohibited practices, high-risk obligations, GPAI, transparency |
| GDPR / AVG | `frameworks/gdpr-avg.yaml` | `GDPR-` | personal data in training/prompts/outputs, external-LLM egress, DSR, DPIA |
| ISO/IEC 42001 | `frameworks/iso-42001.yaml` | `AI-` / `AIMS-` | AI management system: policy, roles, risk, impact, lifecycle, monitoring |
| ISO/IEC 23894 | `frameworks/iso-23894.yaml` | `RID-` / `TRT-` / `MON-` | AI risk management process: identify, analyse, treat, monitor |
| ISO/IEC 27001 + 27701 | `frameworks/iso-27001-27701.yaml` | `A.` / `P.` | infosec + privacy for AI software: secrets, encryption, supplier, prompt-input, PIMS |

## How the pieces fit

```
frameworks/*.yaml   the controls (id, severity, weight, check, evidence, advice)
prompts/audit-prompt.md   the workflow you paste: gather -> adversarial verify -> synthesis
hooks/              optional guard hooks (pre-commit / pre-prompt) that catch obvious leaks early
scripts/score.py    deterministic scorer: findings.json -> per-framework + overall score
frameworks/scoring.md   the scoring model, one page, matches score.py exactly
examples/           a worked, anonymised audit report
```

Flow: paste `prompts/audit-prompt.md`, fill the run brief, the agent writes `findings.json` (one verdict per control), then `score.py` turns those verdicts into the report. The hooks are a cheap front line (block a hardcoded key or raw PII in a prompt before it ships); the audit is the full sweep.

## Install

See `hooks/install.md` for the guard hooks. The audit itself needs no install: it is a prompt plus a Python scorer.

```
python --version        # 3.9+
python scripts/score.py --help
```

## Scoring model (100 points)

Full detail in `frameworks/scoring.md`. In short:

- Each control is `pass`, `fail`, or `na`. `na` (out of scope per `applies_when`) is dropped from the math.
- Weight by severity: critical 5, high 3, medium 2, low 1.
- Per-framework score = `100 * earned / possible` over in-scope controls.
- **Critical cap:** any failed in-scope critical caps that framework at 39. You cannot average away a leak.
- Overall = unweighted mean of the frameworks that are in scope.

Bands: 90-100 compliant, 70-89 substantial, 40-69 partial, 0-39 critical fail.

## Run it

1. Open `prompts/audit-prompt.md`, copy it into your agent, fill the run brief (target, system summary, role, evidence roots).
2. Let it run the three stages. It writes `findings.json` and calls the scorer.
3. Read `audit-report.md`. See `examples/sample-audit-report.md` for the end state.

The kit is generic and offline by default: nothing leaves your machine, no findings are uploaded. Bring your own evidence, get a defensible score.
