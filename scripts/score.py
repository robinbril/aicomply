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
import subprocess
import sys

CRITICAL_CAP = 39

# Roadmap credit (opt-in via --roadmap-credit). A control that is not built yet but is
# committed to in a tracked repo document earns PLANNED_CREDIT of its weight. A critical
# that is only planned (never violated today) caps the framework at PLANNED_CRITICAL_CAP
# instead of CRITICAL_CAP, so it can reach "Partial" but never "Substantial".
PLANNED_CREDIT = 0.75
PLANNED_CRITICAL_CAP = 79

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
# with id, severity, weight fields. We parse only what score.py needs.
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


def _quote_in(text: str, quote) -> bool:
    return " ".join(str(quote).split()) in " ".join(text.split())


def _roadmap_ok(finding: dict, repo_root: str | None) -> tuple[bool, str]:
    """A `planned` verdict earns credit only if its evidence checks out in the repo.

    gap "absent": nothing exists yet, a tracked file documents the plan.
    gap "fixed-unmerged": the fix exists on another branch/ref that is not merged yet;
    roadmap_ref.ref names that branch or sha and the file is read from it.
    gap "violating": built wrongly or violated today with no fix anywhere; never credited.
    """
    gap = finding.get("gap")
    if gap not in ("absent", "fixed-unmerged"):
        return False, "gap must be 'absent' or 'fixed-unmerged': a control violated today with no fix is not offset by a roadmap"
    ref = finding.get("roadmap_ref")
    if not isinstance(ref, dict) or not ref.get("path") or not ref.get("quote"):
        return False, "roadmap_ref needs path and quote"
    git_ref = ref.get("ref")
    if gap == "fixed-unmerged" and not git_ref:
        return False, "fixed-unmerged needs roadmap_ref.ref (the branch or sha holding the fix)"
    if repo_root is None:
        return False, "--repo is required to verify roadmap_ref"
    rel = ref["path"]

    if git_ref:
        try:
            proc = subprocess.run(
                ["git", "-C", repo_root, "show", f"{git_ref}:{rel}"], capture_output=True
            )
        except OSError:
            return False, "git is not available to read the ref"
        if proc.returncode != 0:
            return False, f"{rel} not found in {git_ref}"
        if not _quote_in(proc.stdout.decode("utf-8", "replace"), ref["quote"]):
            return False, f"quote not found verbatim in {git_ref}:{rel}"
        return True, ""

    full = os.path.join(repo_root, rel)
    if not os.path.isfile(full):
        return False, f"{rel} not found in repo"
    with open(full, encoding="utf-8", errors="replace") as f:
        if not _quote_in(f.read(), ref["quote"]):
            return False, f"quote not found verbatim in {rel}"
    try:
        tracked = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--error-unmatch", rel],
            capture_output=True,
        ).returncode == 0
    except OSError:
        tracked = False
    if not tracked:
        return False, f"{rel} is not tracked in git"
    return True, ""


def score_framework(
    fw: dict, findings: dict, roadmap_credit: bool = False, repo_root: str | None = None
) -> dict:
    """
    Returns framework, score (roadmap-adjusted when roadmap_credit is on), strict_score
    (every `planned` treated as `fail`), raw_score, pass_weight, planned_weight,
    total_weight, critical_fails (cap drivers), planned_criticals, rejected_planned,
    counts and capped.
    """
    pass_weight = 0
    planned_weight = 0
    total_weight = 0
    critical_fails = []
    planned_criticals = []
    rejected_planned = []
    counts = {"pass": 0, "fail": 0, "planned": 0, "na": 0, "unknown": 0}

    for ctrl in fw["controls"]:
        cid = ctrl["id"]
        weight = ctrl.get("weight", 1)
        severity = ctrl.get("severity", "medium")
        entry = {"id": cid, "title": ctrl.get("title", cid)}

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

        if status == "planned":
            ok, reason = _roadmap_ok(finding, repo_root) if roadmap_credit else (False, "")
            if ok:
                counts["planned"] += 1
                planned_weight += weight
                if severity == "critical":
                    planned_criticals.append(entry)
                continue
            if roadmap_credit:
                rejected_planned.append({**entry, "reason": reason})
            status = "fail"

        if status == "pass":
            counts["pass"] += 1
            pass_weight += weight
        elif status == "fail":
            counts["fail"] += 1
            if severity == "critical":
                critical_fails.append(entry)
        else:
            counts["unknown"] += 1

    if total_weight == 0:
        raw_score = None
        strict_raw = None
    else:
        raw_score = round(100 * (pass_weight + PLANNED_CREDIT * planned_weight) / total_weight, 1)
        strict_raw = round(100 * pass_weight / total_weight, 1)

    # An unplanned failed critical caps the framework at CRITICAL_CAP. A critical that is
    # only planned caps at PLANNED_CRITICAL_CAP. A single leak cannot be averaged away.
    cap = CRITICAL_CAP if critical_fails else PLANNED_CRITICAL_CAP if planned_criticals else None
    score = min(raw_score, cap) if (cap is not None and raw_score is not None) else raw_score
    strict_capped = bool(critical_fails or planned_criticals)
    strict_score = (
        min(strict_raw, CRITICAL_CAP) if (strict_capped and strict_raw is not None) else strict_raw
    )

    return {
        "framework": fw["framework"],
        "score": score,
        "strict_score": strict_score,
        "raw_score": raw_score,
        "pass_weight": pass_weight,
        "planned_weight": planned_weight,
        "total_weight": total_weight,
        "critical_fails": critical_fails,
        "planned_criticals": planned_criticals,
        "rejected_planned": rejected_planned,
        "counts": counts,
        "capped": cap is not None,
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
    def mean(key: str):
        vals = [r[key] for r in fw_results if r[key] is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    score = mean("score")
    strict = mean("strict_score")
    critical_fails = [cf for r in fw_results for cf in r["critical_fails"]]
    planned_criticals = [pc for r in fw_results for pc in r["planned_criticals"]]
    return {
        "score": score,
        "band": _band(score),
        "strict_score": strict,
        "strict_band": _band(strict),
        "critical_fails": critical_fails,
        "planned_criticals": planned_criticals,
        "capped": any(r["capped"] for r in fw_results),
    }


def _render(fw_results: list[dict], overall: dict, roadmap_credit: bool = False) -> str:
    lines = []
    col_fw = max((len(r["framework"]) for r in fw_results), default=9) + 2
    strict_hdr = f"  {'Strict':>6}" if roadmap_credit else ""
    counts_hdr = "Counts (P/F/R/N/U)" if roadmap_credit else "Counts (P/F/N/U)"
    header = (
        f"{'Framework':<{col_fw}}  {'Score':>6}{strict_hdr}  {'Raw':>6}  {'Band':<13}  "
        f"{'Capped':>6}  {counts_hdr}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    def fmt(v):
        return f"{v:.1f}" if v is not None else "N/A"

    for r in fw_results:
        c = r["counts"]
        counts_str = (
            f"{c['pass']}/{c['fail']}/{c['planned']}/{c['na']}/{c['unknown']}"
            if roadmap_credit
            else f"{c['pass']}/{c['fail']}/{c['na']}/{c['unknown']}"
        )
        strict_col = f"  {fmt(r['strict_score']):>6}" if roadmap_credit else ""
        lines.append(
            f"{r['framework']:<{col_fw}}  {fmt(r['score']):>6}{strict_col}  {fmt(r['raw_score']):>6}  "
            f"{_band(r['score']):<13}  {'YES' if r['capped'] else 'no':>6}  {counts_str}"
        )
    lines.append("-" * len(header))
    strict_col = f"  {fmt(overall['strict_score']):>6}" if roadmap_credit else ""
    lines.append(
        f"{'OVERALL':<{col_fw}}  {fmt(overall['score']):>6}{strict_col}  {'':>6}  {overall['band']:<13}"
    )
    if roadmap_credit:
        lines.append(
            f"\nScore = roadmap-adjusted (planned earns {int(PLANNED_CREDIT * 100)}% of its weight). "
            f"Strict = every planned control counted as fail ({overall['strict_band']})."
        )

    if overall["critical_fails"]:
        lines.append(f"\nCRITICAL FAILS (each caps its framework score to <={CRITICAL_CAP}):")
        for cf in overall["critical_fails"]:
            lines.append(f"  [{cf['id']}] {cf['title']}")
    if overall["planned_criticals"]:
        lines.append(
            f"\nPLANNED CRITICALS (documented, not built; each caps its framework to <={PLANNED_CRITICAL_CAP}):"
        )
        for pc in overall["planned_criticals"]:
            lines.append(f"  [{pc['id']}] {pc['title']}")
    rejected = [rp for r in fw_results for rp in r["rejected_planned"]]
    if rejected:
        lines.append("\nREJECTED ROADMAP CLAIMS (scored as fail):")
        for rp in rejected:
            lines.append(f"  [{rp['id']}] {rp['reason']}")
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
                "strict_score": r["strict_score"],
                "raw_score": r["raw_score"],
                "band": _band(r["score"]),
                "capped": r["capped"],
                "critical_fails": r["critical_fails"],
                "planned_criticals": r["planned_criticals"],
                "rejected_planned": r["rejected_planned"],
                "counts": r["counts"],
            }
            for r in fw_results
        ],
    }


def main(
    findings_path: str,
    frameworks_dir: str | None = None,
    report_path: str | None = None,
    roadmap_credit: bool = False,
    repo_root: str | None = None,
) -> int:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if frameworks_dir is None:
        frameworks_dir = os.path.join(script_dir, "..", "frameworks")

    frameworks = _parse_yaml_frameworks(frameworks_dir)
    findings = _load_findings(findings_path)

    fw_results = [score_framework(fw, findings, roadmap_credit, repo_root) for fw in frameworks]
    overall = overall_score(fw_results)

    table = _render(fw_results, overall, roadmap_credit)
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

    # exit 1 if any in-scope framework has an unplanned critical fail or scores below 40
    failed = any(
        r["critical_fails"] or (r["score"] is not None and r["score"] < 40)
        for r in fw_results
    )
    return 1 if failed else 0


USAGE = (
    "Usage:\n"
    "  python score.py <findings.json>\n"
    "  python score.py --findings <findings.json> [--frameworks <dir>] [--report <out.md>]\n"
    "                  [--roadmap-credit --repo <repo root>]\n"
    "  python score.py --test\n"
    "  python score.py --help\n\n"
    "findings.json: a JSON array of {id,status,...} verdicts, or an object keyed by\n"
    "control id. status is one of pass | fail | na | planned (legacy key 'result' also works).\n"
    "planned only earns credit with --roadmap-credit --repo, see frameworks/scoring.md.\n"
)


def _parse_args(argv: list[str]) -> dict:
    """Tiny flag parser: positional findings path, value flags, and the --roadmap-credit switch."""
    opts = {"findings": None, "frameworks": None, "report": None, "repo": None, "roadmap_credit": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--roadmap-credit":
            opts["roadmap_credit"] = True
            i += 1
        elif a in ("--findings", "--frameworks", "--report", "--repo"):
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
    if opts["roadmap_credit"] and not opts["repo"]:
        raise ValueError("--roadmap-credit requires --repo <repo root> to verify the roadmap evidence")
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

    # Roadmap credit: a planned control needs a verbatim quote from a git-tracked repo file.
    with tempfile.TemporaryDirectory() as repo:
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
        with open(os.path.join(repo, "ROADMAP.md"), "w", encoding="utf-8") as f:
            f.write("Fase 4: DPIA en verwerkersregister opleveren voor Q4.\n")
        with open(os.path.join(repo, "untracked.md"), "w", encoding="utf-8") as f:
            f.write("Fase 9: DPIA.\n")
        subprocess.run(["git", "-C", repo, "add", "ROADMAP.md"], check=True)
        fw_rm = {
            "framework": "RM",
            "controls": [
                {"id": "C", "severity": "critical", "weight": 5},
                {"id": "H", "severity": "high", "weight": 3},
                {"id": "M", "severity": "medium", "weight": 2},
            ],
        }
        good = {"status": "planned", "gap": "absent",
                "roadmap_ref": {"path": "ROADMAP.md", "quote": "DPIA en verwerkersregister"}}
        base = {"H": {"status": "pass"}, "M": {"status": "pass"}}

        # valid roadmap: raw = 100*(3+2+0.75*5)/10 = 87.5, planned critical caps at 79, strict stays 39
        r = score_framework(fw_rm, {**base, "C": good}, True, repo)
        assert r["score"] == PLANNED_CRITICAL_CAP, f"planned critical cap: got {r['score']}"
        assert r["strict_score"] == CRITICAL_CAP, f"strict must ignore the roadmap: got {r['strict_score']}"
        assert r["critical_fails"] == [] and len(r["planned_criticals"]) == 1

        # planned without --roadmap-credit is a plain fail
        r = score_framework(fw_rm, {**base, "C": good}, False, repo)
        assert r["score"] == CRITICAL_CAP and r["counts"]["planned"] == 0

        # every faked or weak claim is rejected and scored as fail
        bad_claims = [
            {**good, "roadmap_ref": {"path": "ROADMAP.md", "quote": "iets dat er niet staat"}},
            {**good, "roadmap_ref": {"path": "untracked.md", "quote": "DPIA"}},
            {**good, "roadmap_ref": {"path": "missing.md", "quote": "DPIA"}},
            {**good, "gap": "violating"},
            {"status": "planned", "gap": "absent"},
        ]
        for bad in bad_claims:
            r = score_framework(fw_rm, {**base, "C": bad}, True, repo)
            assert r["score"] == CRITICAL_CAP, f"bad claim must fail: {bad}"
            assert r["rejected_planned"], f"bad claim must be reported: {bad}"

    # fixed-unmerged: the fix lives on another branch, read from that ref
    with tempfile.TemporaryDirectory() as repo:
        def git(*a):
            subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        with open(os.path.join(repo, "a.txt"), "w", encoding="utf-8") as f:
            f.write("main\n")
        git("add", "a.txt")
        git("commit", "-q", "-m", "init")
        git("checkout", "-q", "-b", "fix/redactie")
        with open(os.path.join(repo, "redactie.md"), "w", encoding="utf-8") as f:
            f.write("Namen worden geredigeerd voor elke LLM-call.\n")
        git("add", "redactie.md")
        git("commit", "-q", "-m", "fix")
        git("checkout", "-q", "main")
        fw_fx = {"framework": "FX", "controls": [
            {"id": "C", "severity": "critical", "weight": 5},
            {"id": "H", "severity": "high", "weight": 3},
        ]}
        fixed = {"status": "planned", "gap": "fixed-unmerged",
                 "roadmap_ref": {"path": "redactie.md", "quote": "Namen worden geredigeerd", "ref": "fix/redactie"}}
        r = score_framework(fw_fx, {"H": {"status": "pass"}, "C": fixed}, True, repo)
        assert r["score"] == PLANNED_CRITICAL_CAP and not r["rejected_planned"], f"fixed-unmerged must earn credit: {r}"
        assert r["strict_score"] == 37.5, "strict must ignore an unmerged fix (3/8, below the cap)"
        for bad in (
            {**fixed, "roadmap_ref": {**fixed["roadmap_ref"], "ref": "no-such-branch"}},
            {**fixed, "roadmap_ref": {**fixed["roadmap_ref"], "quote": "niet aanwezig"}},
            {**fixed, "roadmap_ref": {"path": "redactie.md", "quote": "Namen worden geredigeerd"}},
        ):
            r = score_framework(fw_fx, {"H": {"status": "pass"}, "C": bad}, True, repo)
            assert r["score"] == 37.5 and r["rejected_planned"] and r["critical_fails"], f"bad fixed-unmerged claim: {bad}"

    assert _parse_args(["f.json", "--roadmap-credit", "--repo", "r"])["roadmap_credit"] is True
    try:
        _parse_args(["f.json", "--roadmap-credit"])
        raise AssertionError("--roadmap-credit without --repo must be rejected")
    except ValueError:
        pass

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

    sys.exit(
        main(
            opts["findings"],
            opts["frameworks"],
            opts["report"],
            opts["roadmap_credit"],
            opts["repo"],
        )
    )
