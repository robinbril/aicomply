"""
score.py - Deterministic compliance scorer for aicomply.

Usage:
    python scripts/score.py <findings.json>
    python scripts/score.py --findings <findings.json> [--frameworks <dir>] [--report <out.md>]
    python scripts/score.py --test
    python scripts/score.py --help

findings.json accepts two shapes (same meaning, pick whichever your tooling emits):

  Array of verdicts (the format prompts/audit-prompt.md emits):
    [
      {"id": "GDPR-LAWFUL-BASIS", "status": "pass", "evidence": "..."},
      {"id": "AIA-CLASS",         "status": "fail", "evidence": "no inventory"},
      {"id": "AIMS-CONTEXT",      "status": "na"}
    ]

  Object keyed by control id:
    {
      "GDPR-LAWFUL-BASIS": {"status": "pass"},
      "AIA-CLASS":         "fail",
      "AIMS-CONTEXT":      {"status": "na"}
    }

Verdict key is "status" (legacy "result" is still accepted).
Status values: "pass" | "fail" | "na".

Reads all frameworks/*.yaml relative to the script's parent directory (override
with --frameworks). Prints a per-framework score table, critical-fail list, and
a machine-readable JSON block. With --report, also writes that summary to a file.

Score model (see frameworks/scoring.md, kept in sync with this file):
    earned   = sum(weight for c if status == "pass")
    possible = sum(weight for c if status in {"pass","fail"})
    raw      = 100 * earned / possible        # null if possible == 0
Any in-scope critical control that is "fail" caps that framework at 39.
Overall = unweighted mean of the non-null per-framework scores.

Exit code: 0 if every in-scope framework scores >= 40 with no critical fail, else 1.
"""

import json
import os
import sys

CRITICAL_CAP = 39

# Expected weights per severity level.
# Used to warn when a YAML control's weight deviates from the canonical mapping.
# Warnings go to stderr only and do NOT change the score.
SEVERITY_WEIGHTS = {
    "critical": 5,
    "high":     3,
    "medium":   2,
    "low":      1,
}


# yaml is stdlib-absent; parse the minimal subset we need with a hand-rolled reader.
# The YAML files use a strict structure: each control is a block under "controls:"
# with id, severity, weight fields, one value per line. We parse only what score.py
# needs; fields that don't match this format (e.g. multi-line block scalars) are
# skipped, with a stderr warning for the block-scalar case since that's silent
# otherwise.
def _parse_yaml_frameworks(frameworks_dir: str) -> list[dict]:
    """
    Minimal YAML parser for frameworks/*.yaml.
    Returns a list of framework dicts:
      {
        "framework": str,
        "reference": str,
        "scope": str,
        "controls": [{"id": str, "severity": str, "weight": int, "title": str}]
      }
    """
    results = []
    if not os.path.isdir(frameworks_dir):
        raise FileNotFoundError(f"frameworks dir not found: {frameworks_dir}")

    for fname in sorted(os.listdir(frameworks_dir)):
        if not fname.endswith(".yaml") and not fname.endswith(".yml"):
            continue
        fpath = os.path.join(frameworks_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as exc:
            print(f"WARNING: could not read {fpath}: {exc}", file=sys.stderr)
            continue

        fw: dict = {"framework": fname, "reference": "", "scope": "", "controls": []}
        current_control: dict | None = None
        in_controls = False

        for line in lines:
            stripped = line.rstrip()
            # top-level fields (not indented)
            if not stripped.startswith(" "):
                if stripped.startswith("framework:"):
                    fw["framework"] = stripped.split(":", 1)[1].strip().strip('"')
                    continue
                if stripped.startswith("reference:"):
                    fw["reference"] = stripped.split(":", 1)[1].strip().strip('"')
                    continue
                if stripped.startswith("scope:"):
                    fw["scope"] = stripped.split(":", 1)[1].strip().strip('"')
                    continue
                if stripped.strip() == "controls:":
                    in_controls = True
                    continue
            if not in_controls:
                continue
            # new control block starts with "  - id:"
            if stripped.startswith("  - id:"):
                if current_control is not None:
                    if "id" in current_control:
                        fw["controls"].append(current_control)
                    else:
                        print(
                            f"WARNING: control block in {fname} discarded (missing id)",
                            file=sys.stderr,
                        )
                current_control = {"id": stripped.split(":", 1)[1].strip().strip('"')}
                continue
            if current_control is None:
                continue
            if stripped.startswith("    title:"):
                current_control["title"] = stripped.split(":", 1)[1].strip().strip('"')
            elif stripped.startswith("    severity:"):
                current_control["severity"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("    weight:"):
                try:
                    current_control["weight"] = int(stripped.split(":", 1)[1].strip())
                except ValueError:
                    current_control["weight"] = 1
            elif stripped.lstrip().endswith((": |", ": >")) and ":" in stripped:
                # Block scalars (multi-line "requirement: |" / ">") aren't supported by
                # this minimal parser: the continuation lines don't match any of the
                # "    <field>:" prefixes above and would otherwise vanish silently.
                field = stripped.strip().split(":", 1)[0]
                print(
                    f"WARNING: {fname} control {current_control.get('id', '?')} uses a "
                    f"block scalar ('{field}: |' or '>') which this minimal parser cannot "
                    f"read; convert it to a single-line quoted string.",
                    file=sys.stderr,
                )

        if current_control is not None:
            if "id" in current_control:
                fw["controls"].append(current_control)
            else:
                print(
                    f"WARNING: control block in {fname} discarded (missing id)",
                    file=sys.stderr,
                )

        results.append(fw)

    return results


def _verdict(entry) -> dict:
    """Normalise a single finding entry to {"status": ...} plus any extra fields."""
    if isinstance(entry, str):
        return {"status": entry}
    if isinstance(entry, dict):
        return {**entry, "status": entry.get("status", entry.get("result", "unknown"))}
    return {"status": "unknown"}


def _load_findings(path: str) -> dict:
    """Load findings from either the array or the object shape into {id: {status,...}}."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    out: dict = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict) or "id" not in item:
                continue
            out[item["id"]] = _verdict(item)
    elif isinstance(raw, dict):
        for k, v in raw.items():
            out[k] = _verdict(v)
    else:
        raise ValueError("findings must be a JSON array of verdicts or an object keyed by id")
    return out


def score_framework(fw: dict, findings: dict) -> dict:
    """
    Returns:
    {
        "framework": str,
        "score": float | None,
        "raw_score": float | None,
        "pass_weight": int,
        "total_weight": int,
        "critical_fails": [{"id": str, "title": str}],
        "counts": {"pass": int, "fail": int, "na": int, "unknown": int},
        "capped": bool,
    }
    """
    pass_weight = 0
    total_weight = 0
    critical_fails = []
    counts = {"pass": 0, "fail": 0, "na": 0, "unknown": 0}

    for ctrl in fw["controls"]:
        cid = ctrl["id"]
        weight = ctrl.get("weight", 1)
        severity = ctrl.get("severity", "medium")

        # Warn if weight deviates from the canonical SEVERITY_WEIGHTS mapping.
        expected = SEVERITY_WEIGHTS.get(severity)
        if expected is not None and weight != expected:
            print(
                f"WARNING: {fw['framework']} control {cid} has weight={weight} "
                f"but severity={severity!r} expects weight={expected}",
                file=sys.stderr,
            )

        finding = findings.get(cid)

        if finding is None:
            # not in findings: treat as unknown (not na, not pass)
            counts["unknown"] += 1
            total_weight += weight
            continue

        status = str(finding.get("status", "unknown")).lower()

        if status == "na":
            counts["na"] += 1
            continue

        total_weight += weight

        if status == "pass":
            counts["pass"] += 1
            pass_weight += weight
        elif status == "fail":
            counts["fail"] += 1
            if severity == "critical":
                critical_fails.append({"id": cid, "title": ctrl.get("title", cid)})
        else:
            counts["unknown"] += 1

    if total_weight == 0:
        raw_score = None
    else:
        raw_score = round(100 * pass_weight / total_weight, 1)

    # Any failed in-scope critical caps the framework at CRITICAL_CAP, regardless
    # of the weighted mean. A single leak cannot be averaged away by green controls.
    capped = bool(critical_fails)
    score = min(raw_score, CRITICAL_CAP) if (capped and raw_score is not None and raw_score > CRITICAL_CAP) else raw_score

    return {
        "framework": fw["framework"],
        "score": score,
        "raw_score": raw_score,
        "pass_weight": pass_weight,
        "total_weight": total_weight,
        "critical_fails": critical_fails,
        "counts": counts,
        "capped": capped,
    }


def _band(score) -> str:
    if score is None:
        return "Out of scope"
    if score >= 90:
        return "Compliant"
    if score >= 70:
        return "Substantial"
    if score >= 40:
        return "Partial"
    return "Critical fail"


def overall_score(fw_results: list[dict]) -> dict:
    # Overall = unweighted mean of the post-cap per-framework scores that are not null.
    scored = [r["score"] for r in fw_results if r["score"] is not None]
    if not scored:
        score = None
    else:
        score = round(sum(scored) / len(scored), 1)
    all_critical_fails = []
    for r in fw_results:
        all_critical_fails.extend(r["critical_fails"])
    return {
        "score": score,
        "band": _band(score),
        "critical_fails": all_critical_fails,
        "capped": any(r["capped"] for r in fw_results),
    }


def _render(fw_results: list[dict], overall: dict) -> str:
    lines = []
    col_fw = max((len(r["framework"]) for r in fw_results), default=9) + 2
    header = (
        f"{'Framework':<{col_fw}}  {'Score':>6}  {'Raw':>6}  {'Band':<13}  "
        f"{'Capped':>6}  Counts (P/F/N/U)"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for r in fw_results:
        score_str = f"{r['score']:.1f}" if r["score"] is not None else "N/A"
        raw_str = f"{r['raw_score']:.1f}" if r["raw_score"] is not None else "N/A"
        capped_str = "YES" if r["capped"] else "no"
        c = r["counts"]
        counts_str = f"{c['pass']}/{c['fail']}/{c['na']}/{c['unknown']}"
        lines.append(
            f"{r['framework']:<{col_fw}}  {score_str:>6}  {raw_str:>6}  "
            f"{_band(r['score']):<13}  {capped_str:>6}  {counts_str}"
        )
    lines.append("-" * len(header))
    ov = f"{overall['score']:.1f}" if overall["score"] is not None else "N/A"
    lines.append(f"{'OVERALL':<{col_fw}}  {ov:>6}  {'':>6}  {overall['band']:<13}")

    if overall["critical_fails"]:
        lines.append(f"\nCRITICAL FAILS (each caps its framework score to <={CRITICAL_CAP}):")
        for cf in overall["critical_fails"]:
            lines.append(f"  [{cf['id']}] {cf['title']}")
    return "\n".join(lines)


def _machine(fw_results: list[dict], overall: dict, frameworks: list[dict]) -> dict:
    # Build a lookup from framework name to top-level metadata
    fw_meta = {fw["framework"]: fw for fw in frameworks}
    return {
        "overall": overall,
        "frameworks": [
            {
                "framework": r["framework"],
                "reference": fw_meta.get(r["framework"], {}).get("reference", ""),
                "scope": fw_meta.get(r["framework"], {}).get("scope", ""),
                "score": r["score"],
                "raw_score": r["raw_score"],
                "band": _band(r["score"]),
                "capped": r["capped"],
                "critical_fails": r["critical_fails"],
                "counts": r["counts"],
            }
            for r in fw_results
        ],
    }


def main(findings_path: str, frameworks_dir: str | None = None, report_path: str | None = None) -> int:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if frameworks_dir is None:
        frameworks_dir = os.path.join(script_dir, "..", "frameworks")

    frameworks = _parse_yaml_frameworks(frameworks_dir)
    findings = _load_findings(findings_path)

    fw_results = [score_framework(fw, findings) for fw in frameworks]
    overall = overall_score(fw_results)

    table = _render(fw_results, overall)
    machine = _machine(fw_results, overall, frameworks)
    machine_json = json.dumps(machine, indent=2)

    print(table)
    print("\n--- machine JSON ---")
    print(machine_json)

    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# Compliance score\n\n```\n")
            f.write(table)
            f.write("\n```\n\n## Machine JSON\n\n```json\n")
            f.write(machine_json)
            f.write("\n```\n")
        print(f"\nReport written to {report_path}", file=sys.stderr)

    # exit 1 if any in-scope framework has a critical fail or scores below 40
    failed = any(
        r["critical_fails"] or (r["score"] is not None and r["score"] < 40)
        for r in fw_results
    )
    return 1 if failed else 0


USAGE = (
    "Usage:\n"
    "  python score.py <findings.json>\n"
    "  python score.py --findings <findings.json> [--frameworks <dir>] [--report <out.md>]\n"
    "  python score.py --test\n"
    "  python score.py --help\n\n"
    "findings.json: a JSON array of {id,status,...} verdicts, or an object keyed by\n"
    "control id. status is one of pass | fail | na (legacy key 'result' also works).\n"
)


def _parse_args(argv: list[str]) -> dict:
    """Tiny flag parser: supports positional findings path and --findings/--frameworks/--report."""
    opts = {"findings": None, "frameworks": None, "report": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--findings", "--frameworks", "--report"):
            if i + 1 >= len(argv):
                raise ValueError(f"{a} requires a value")
            opts[a[2:]] = argv[i + 1]
            i += 2
        elif a.startswith("--"):
            raise ValueError(f"unknown flag: {a}")
        else:
            if opts["findings"] is not None:
                raise ValueError(f"unexpected extra argument: {a}")
            opts["findings"] = a
            i += 1
    return opts


# ---------------------------------------------------------------------------
# Self-test: runs without external input using an inline fixture
# ---------------------------------------------------------------------------
def _self_test() -> None:
    import tempfile

    fake_yaml = """framework: "Test Framework"
reference: "Test Reference"
scope: "Test Scope"
controls:
  - id: "TEST-CRIT"
    title: "Critical control"
    severity: critical
    weight: 5
    check: "check crit"
  - id: "TEST-HIGH"
    title: "High control"
    severity: high
    weight: 3
    check: "check high"
  - id: "TEST-MED"
    title: "Medium control"
    severity: medium
    weight: 2
    check: "check med"
  - id: "TEST-NA"
    title: "NA control"
    severity: low
    weight: 1
    check: "check na"
"""

    findings_pass_all = {
        "TEST-CRIT": {"status": "pass"},
        "TEST-HIGH": {"status": "pass"},
        "TEST-MED": {"status": "pass"},
        "TEST-NA": {"status": "na"},
    }
    findings_crit_fail = {
        "TEST-CRIT": {"status": "fail"},
        "TEST-HIGH": {"status": "pass"},
        "TEST-MED": {"status": "pass"},
        "TEST-NA": {"status": "na"},
    }
    # legacy "result" key + bare string + array shape must all still parse
    findings_array = [
        {"id": "TEST-CRIT", "result": "fail"},
        {"id": "TEST-HIGH", "status": "pass"},
        {"id": "TEST-MED", "status": "pass"},
        {"id": "TEST-NA", "status": "na"},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        fw_path = os.path.join(tmpdir, "test.yaml")
        with open(fw_path, "w", encoding="utf-8") as f:
            f.write(fake_yaml)

        frameworks = _parse_yaml_frameworks(tmpdir)
        assert len(frameworks) == 1, "expected 1 framework"
        fw = frameworks[0]
        assert len(fw["controls"]) == 4, f"expected 4 controls, got {len(fw['controls'])}"

        # Verify top-level metadata is captured
        assert fw["reference"] == "Test Reference", f"expected reference, got {fw['reference']}"
        assert fw["scope"] == "Test Scope", f"expected scope, got {fw['scope']}"

        # All pass (NA dropped): score = 100 * (5+3+2)/(5+3+2) = 100
        r = score_framework(fw, findings_pass_all)
        assert r["score"] == 100.0, f"expected 100, got {r['score']}"
        assert not r["capped"], "should not be capped"
        assert r["critical_fails"] == [], "no critical fails expected"

        # Critical fail: raw = 100*(3+2)/(5+3+2) = 50.0, capped to 39
        r2 = score_framework(fw, findings_crit_fail)
        assert r2["raw_score"] == 50.0, f"expected raw 50.0, got {r2['raw_score']}"
        assert r2["critical_fails"][0]["id"] == "TEST-CRIT", "critical fail not detected"
        assert r2["capped"], "should be capped"
        assert r2["score"] == CRITICAL_CAP, f"expected {CRITICAL_CAP} (capped), got {r2['score']}"
        assert _band(r2["score"]) == "Critical fail", "capped framework must be Critical fail band"

        # Cap applies even when raw is already below the cap: capped=True, score stays 0.0.
        r3 = score_framework(fw, {"TEST-CRIT": {"status": "fail"}})
        assert r3["raw_score"] == 0.0, f"expected raw 0.0, got {r3['raw_score']}"
        assert r3["critical_fails"], "critical fail must be recorded"
        assert r3["capped"], "capped must be True whenever there are critical_fails"
        assert r3["score"] == 0.0, f"expected 0.0, got {r3['score']}"

        # Array shape + legacy result key parses identically to the dict shape.
        af_path = os.path.join(tmpdir, "findings.json")
        with open(af_path, "w", encoding="utf-8") as f:
            json.dump(findings_array, f)
        loaded = _load_findings(af_path)
        r4 = score_framework(fw, loaded)
        assert r4["score"] == CRITICAL_CAP, f"array shape: expected {CRITICAL_CAP}, got {r4['score']}"

        # Verify _machine includes reference and scope in output
        fw_results = [r4]
        overall = overall_score(fw_results)
        m = _machine(fw_results, overall, frameworks)
        assert m["frameworks"][0]["reference"] == "Test Reference", "reference missing from machine output"
        assert m["frameworks"][0]["scope"] == "Test Scope", "scope missing from machine output"

    # Flag parser
    assert _parse_args(["f.json"])["findings"] == "f.json"
    assert _parse_args(["--findings", "f.json", "--report", "r.md"])["report"] == "r.md"

    print("Self-test PASSED")


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] in ("--test", "-t"):
        _self_test()
        sys.exit(0)

    if not args:
        print(USAGE, file=sys.stderr)
        sys.exit(2)

    if args[0] in ("--help", "-h"):
        print(USAGE)
        sys.exit(0)

    try:
        opts = _parse_args(args)
    except ValueError as e:
        print(f"error: {e}\n\n{USAGE}", file=sys.stderr)
        sys.exit(2)

    if not opts["findings"]:
        print(f"error: no findings file given\n\n{USAGE}", file=sys.stderr)
        sys.exit(2)

    sys.exit(main(opts["findings"], opts["frameworks"], opts["report"]))
