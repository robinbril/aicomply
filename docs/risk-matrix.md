# Risk matrix

`python -m aicomply audit` turns verdicts into a risk register, a heatmap and a treatment plan for every framework and for every part of it. Nothing in the matrix is typed in by hand: every number is derived, so the same findings always give the same matrix.

## Impact: from the control's severity

| severity | impact |
|---|---|
| critical | 5 Severe |
| high | 4 Major |
| medium | 3 Moderate |
| low | 2 Minor |

## Likelihood: from the verdict

| verdict | likelihood |
|---|---|
| `fail`, `gap: violating` | 5 Almost certain |
| `fail` while the egress scan sees personal data flowing to a destination this control governs | 5 Almost certain |
| `fail`, `gap: absent` | 4 Likely |
| no verdict (unassessed; scored as fail) | 3 Possible |
| `pass`, but data flows to a destination this control governs | 2 Unlikely |
| `pass` | 1 Rare |

`na` controls are out of the matrix.

## Level, treatment, deadline

Risk = likelihood x impact.

| score | level | treatment | due |
|---|---|---|---|
| 20-25 | critical | Mitigate now, block release | audit date + 14 days |
| 10-19 | high | Mitigate | + 30 days |
| 5-9 | medium | Mitigate | + 90 days |
| 1-4 | low | Mitigate, or accept with signed rationale | + 180 days |

A passing control is listed as residual risk with treatment "Monitor". The owner of every treatment is the control's `owner` role from the catalogue; the action is its `advice`.

## The document

`risk-matrix.html` is one self-contained file (no external scripts, fonts or images), readable offline and printable:

- **Overview**: the combined heatmap, a score and risk count per framework, the twelve highest risks.
- **One tab per framework**, ISO standards first, then laws. Each has a sub-tab per part, the sections the catalogue groups its controls in (for ISO/IEC 27001: Clauses 4-10, A.5 Organizational, A.6 People, A.8 Technological). Every part has its own heatmap, risk register and treatment plan.
- **Data egress**: every outbound destination from the egress scan.
- **Regulation sources**: the state of every watched source and every detected change with its diff.

Printing gives one page per framework and per part, with the page number as the only footer.
