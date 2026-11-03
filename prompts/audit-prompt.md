# AI compliance audit prompt

Paste this into Claude Code (or any agent with parallel subagents) from the root of the system you want audited. It audits the system against every framework in `frameworks/`, maps where its data goes, and lets `python -m aicomply audit` turn the verdicts into scores, a risk matrix and a treatment plan.

Agents gather and verify. Code decides the number.

---

## Run brief (edit this)

```
TARGET: <repo path or product name, e.g. ./ or "AcmeChat assistant">
SYSTEM SUMMARY: <2-4 sentences: what the AI system does, who uses it, what data it touches, which models/providers it calls, where it runs>
ROLE: <provider | deployer | importer | distributor, and controller | processor for GDPR>
EVIDENCE ROOTS: <where to look: source dirs, /docs, /infra, README, DPA folder, model config, .env.example, IaC>
OWN HOSTS: <your own domains, e.g. acme.eu, so the egress scan treats them as first party>
FRAMEWORKS: all          # or a subset of slugs: eu-ai-act, gdpr, iso-42001, iso-42005, iso-23894, iso-5338, iso-38507,
                         # iso-25059, iso-24027, iso-27001, iso-27701, iso-27005, iso-27017, iso-27018, iso-22301
OUT: ./audit             # findings.json, egress.json and the generated report land here
```

If `SYSTEM SUMMARY` or `ROLE` is blank, stop and ask. Scope drives every `na`, and a wrong role silently invalidates half the AI Act controls.

---

## Stage 0: Ground truth (once, before any gathering)

1. **Audited ref.** Run `git fetch --all`, pick the audited ref (default: the default branch HEAD) and record its sha and date in `OUT/ground-truth.md`.
2. **Inventory the rest.** List other branches, worktrees, uncommitted changes and stashes. They are searched for one reason only: to name a fix that exists but is not on the audited ref. Such a fix never changes a verdict. The control is `fail`, and the report says "fix exists on `<ref>`, merge it".
3. **Regulation freshness.** Run `python -m aicomply changes`. Every open change on an in-scope framework goes into the report: the controls were written against the previous text of that source.

## Stage 1: Egress map

Run the static egress scan and keep its output; every gather agent reads it.

```
python -m aicomply egress <TARGET> --own <OWN HOSTS> --out OUT/egress.json
```

It lists every outbound destination (LLM providers, analytics, error tracking, storage, unknown hosts), the region, the personal data in reach of each call, and risky settings such as `send_default_pii=True`. For a native binary or an app without source, run REA (github.com/morluto/rea) first and pass the endpoints it recovers with `--extra-hosts`.

## Stage 2: Gather (parallel, one agent per framework)

Spawn one agent per in-scope `frameworks/<slug>.yaml`. Each agent sees only its own framework, the brief, Stage 0 and the egress map.

Per control (`id, title, part, clause, requirement, applies_when, severity, weight, check, evidence, advice, owner`):

1. **Scope first.** Does `applies_when` hold for TARGET, ROLE and SYSTEM SUMMARY? If not: `na`, with a one-line reason. No evidence hunting on out-of-scope controls.
2. **Evidence.** Search EVIDENCE ROOTS for what `check` and `evidence` name. Grep to the line; never dump files. Cite `path:line` or a config key.
3. **Verdict.**
   - `pass`: only with a concrete citation on the audited ref that satisfies `check` today.
   - `fail` with `"gap": "violating"`: the system does the wrong thing now (PII leaving in a prompt, a secret in the repo, tracking before consent). The egress map is the first place to look.
   - `fail` with `"gap": "absent"`: the control does not exist. A roadmap, a ticket, a TODO, a policy that says "we will", or a fix on an unmerged branch is still `absent`.

Output, JSON only, max ~25 words of evidence per control:

```json
[
  { "id": "GDPR-PII-TO-EXTERNAL-LLM", "status": "fail", "gap": "violating",
    "evidence": "src/llm/client.ts:42 sends user.email in the prompt to api.openai.com" },
  { "id": "AIA-PROHIB", "status": "pass", "evidence": "docs/art5-screening.md:3 dated screening by Legal" },
  { "id": "AIA-GPAI", "status": "na", "evidence": "deployer only, provides no general-purpose model" }
]
```

Allowed `status`: `pass`, `fail`, `na`. Anything else is scored as `fail` by the tool.

## Stage 3: Adversarial verify (fresh context)

One verifier gets the merged array, the egress map and the evidence roots, not the gatherers' reasoning. It tries to break every verdict:

- **Every `pass`:** reopen the citation. Adjacent, aspirational or future evidence (a TODO, a draft, "we should", a plan) is `fail` + `absent`.
- **Every `fail`:** one honest search for evidence the gatherer missed on the audited ref. Upgrade only with a real citation.
- **Every `na`:** retest `applies_when`. A critical scoped out without a reason flips back in scope.
- **Cross-check egress:** a destination with personal data in reach and no matching processor agreement, transfer basis or masking is a `fail` + `violating` on the controls the egress map lists for it, whatever the documents say.

The verifier's array is authoritative. Write it to `OUT/findings.json`.

## Stage 4: Score and report (deterministic)

```
python -m aicomply audit --findings OUT/findings.json --egress OUT/egress.json --system "<name>" --out OUT
```

This writes:

- `risk-matrix.html`: one tab per framework, a sub-tab per part (clause group or annex theme), each with a 5x5 heatmap, a risk register and a treatment plan with owner and deadline; plus Data egress and Regulation sources tabs.
- `audit-report.md`: scores, failed criticals, open regulation changes, the top 25 treatments, the egress summary.
- `risk-register.json`: the same register for other tools.

Then add, below the generated report, a **completeness critic**: what the audit could not see (runtime behaviour, training-data provenance, infrastructure outside the repo, contracts taken on trust) and every `na` you are less than sure about. An audit that claims full coverage without this section is lying.

---

## Rules for every stage

- **The tool owns the number.** If an agent's sense of the score and the tool disagree, the findings are wrong.
- **Today, not tomorrow.** Only what exists on the audited ref counts. Plans, roadmaps and unmerged fixes are reported, never credited.
- **One verdict per control id.** Deduplicate before scoring.
- **Cite or fail.** Plausibility is not evidence.
- **Scope is a decision.** `na` needs a reason tied to `applies_when`; blanket `na` to lift a score is what the verifier exists to catch.
- **Verify once, reference across.** GDPR-PII-TO-EXTERNAL-LLM, GDPR-PROCESSOR-DPA, P.7.5-TRANSFER, A.5.19-SUPPLIER and AIA-DEPLOYER overlap on third-party models. One missing DPA must fail in each of them, not pass in one.
