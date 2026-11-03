# Regulation sync

Every framework rests on an official source: a regulation, a Dutch implementing act, regulator guidance, or an ISO standard. Those sources move. The AI Act was corrected four times and amended by the Digital Omnibus on AI (Regulation (EU) 2026/1744) within two years of publication; ISO/IEC 27701, 27017 and 27018 all got new editions in 2025-2026. A catalogue that does not notice is quietly wrong.

`python -m aicomply sync` watches every source in `registry/sources.json` and records what moved.

## The one rule

**The sync signals, it never edits a control.** It writes a change record with a readable diff and the list of controls that lean on the source. A person reads the diff, updates the controls if needed, and closes the record. A tool that sees "text changed" cannot tell a reworded sentence from a new obligation, and automating that judgement would automate an audit failure.

## Four ways to read a source

| strategy | used for | how |
|---|---|---|
| `cellar` | EU regulations (AI Act, GDPR) | SPARQL on the Publications Office endpoint: every act that amends, corrects, consolidates, repeals or proposes to amend the CELEX number, and every CJEU preliminary question about it. Structured data, so a EUR-Lex redesign cannot break it. |
| `sru` | Dutch acts (UAVG) | The KOOP SRU service on the Basiswettenbestand: one line per consolidated state, with its validity period. |
| `iso` | ISO standards | ISO's own open-data feed of deliverables: current stage, edition, publication date, and the next edition in development (followed through `replacedBy`). A new draft, an amendment or a withdrawal shows up the day ISO lists it. The standard text itself is paid and never fetched. |
| `html` | Regulator guidance pages | The page reduced to text. Session tokens and "last updated" stamps are normalised away; a date in the body (an application date that moved) stays, because that is exactly the change to catch. Must contain the source's `anchor`, or the check counts as broken. |

## Three outcomes, not two

- **unchanged**: same hash as the baseline.
- **changed**: a change record lands in `registry/changes/`.
- **broken**: the fetch failed, the anchor vanished, the host redirected elsewhere, or the text shrank by more than 60%. A broken check never becomes the new baseline, so the first real change after a repair still diffs against good text. Three failures in a row mark the source broken in the report.

A failed source is retried after a day instead of waiting a full interval. Any error inside a fetcher, not only the expected ones, marks that source broken and the run continues with the next. After a genuine restructure or repeal that shrinks a page, `python -m aicomply sync --source <id> --accept-shrink` records the new text as a change and resets the guard.

## Change records

`registry/changes/<date>-<source>-<hash>.json` has two halves:

- `detection`: source, time, old and new hash, diff, impacted controls. Written once, never edited; the sync refuses to overwrite an existing record file.
- `review`: status (`open`, `in_review`, `processed`, `not_relevant`), reviewer, time, note. The only part that moves.

```bash
python -m aicomply changes --diff                    # what is open
python -m aicomply review 2026-11-10-gdpr-1a2b3c4d.json --status processed \
  --reviewer "DPO" --note "Art. 12-14 controls checked against the omnibus text"
```

While a record is open, the risk matrix shows a banner on every affected framework tab and the audit report lists it.

## Automation

`.github/workflows/regulation-sync.yml` runs the sync every Monday. A quiet week commits the moved baseline (`registry/state.json`) straight to the branch, so failure counts and check dates persist. When a source changed or broke, it opens a pull request with the change records and the diff instead, so a person sees it before anything merges. The repository setting "Allow GitHub Actions to create and approve pull requests" must be on.

## Adding a source

Add an entry to `registry/sources.json` with an `id`, `name`, `strategy`, the strategy's key (`celex`, `bwb_id`, `family` or `url` + `anchor`) and the framework slugs it feeds, then run `python -m aicomply sync --source <id>` once to set the baseline.
