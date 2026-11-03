# Scoring model

One deterministic model, computed by `aicomply/scoring.py`. The scorer reads the verdicts and the catalogue, nothing else. Same findings in, same numbers out.

## Verdicts

| status | meaning |
|---|---|
| `pass` | the control is satisfied today, on the audited ref, with a citation |
| `fail` | in scope and not satisfied. Carries `gap`: `violating` (the system does the wrong thing now) or `absent` (the control does not exist) |
| `na` | out of scope: the control's `applies_when` does not hold, with a reason |

There is no fourth verdict. A roadmap, a ticket, a policy that says "we will" or a fix on an unmerged branch is a `fail`. Any other status in a findings file (`planned`, `partial`, `wip`) is scored as `fail`, with a warning.

`gap` never changes the score. It feeds the likelihood in the risk matrix (see [risk-matrix.md](risk-matrix.md)).

## Weights

| severity | weight |
|---|---|
| critical | 5 |
| high | 3 |
| medium | 2 |
| low | 1 |

`python -m aicomply validate` rejects a control whose `weight` does not match its `severity`.

## Per framework

```
earned   = sum(weight of passing controls)
possible = sum(weight of passing, failing and unassessed)   # only na drops out
raw      = 100 * earned / possible                          # null when possible == 0
score    = min(raw, 39) if any critical control fails else raw
```

A framework whose controls are all `na` scores `null` and shows as "Out of scope", not 0 and not 100. A control with no verdict at all is **unassessed** and counts as a fail in the score: a framework nobody looked at does not become out of scope by omission. In the risk matrix an unassessed control gets likelihood 3.

A findings file that names the same control twice is rejected: a verifier's downgrade must never lose to a gatherer's pass further down the file. An `na` without a reason is scored but warned about.

**Critical cap.** One failed critical caps its framework at 39. A leak cannot be averaged away by green low-severity controls.

## Overall

The unweighted mean of the non-null framework scores. Frameworks are peers.

## Bands

| band | range | meaning |
|---|---|---|
| Compliant | 90-100 | audit-ready, minor gaps |
| Substantial | 70-89 | broadly there, fix the highs |
| Partial | 40-69 | material gaps, not defensible yet |
| Critical fail | 0-39 | a critical control failed, stop and fix |

`python -m aicomply score` and `audit` exit with 1 when any in-scope framework has a failed critical or scores below 40, so CI can gate on it.
