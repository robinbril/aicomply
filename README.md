# AIComply

Score any AI or LLM system against the EU AI Act, GDPR, and the ISO AI standards, and get a number you can defend. You point it at a codebase or a product, an agent checks one framework at a time, a second agent tries to refute every verdict, and a deterministic script turns the verdicts into a 0-100 score. The number comes from code, not from a model's mood.

**You get:** 5 frameworks (~90 controls), a paste-and-run audit prompt, two guard hooks that catch leaks before they ship, and a scorer that returns the same number for the same findings every time.

## Quick start

1. **Audit.** Open `prompts/audit-prompt.md`, paste it into your agent, and fill the four-line brief: what you are auditing, a one-paragraph system summary, your role, and where the evidence lives.
2. **Score.** The agent writes `findings.json` (one `pass` / `fail` / `na` per control) and runs the scorer:
   ```
   python scripts/score.py --findings findings.json --report audit-report.md
   ```
3. **Read** `audit-report.md`: a score per framework, the overall, the band, and every failed critical. `examples/sample-audit-report.md` shows what the end state looks like.

The audit needs no install: it is a prompt plus one standard-library Python script (3.9+). The guard hooks are optional, see below.

## What it checks

Five frameworks, ~90 controls. Every control carries an `id`, a `check` (what to verify), the `evidence` to look for, a `severity`, and one line of `advice`.

| Framework | File | Focus |
|---|---|---|
| EU AI Act (2024/1689) | `frameworks/eu-ai-act.yaml` | risk tiers, prohibited practices, high-risk duties, GPAI, transparency |
| GDPR / AVG | `frameworks/gdpr-avg.yaml` | personal data in prompts/training/output, external-LLM egress, DSR, DPIA |
| ISO/IEC 42001 | `frameworks/iso-42001.yaml` | AI management system: policy, roles, risk, lifecycle, monitoring |
| ISO/IEC 23894 | `frameworks/iso-23894.yaml` | AI risk process: identify, analyse, treat, monitor |
| ISO/IEC 27001 + 27701 | `frameworks/iso-27001-27701.yaml` | infosec + privacy: secrets, encryption, suppliers, prompt-injection, PIMS |

## How it works

```
prompts/audit-prompt.md  ->  agent fans out, one checker per framework
                         ->  a skeptic re-checks every pass and every fail
                         ->  writes findings.json (one verdict per control)
scripts/score.py         ->  reads findings.json + frameworks/*.yaml
                         ->  audit-report.md (per-framework score + overall)
```

The prompt drives three stages: gather evidence, verify it adversarially, then synthesise. Only the scorer produces the number, so the same findings always yield the same score. No model is asked to "rate compliance."

## The score (100 points)

Full model in `frameworks/scoring.md`. In short:

- Each control is `pass`, `fail`, or `na`. `na` (out of scope per its `applies_when`) drops out of the math entirely.
- Severity sets the weight: critical 5, high 3, medium 2, low 1.
- Framework score = `100 * earned / possible` across the in-scope controls.
- **Critical cap:** a single failed in-scope critical caps that framework at 39. You cannot average a leak away.
- Overall = the mean of the in-scope frameworks.

**Roadmap mode (opt-in).** For a young system that documents what it will build, `--roadmap-credit --repo <root>` gives a verified `planned` control 75% credit and softens the critical cap from 39 to 79. Claims are checked on disk (git-tracked file, verbatim quote, control absent rather than violated) and every result shows an adjusted and a strict score. See `frameworks/scoring.md`.

**Whole-repo scan.** Every audit starts with a ground-truth stage: fetch, then inventory all branches, worktrees, uncommitted changes and stashes. A fix that exists on an unmerged branch is found and credited as `planned` (`fixed-unmerged`), instead of the audit failing the control because only `main` was read.

| Band | Score | Meaning |
|---|---|---|
| Compliant | 90-100 | audit-ready, minor gaps |
| Substantial | 70-89 | broadly there, fix the highs |
| Partial | 40-69 | material gaps, not defensible yet |
| Critical fail | 0-39 | a critical control failed, stop and fix |

## Guard hooks (optional)

Two PreToolUse hooks for Claude Code, regex-only, no LLM, no tokens, so they can run on every tool call:

- `hooks/pii-redact.js` redacts PII and blocks secrets before a payload leaves the machine (outbound web, mail, file writes to synced folders).
- `hooks/compliance-guard.js` prints a one-line advisory tied to a real control id when it sees a risky move (PII heading to an external LLM, logging switched off, a secret going into a repo).

Wire them with the snippet in `hooks/install.md` (Node 18+). They are a cheap front line; the audit is the full sweep.

## Layout

```
frameworks/   the controls (yaml) + scoring.md (the model)
prompts/      the paste-and-run audit prompt
hooks/        the optional guard hooks + install.md
scripts/      score.py (the deterministic scorer, stdlib only)
examples/     a worked, anonymised audit report
```

Generic and offline by default: nothing leaves your machine and no findings are uploaded. Bring your own evidence, get a defensible score.
