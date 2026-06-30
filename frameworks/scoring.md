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
