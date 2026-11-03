"""The deterministic score. Same findings in, same numbers out.

A control is `pass`, `fail` or `na`. Nothing else earns or softens anything:
a control that is not built today is a `fail`, whatever a roadmap promises,
and a fix that lives on an unmerged branch is a `fail` until it is merged.
See docs/scoring.md.
"""

from __future__ import annotations

import json
import sys

from aicomply.frameworks import SEVERITY_WEIGHTS

CRITICAL_CAP = 39
VERDICTS = ("pass", "fail", "na")
GAPS = ("violating", "absent")

BANDS = (
    (90, "Compliant"),
    (70, "Substantial"),
    (40, "Partial"),
    (0, "Critical fail"),
)


def _normalise(cid: str, entry) -> dict:
    if isinstance(entry, str):
        entry = {"status": entry}
    verdict = dict(entry)
    status = str(verdict.get("status", verdict.get("result", ""))).lower()
    if status not in VERDICTS:
        print(
            f"WARNING: {cid}: status '{status}' is not a verdict; scored as fail. "
            "A control that is not built today is a fail.",
            file=sys.stderr,
        )
        verdict["status_original"] = status
        status = "fail"
    verdict["status"] = status
    if status == "fail" and verdict.get("gap") not in GAPS:
        verdict["gap"] = "absent"
    return verdict


def load_findings(path: str) -> dict[str, dict]:
    """Accepts a list of {id, status, ...} or an object keyed by control id."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        pairs = [(e["id"], e) for e in raw if isinstance(e, dict) and "id" in e]
    elif isinstance(raw, dict):
        pairs = list(raw.items())
    else:
        raise ValueError(f"{path}: expected a JSON list or object")
    seen = [cid for cid, _ in pairs]
    duplicates = sorted({cid for cid in seen if seen.count(cid) > 1})
    if duplicates:
        # A verifier's downgrade must never lose to a gatherer's pass further down the file.
        raise ValueError(f"{path}: one verdict per control id; duplicated: {', '.join(duplicates)}")
    findings = {cid: _normalise(cid, entry) for cid, entry in pairs}
    for cid, verdict in findings.items():
        if verdict["status"] == "na" and not str(verdict.get("evidence", verdict.get("reason", ""))).strip():
            print(f"WARNING: {cid}: na without a reason; scope is a decision, write why applies_when does not hold.",
                  file=sys.stderr)
    return findings


def band(score) -> str:
    if score is None:
        return "Out of scope"
    return next(name for floor, name in BANDS if score >= floor)


def score_framework(fw: dict, findings: dict[str, dict]) -> dict:
    earned = possible = 0
    critical_fails = []
    counts = {"pass": 0, "fail": 0, "na": 0, "unassessed": 0}
    for ctrl in fw["controls"]:
        verdict = findings.get(ctrl["id"])
        # No verdict is not "out of scope": an unassessed control counts as a fail
        # until someone looks at it. Only an explicit `na` with a reason drops out.
        status = verdict["status"] if verdict is not None else "unassessed"
        counts[status] += 1
        if status == "na":
            continue
        weight = SEVERITY_WEIGHTS.get(ctrl.get("severity"), ctrl.get("weight", 1))
        possible += weight
        if status == "pass":
            earned += weight
        elif ctrl.get("severity") == "critical":
            critical_fails.append({"id": ctrl["id"], "title": ctrl.get("title", ctrl["id"])})
    raw = round(100 * earned / possible, 1) if possible else None
    # One failed critical caps the framework: a leak cannot be averaged away.
    score = min(raw, CRITICAL_CAP) if (critical_fails and raw is not None) else raw
    return {
        "framework": fw.get("framework"),
        "short": fw.get("short"),
        "source": fw.get("source"),
        "reference": fw.get("reference"),
        "score": score,
        "raw_score": raw,
        "band": band(score),
        "capped": bool(critical_fails),
        "critical_fails": critical_fails,
        "counts": counts,
    }


def score_all(frameworks: list[dict], findings: dict[str, dict]) -> dict:
    results = [score_framework(fw, findings) for fw in frameworks]
    scored = [r["score"] for r in results if r["score"] is not None]
    overall = round(sum(scored) / len(scored), 1) if scored else None
    known = {c["id"] for fw in frameworks for c in fw["controls"]}
    return {
        "overall": {
            "score": overall,
            "band": band(overall),
            "critical_fails": [cf for r in results for cf in r["critical_fails"]],
            "frameworks_in_scope": len(scored),
        },
        "frameworks": results,
        "unknown_ids": sorted(set(findings) - known),
    }


def exit_code(result: dict) -> int:
    """1 when any in-scope framework has a critical fail or sits in the fail band."""
    bad = any(
        r["critical_fails"] or (r["score"] is not None and r["score"] < 40)
        for r in result["frameworks"]
    )
    return 1 if bad else 0
