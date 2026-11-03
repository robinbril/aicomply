"""The plain-text sides of an audit: the console table and audit-report.md."""

from __future__ import annotations

from aicomply.riskmatrix import level_counts


def _s(v) -> str:
    return "n/a" if v is None else f"{v:.1f}"


def score_table(scores: dict) -> str:
    w = max(len(r["short"] or "") for r in scores["frameworks"]) + 2
    head = f"{'Framework':<{w}} {'Score':>6} {'Raw':>6}  {'Band':<13} P/F/NA/unassessed"
    lines = [head, "-" * len(head)]
    for r in scores["frameworks"]:
        c = r["counts"]
        lines.append(
            f"{r['short']:<{w}} {_s(r['score']):>6} {_s(r['raw_score']):>6}  {r['band']:<13} "
            f"{c['pass']}/{c['fail']}/{c['na']}/{c['unassessed']}"
        )
    o = scores["overall"]
    lines += ["-" * len(head), f"{'OVERALL':<{w}} {_s(o['score']):>6} {'':>6}  {o['band']}"]
    if o["critical_fails"]:
        lines.append("\nFailed criticals (each caps its framework at 39):")
        lines += [f"  [{cf['id']}] {cf['title']}" for cf in o["critical_fails"]]
    if scores["unknown_ids"]:
        lines.append("\nIgnored, not in any framework: " + ", ".join(scores["unknown_ids"]))
    return "\n".join(lines)


def audit_report(meta: dict, scores: dict, register: list[dict], egress: dict | None, open_changes: dict) -> str:
    o = scores["overall"]
    out = [
        f"# AI compliance audit: {meta['system']}",
        "",
        f"Assessed {meta['date']}. Overall **{_s(o['score'])}** ({o['band']}) across {o['frameworks_in_scope']} "
        f"in-scope frameworks; {meta['assessed']} of {meta['controls']} controls assessed.",
        "",
        "## Scores",
        "",
        "| Framework | Reference | Score | Band | Critical | High | Medium | Low |",
        "|---|---|---:|---|---:|---:|---:|---:|",
    ]
    for fw in register:
        c = level_counts(fw["rows"])
        s = fw["score"]
        out.append(
            f"| {fw['short']} | {fw['reference']} | {_s(s.get('score'))} | {s.get('band')} | "
            f"{c['critical']} | {c['high']} | {c['medium']} | {c['low']} |"
        )
    if o["critical_fails"]:
        out += ["", "## Failed criticals", ""]
        out += [f"- `{cf['id']}` {cf['title']}" for cf in o["critical_fails"]]
    if open_changes:
        out += ["", "## Regulation changes awaiting review", ""]
        for slug, items in sorted(open_changes.items()):
            for c in items:
                out.append(f"- **{slug}**: {c['source_name']} changed on {c['detected_at'][:10]} (`registry/{c['file'] if '/' in c['file'] else 'changes/' + c['file']}`)")
    rows = sorted((r | {"fw": fw["short"]} for fw in register for r in fw["rows"] if r["status"] != "pass"),
                  key=lambda r: (-r["score"], r["due"]))[:25]
    if rows:
        out += ["", "## Treatment plan (top 25 by risk)", "", "| Risk | Framework | Control | Owner | Due | Action |", "|---|---|---|---|---|---|"]
        out += [
            f"| {r['score']} {r['level']} | {r['fw']} | `{r['id']}` {r['title']} | {r['owner']} | {r['due']} | {r['action']} |"
            for r in rows
        ]
    if egress:
        sm = egress["summary"]
        out += [
            "", "## Data egress", "",
            f"{sm['destinations']} outbound destinations; {sm['non_eu_with_personal_data']} outside the EU with personal data in reach.",
            "", "| Destination | Category | Region | Data in reach | Risk |", "|---|---|---|---|---:|",
        ]
        out += [
            f"| {d['vendor']} | {d['category']} | {d['region']} | {', '.join(d['data_hints']) or 'none seen'} | {d['risk_score']} |"
            for d in egress["destinations"]
        ]
    out += ["", "The full register, per framework and per part, is in `risk-matrix.html`.", ""]
    return "\n".join(out)
