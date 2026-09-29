# Scoring model

One deterministic model, computed by `scripts/score.py`. No vibes: the scorer reads the per-control verdicts and the framework yaml, nothing else.

## Inputs

- Framework yaml files in `frameworks/` (each control has `id`, `severity`, `weight`).
- A findings file (`findings.json`) with one verdict per control:
  `{ "id": "GDPR-LAWFUL-BASIS", "status": "pass" | "fail" | "na", "evidence": "...", "severity": "..." }`

`status` meaning:
- `pass`: control satisfied, evidence cited.
- `fail`: control in scope and not satisfied (or no evidence found).
- `na`: control out of scope for this system (its `applies_when` does not hold).
- `planned`: control not built yet, but a git-tracked repo document commits to building it. Only earns credit in roadmap mode (below); otherwise it scores exactly like `fail`.

## Weights

Weight is fixed per severity and already encoded in each control's `weight` field. They must agree:

| severity | weight |
|----------|--------|
| critical | 5 |
| high     | 3 |
| medium   | 2 |
| low      | 1 |

## In-scope logic

Only `pass` and `fail` controls count. `na` controls are dropped from both numerator and denominator (you are not penalised for a control that does not apply, nor rewarded). A framework where every control is `na` scores `null` (reported as "out of scope"), not 0 and not 100.

## Per-framework score

```
earned   = sum(weight for c in framework if c.status == "pass")
possible = sum(weight for c in framework if c.status in {"pass","fail"})
raw      = 100 * earned / possible          # 0..100, or null if possible == 0
```

## Critical-cap rule

Any in-scope `critical` control that is `fail` caps the framework score at **39** (a hard fail band). The cap applies after the weighted mean:

```
if any(c.severity == "critical" and c.status == "fail"):
    score = min(raw, 39)
else:
    score = raw
```

Rationale: a single failed critical (e.g. PII sent to an external LLM with no DPA, or a prohibited Art 5 practice) cannot be averaged away by many green low-severity controls. A framework cannot read "82% compliant" while leaking special-category data.

## Overall score

Unweighted mean of the per-framework scores that are not `null`:

```
overall = mean(score for f in frameworks if f.score is not null)
```

Frameworks are treated as equal peers. A framework fully `na` does not drag the overall mean.

## Bands

| band | range | meaning |
|------|-------|---------|
| Compliant      | 90-100 | audit-ready, minor gaps only |
| Substantial    | 70-89  | broadly there, fix the highs |
| Partial        | 40-69  | material gaps, not defensible yet |
| Critical fail  | 0-39   | a critical control failed, stop and remediate |

The scorer prints per-framework scores, the overall, the band, and the list of failed criticals driving any cap. Same findings in, same numbers out.

## Roadmap mode (opt-in)

`python scripts/score.py --findings findings.json --roadmap-credit --repo <repo root>`

For systems that are early but honest about it: a control that does not exist yet, and that the repo itself documents as work to be built, earns partial credit. Default mode is unchanged.

A `planned` verdict must carry all of:

```json
{ "id": "GDPR-DPIA", "status": "planned", "gap": "absent",
  "roadmap_ref": { "path": "docs/compliance/roadmap.md", "quote": "verbatim text from that file" } }
```

The scorer rejects the claim (scores it as `fail`, lists it under "Rejected roadmap claims") unless:

1. `gap` is `absent` (nothing exists yet) or `fixed-unmerged` (the fix exists on another branch or ref that is not merged, see below). A control that is built wrongly or violated today with no fix anywhere (PII already leaving to an external LLM, a secret in the repo) is `violating`, and a roadmap never offsets that.
2. `roadmap_ref.path` exists in `--repo` and is tracked in git (an untracked local note is not evidence).
3. `roadmap_ref.quote` occurs verbatim in that file (whitespace-insensitive), so the claim cannot be invented.

`fixed-unmerged` adds `roadmap_ref.ref` (branch or sha): the scorer reads `path` from that ref with `git show <ref>:<path>` and checks the quote there. The fix is real code, but it is not on the audited ref, so it earns the same half credit and the strict score still counts it as `fail`. Once merged, the control is a plain `pass`.

The audit's skeptic additionally checks that the quote is a concrete commitment (a named deliverable in a phase or task), not "we should".

Credit and caps:

```
earned   = sum(weight for pass) + 0.75 * sum(weight for valid planned)
possible = as before (planned counts in full)
```

- A failed in-scope critical with no valid roadmap caps the framework at **39**, as before.
- A critical that is only `planned` caps the framework at **79**: it can reach the low end of Substantial (70-79), never Compliant.
- Every result prints two numbers per framework and overall: **Score** (roadmap-adjusted) and **Strict** (every `planned` counted as `fail`). Quote both. The adjusted score is the roadmap-credit view; the strict score is what is built today.

## Whole-repo scan (every audit)

The audited state is one ref (default: the default branch HEAD, recorded by sha in the report). Evidence is never limited to the checked-out tree: before a control is scored `fail` or `violating`, the whole repository is searched, meaning every local and remote branch, every worktree, uncommitted changes and stashes. A fix found on an unmerged ref becomes `planned` with `gap: "fixed-unmerged"`; a fix found only as uncommitted change is reported as a finding but scores `fail` until it is committed to a ref. Code found on the audited ref is `pass` evidence as usual.
