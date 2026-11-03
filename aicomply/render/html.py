"""The risk-matrix document: one self-contained HTML file, a tab per framework, a tab per part."""

from __future__ import annotations

import os
import re
from html import escape

from aicomply.riskmatrix import IMPACT_LABELS, LIKELIHOOD_LABELS, heatmap, level, level_counts

CSS = os.path.join(os.path.dirname(__file__), "matrix.css")

JS = """
function pick(b, remember) {
  var nav = b.closest('nav');
  nav.querySelectorAll('button').forEach(function (x) {
    var on = x === b; x.setAttribute('aria-selected', on);
    document.getElementById(x.dataset.panel).hidden = !on;
  });
  if (remember && !nav.classList.contains('sub')) history.replaceState(null, '', '#' + b.dataset.panel);
}
document.querySelectorAll('nav.tabs').forEach(function (nav) {
  nav.addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) pick(b, true); });
});
var h = location.hash.slice(1) || new URLSearchParams(location.search).get('tab'),
    t = h && document.querySelector('nav.tabs:not(.sub) button[data-panel="' + h + '"]');
if (t) pick(t, false);
"""


def _e(value) -> str:
    return escape(str(value if value is not None else ""))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _band_class(band: str) -> str:
    return _slug(band or "out of scope")


def _score_txt(s) -> str:
    return "n/a" if s is None else f"{s:.0f}"


def _tabs(items: list[tuple[str, str]], sub: bool = False) -> str:
    buttons = "".join(
        f'<button type="button" role="tab" data-panel="{pid}" aria-selected="{"true" if i == 0 else "false"}">{_e(label)}</button>'
        for i, (pid, label) in enumerate(items)
    )
    return f'<nav class="tabs{" sub" if sub else ""}" role="tablist">{buttons}</nav>'


def _heatmap(rows: list[dict]) -> str:
    grid = heatmap(rows)
    cells = []
    for lk in range(5, 0, -1):
        cells.append(f'<div class="ax" title="{LIKELIHOOD_LABELS[lk]}">{lk}</div>')
        for im in range(1, 6):
            n = grid[lk - 1][im - 1]
            cls = level(lk * im) + ("" if n else " empty")
            cells.append(f'<div class="cell {cls}" title="likelihood {lk} x impact {im} = {lk * im}">{n or "."}</div>')
    cells.append('<div></div>' + "".join(f'<div class="ax">{i}</div>' for i in range(1, 6)))
    return (
        '<div class="card"><div class="heat">' + "".join(cells) + "</div>"
        '<div class="heat-cap"><span>Likelihood &uarr;</span><span>Impact &rarr;</span></div></div>'
    )


def _kpis(rows: list[dict]) -> str:
    c = level_counts(rows)
    return '<div class="kpis">' + "".join(
        f'<div class="kpi {k}"><div class="v">{c[k]}</div><div class="l">{k}</div></div>'
        for k in ("critical", "high", "medium", "low")
    ) + "</div>"


def _register(rows: list[dict]) -> str:
    if not rows:
        return '<p class="small">No in-scope controls in this part.</p>'
    body = []
    for r in rows:
        egress = f'<div class="small">Egress: {_e(", ".join(r["egress"]))}</div>' if r["egress"] else ""
        evidence = f'<div class="small">Evidence: {_e(r["evidence"])}</div>' if r["evidence"] else ""
        body.append(
            "<tr>"
            f'<td><div class="id">{_e(r["id"])}</div><div>{_e(r["title"])}</div><div class="small">{_e(r["clause"])}</div></td>'
            f'<td><span class="pill {r["status"]}">{_e(r["status"])}</span></td>'
            f'<td class="num" title="{_e(r["likelihood_why"])}">{r["likelihood"]}</td>'
            f'<td class="num">{r["impact"]}</td>'
            f'<td class="num"><span class="pill {r["level"]}">{r["score"]} {r["level"]}</span></td>'
            f'<td class="hide-sm">{_e(r["treatment"])}<div class="small">{_e(r["owner"])}{" &middot; due " + _e(r["due"]) if r["due"] else ""}</div></td>'
            f'<td>{_e(r["action"])}{evidence}{egress}</td>'
            "</tr>"
        )
    return (
        '<div class="tbl"><table><thead><tr><th>Control</th><th>Verdict</th><th class="num">L</th>'
        '<th class="num">I</th><th>Risk</th><th class="hide-sm">Treatment</th><th>Action</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def _plan(rows: list[dict]) -> str:
    todo = [r for r in rows if r["status"] != "pass"]
    if not todo:
        return '<p class="small">Nothing to treat: every in-scope control passes.</p>'
    todo.sort(key=lambda r: (r["due"], -r["score"]))
    items = "".join(
        f'<li><span class="pill {r["level"]}">{r["level"]}</span> <b>{_e(r["title"])}</b> '
        f'<span class="id">{_e(r["id"])}</span><div>{_e(r["action"])}</div>'
        f'<div class="due">Owner: {_e(r["owner"])} &middot; due {_e(r["due"])}</div></li>'
        for r in todo
    )
    return f'<div class="card"><ol class="plan">{items}</ol></div>'


def _part_panel(pid: str, rows: list[dict], hidden: bool, extra_class: str = "") -> str:
    return (
        f'<section class="panel part {extra_class}" id="{pid}" role="tabpanel"{" hidden" if hidden else ""}>'
        f'<div class="grid2">{_heatmap(rows)}<div>{_kpis(rows)}<h3>Treatment plan</h3>{_plan(rows)}</div></div>'
        f"<h3>Risk register</h3>{_register(rows)}</section>"
    )


def _framework_panel(fw: dict, hidden: bool, sources: list[dict]) -> str:
    pid = "fw-" + fw["slug"]
    s = fw["score"]
    parts = [(f"{pid}-all", "All parts")] + [(f"{pid}-{_slug(p)}", p) for p in fw["parts"]]
    panels = [_part_panel(parts[0][0], fw["rows"], False, "part-all")]
    for (ppid, name) in parts[1:]:
        title = f'<h2 style="margin-top:8px">{_e(fw["short"])}: {_e(name)}</h2>'
        panel = _part_panel(ppid, [r for r in fw["rows"] if r["part"] == name], True)
        panels.append(panel.replace('role="tabpanel" hidden>', f'role="tabpanel" hidden><div class="print-only">{title}</div>', 1))
    src = [x for x in sources if fw["slug"] in x["frameworks"]]
    src_line = " &middot; ".join(
        f'{_e(x["name"])}: {"broken" if x["broken"] else "synced " + _e(x["last_success"][:10] or "never")}' for x in src
    )
    banner = ""
    if fw["open_changes"]:
        names = ", ".join(sorted({c["source_name"] for c in fw["open_changes"]}))
        banner = (
            f'<div class="banner"><b>Source changed, review open.</b> {len(fw["open_changes"])} unreviewed change(s) in {_e(names)}. '
            "Controls in this tab were written against the previous text; see the Regulation sources tab.</div>"
        )
    return (
        f'<section class="panel fw" id="{pid}" role="tabpanel"{" hidden" if hidden else ""}>'
        f'<div class="fw-head"><div><div class="eyebrow">{_e("Standard" if fw["kind"] == "iso" else "Law")}</div>'
        f'<h2>{_e(fw["framework"])}</h2><div class="meta">{_e(fw["reference"])}</div>'
        f'<div class="small" style="margin-top:6px;max-width:760px">{_e(fw["scope"])}</div>'
        f'<div class="small" style="margin-top:6px">{src_line}</div></div>'
        f'<div class="score-big"><div class="n">{_score_txt(s.get("score"))}</div>'
        f'<span class="band {_band_class(s.get("band"))}">{_e(s.get("band"))}</span></div></div>'
        f"{banner}{_tabs(parts, sub=True)}{''.join(panels)}</section>"
    )


def _overview(register: list[dict], scores: dict, hidden: bool) -> str:
    rows = []
    for fw in register:
        c = level_counts(fw["rows"])
        s = fw["score"]
        rows.append(
            f'<tr><td><b>{_e(fw["short"])}</b><div class="small">{_e(fw["reference"])}</div></td>'
            f'<td class="num">{_score_txt(s.get("score"))}</td><td><span class="band {_band_class(s.get("band"))}">{_e(s.get("band"))}</span></td>'
            + "".join(f'<td class="num">{c[k] or ""}</td>' for k in ("critical", "high", "medium", "low"))
            + f'<td class="num">{len(fw["open_changes"]) or ""}</td></tr>'
        )
    every = [r for fw in register for r in fw["rows"]]
    top = sorted((r for r in every if r["status"] != "pass"), key=lambda r: -r["score"])[:12]
    return (
        f'<section class="panel top" id="overview" role="tabpanel"{" hidden" if hidden else ""}>'
        f'<div class="grid2">{_heatmap(every)}<div>{_kpis(every)}'
        '<h3>Frameworks</h3><div class="tbl"><table><thead><tr><th>Framework</th><th class="num">Score</th><th>Band</th>'
        '<th class="num">Crit</th><th class="num">High</th><th class="num">Med</th><th class="num">Low</th><th class="num">Src changes</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></div></div>'
        f"<h3>Highest risks across all frameworks</h3>{_register(top)}</section>"
    )


def _egress_panel(egress: dict | None, hidden: bool) -> str:
    if not egress:
        return (
            f'<section class="panel top" id="egress" role="tabpanel"{" hidden" if hidden else ""}>'
            '<p class="small">No egress scan supplied. Run <code>python -m aicomply egress &lt;target&gt; --out egress.json</code> '
            "and pass it with <code>--egress</code>.</p></section>"
        )
    rows = "".join(
        f'<tr><td><b>{_e(d["vendor"])}</b><div class="small">{_e(", ".join(d["hosts"]))}</div>'
        f'<div class="small">{_e(d["note"])}</div></td><td>{_e(d["category"])}</td><td>{_e(d["region"])}</td>'
        f'<td>{_e(", ".join(d["data_hints"]) or "none seen")}</td>'
        f'<td class="num"><span class="pill {level(int(d["risk_score"]))}">{_e(d["risk_score"])} {level(int(d["risk_score"]))}</span></td>'
        f'<td class="small">{"<br>".join(_e(e["where"] + " (" + e["kind"] + ")") for e in d["evidence"][:6])}</td>'
        f'<td class="small" style="font-family:var(--mono)">{"<br>".join(_e(c) for c in d["controls"])}</td></tr>'
        for d in egress["destinations"]
    )
    settings = "".join(f'<li>{_e(s["setting"])} <span class="id">{_e(s["where"])}</span></li>' for s in egress["risky_settings"])
    skipped = "".join(f"<li>{_e(s)}</li>" for s in egress.get("skipped", []))
    sm = egress["summary"]
    return (
        f'<section class="panel top" id="egress" role="tabpanel"{" hidden" if hidden else ""}>'
        f'<div class="kpis"><div class="kpi"><div class="v">{_e(sm["destinations"])}</div><div class="l">destinations</div></div>'
        f'<div class="kpi critical"><div class="v">{_e(sm["non_eu_with_personal_data"])}</div><div class="l">non-EU with personal data</div></div>'
        f'<div class="kpi"><div class="v">{len(sm["llm_providers"])}</div><div class="l">LLM providers</div></div>'
        f'<div class="kpi high"><div class="v">{len(sm["unknown_destinations"])}</div><div class="l">unknown destinations</div></div></div>'
        f'<p class="small">Static scan of {_e(egress["files_scanned"])} files in {_e(egress["target"])}. Data hints are the personal data '
        "in reach of the call (same statement, or the same file for an SDK import or credential).</p>"
        '<div class="tbl"><table><thead><tr><th>Destination</th><th>Category</th><th>Region</th><th>Data in reach</th>'
        f'<th>Risk</th><th>Where</th><th>Controls</th></tr></thead><tbody>{rows}</tbody></table></div>'
        + (f"<h3>Risky settings</h3><div class=\"card\"><ul>{settings}</ul></div>" if settings else "")
        + (f"<h3>Not scanned</h3><div class=\"card\"><ul>{skipped}</ul></div>" if skipped else "")
        + "</section>"
    )


def _sources_panel(sources: list[dict], changes: list[tuple[str, dict]], hidden: bool) -> str:
    cards = []
    for s in sources:
        state = "".join(f"<li>{_e(line)}</li>" for line in s["current"][:14])
        more = f'<li>... {len(s["current"]) - 14} more</li>' if len(s["current"]) > 14 else ""
        status = "broken: " + _e(s["last_error"]) if s["broken"] else ("last synced " + _e(s["last_success"][:10]) if s["last_success"] else "never synced")
        cards.append(
            f'<div class="card" style="margin-bottom:10px"><b>{_e(s["name"])}</b> '
            f'<span class="small">{_e(s["strategy"])} &middot; {status} &middot; feeds {_e(", ".join(s["frameworks"]))}</span>'
            f'<ul class="state">{state}{more}</ul></div>'
        )
    change_html = "".join(
        f'<div class="card" style="margin-bottom:10px"><b>{_e(r["detection"]["source_name"])}</b> '
        f'<span class="pill {"high" if r["review"]["status"] in ("open", "in_review") else "low"}">{_e(r["review"]["status"])}</span> '
        f'<span class="small">detected {_e(r["detection"]["detected_at"][:10])} &middot; {len(r["detection"].get("impacted_controls", []))} controls to re-check &middot; {_e(name)}</span>'
        f'<pre class="diff">{_e(r["detection"]["diff"])}</pre>'
        + (f'<div class="small">Review note: {_e(r["review"]["note"])}</div>' if r["review"]["note"] else "")
        + "</div>"
        for name, r in reversed(changes)
    ) or '<p class="small">No changes detected since the baseline.</p>'
    return (
        f'<section class="panel top" id="sources" role="tabpanel"{" hidden" if hidden else ""}>'
        f"<h3>Detected changes</h3>{change_html}<h3>Watched sources</h3>{''.join(cards)}</section>"
    )


def render(register: list[dict], scores: dict, meta: dict, egress: dict | None,
           sources: list[dict], changes: list[tuple[str, dict]]) -> str:
    with open(CSS, encoding="utf-8") as f:
        css = f.read() + "\n.print-only{display:none}@media print{.print-only{display:block}}"
    tabs = [("overview", "Overview")] + [("fw-" + fw["slug"], fw["short"]) for fw in register]
    tabs += [("egress", "Data egress"), ("sources", "Regulation sources")]
    overall = scores["overall"]
    body = (
        _overview(register, scores, False)
        + "".join(_framework_panel(fw, True, sources) for fw in register)
        + _egress_panel(egress, True)
        + _sources_panel(sources, changes, True)
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Risk matrix: {_e(meta["system"])}</title><style>{css}</style></head>
<body><div class="wrap">
<header class="doc"><div><div class="eyebrow">AI compliance risk matrix</div><h1>{_e(meta["system"])}</h1>
<div class="meta">Assessed {_e(meta["date"])} &middot; {len(register)} frameworks &middot; {meta["assessed"]} of {meta["controls"]} controls assessed</div></div>
<div class="score-big"><div class="n">{_score_txt(overall["score"])}</div><span class="band {_band_class(overall["band"])}">{_e(overall["band"])}</span></div></header>
{_tabs(tabs)}
{body}
<footer class="doc">Likelihood: 1 {LIKELIHOOD_LABELS[1]} to 5 {LIKELIHOOD_LABELS[5]}. Impact: 2 {IMPACT_LABELS[2]} (low severity) to 5 {IMPACT_LABELS[5]} (critical).
Risk = likelihood x impact: 20-25 critical, 10-19 high, 5-9 medium, 1-4 low.</footer>
</div><script>{JS}</script></body></html>
"""
