"""Turn verdicts into a risk register and a treatment plan, per framework and per part.

Nothing here is typed in by hand. Impact comes from the control's severity,
likelihood from the verdict (and from the egress scan when data is seen
leaving), the level from their product, the deadline from the level.
See docs/risk-matrix.md for the model.
"""

from __future__ import annotations

from datetime import date, timedelta

IMPACT = {"critical": 5, "high": 4, "medium": 3, "low": 2}
LEVELS = ((20, "critical"), (10, "high"), (5, "medium"), (0, "low"))
DUE_DAYS = {"critical": 14, "high": 30, "medium": 90, "low": 180}
TREATMENT = {
    "critical": "Mitigate now, block release",
    "high": "Mitigate",
    "medium": "Mitigate",
    "low": "Mitigate, or accept with signed rationale",
}
LIKELIHOOD_LABELS = {1: "Rare", 2: "Unlikely", 3: "Possible", 4: "Likely", 5: "Almost certain"}
IMPACT_LABELS = {1: "Negligible", 2: "Minor", 3: "Moderate", 4: "Major", 5: "Severe"}


def level(score: int) -> str:
    return next(name for floor, name in LEVELS if score >= floor)


def likelihood(verdict: dict | None, egress_vendors: list[str]) -> tuple[int, str]:
    """(1-5, why). An unassessed control is not a safe control."""
    if verdict is None:
        return 3, "not assessed"
    status = verdict["status"]
    if status == "pass":
        return (2, "passes, but data flows to " + ", ".join(egress_vendors)) if egress_vendors else (1, "passes")
    if egress_vendors:
        return 5, "fails while data flows to " + ", ".join(egress_vendors)
    if verdict.get("gap") == "violating":
        return 5, "fails: violated today"
    return 4, "fails: control absent"


def build_register(frameworks: list[dict], findings: dict, egress_hits: dict[str, list[str]],
                   scores: dict, audit_date: date, open_changes: dict[str, list[dict]]) -> list[dict]:
    by_slug = {r["source"]: r for r in scores["frameworks"]}
    out = []
    for fw in frameworks:
        rows = []
        for ctrl in fw["controls"]:
            verdict = findings.get(ctrl["id"])
            if verdict is not None and verdict["status"] == "na":
                continue
            vendors = egress_hits.get(ctrl["id"], [])
            lk, why = likelihood(verdict, vendors)
            impact = IMPACT.get(ctrl.get("severity"), 3)
            score = lk * impact
            lvl = level(score)
            passing = verdict is not None and verdict["status"] == "pass"
            rows.append({
                "id": ctrl["id"],
                "title": ctrl.get("title", ""),
                "part": ctrl.get("part", "General"),
                "clause": ctrl.get("clause", ""),
                "severity": ctrl.get("severity", ""),
                "owner": ctrl.get("owner", ""),
                "status": verdict["status"] if verdict else "unassessed",
                "likelihood": lk,
                "likelihood_why": why,
                "impact": impact,
                "score": score,
                "level": lvl,
                "treatment": "Monitor" if passing else TREATMENT[lvl],
                "due": "" if passing else (audit_date + timedelta(days=DUE_DAYS[lvl])).isoformat(),
                "action": ctrl.get("advice", "") if not passing else "Keep the evidence current; re-test at the next audit.",
                "evidence": (verdict or {}).get("evidence", ""),
                "egress": vendors,
            })
        rows.sort(key=lambda r: (-r["score"], r["id"]))
        parts = list(dict.fromkeys(c.get("part", "General") for c in fw["controls"]))
        out.append({
            "slug": fw["source"],
            "short": fw.get("short", fw["source"]),
            "framework": fw.get("framework", ""),
            "reference": fw.get("reference", ""),
            "kind": fw.get("kind", ""),
            "scope": fw.get("scope", ""),
            "score": by_slug.get(fw["source"], {}),
            "parts": parts,
            "rows": rows,
            "open_changes": open_changes.get(fw["source"], []),
        })
    return out


def heatmap(rows: list[dict]) -> list[list[int]]:
    """grid[likelihood-1][impact-1] = number of risks (residual passes excluded)."""
    grid = [[0] * 5 for _ in range(5)]
    for r in rows:
        if r["status"] != "pass":
            grid[r["likelihood"] - 1][r["impact"] - 1] += 1
    return grid


def level_counts(rows: list[dict]) -> dict[str, int]:
    counts = {name: 0 for _, name in LEVELS}
    for r in rows:
        if r["status"] != "pass":
            counts[r["level"]] += 1
    return counts
