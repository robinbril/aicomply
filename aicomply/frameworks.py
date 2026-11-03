"""Load and validate the control catalogue in frameworks/*.yaml.

PyYAML is not in the standard library, and AIComply ships with zero
dependencies, so this reads the strict subset the catalogue is written in:
one `key: value` per line, values on a single line, controls as a list under
`controls:`. Anything outside that subset is reported by `validate`, never
silently dropped.
"""

from __future__ import annotations

import os

SEVERITY_WEIGHTS = {"critical": 5, "high": 3, "medium": 2, "low": 1}

TOP_FIELDS = ("framework", "reference", "short", "kind", "source", "scope")
CONTROL_FIELDS = (
    "id", "title", "part", "clause", "requirement", "applies_when", "severity",
    "weight", "check", "evidence", "advice", "owner",
)
KINDS = ("iso", "law")


def _value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def parse_framework(text: str, filename: str = "") -> dict:
    fw: dict = {"file": filename, "controls": [], "_problems": []}
    current = None
    in_controls = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not in_controls:
            if line.strip() == "controls:":
                in_controls = True
            elif ":" in line and not line.startswith(" "):
                key, raw = line.split(":", 1)
                fw[key.strip()] = _value(raw)
            continue
        if line.startswith("  - "):
            current = {"_line": lineno}
            fw["controls"].append(current)
            line = "    " + line[4:]
        if current is None or not line.startswith("    ") or ":" not in line:
            fw["_problems"].append(f"{filename}:{lineno}: unreadable line")
            continue
        key, raw = line.strip().split(":", 1)
        if raw.strip() in ("|", ">", "|-", ">-"):
            fw["_problems"].append(f"{filename}:{lineno}: block scalar in '{key}' is not supported")
            continue
        current[key] = _value(raw)
    for ctrl in fw["controls"]:
        if "weight" in ctrl:
            try:
                ctrl["weight"] = int(ctrl["weight"])
            except ValueError:
                fw["_problems"].append(f"{filename}: {ctrl.get('id')}: weight is not a number")
                ctrl["weight"] = 0
    fw.setdefault("source", os.path.splitext(os.path.basename(filename))[0])
    fw.setdefault("short", fw.get("framework", fw["source"]))
    return fw


def load_frameworks(frameworks_dir: str) -> list[dict]:
    frameworks = []
    for name in sorted(os.listdir(frameworks_dir)):
        if name.endswith((".yaml", ".yml")):
            with open(os.path.join(frameworks_dir, name), encoding="utf-8") as f:
                frameworks.append(parse_framework(f.read(), name))
    # ISO standards first, then laws, each alphabetical: the order of the report tabs.
    frameworks.sort(key=lambda fw: (fw.get("kind") != "iso", fw.get("short", "")))
    return frameworks


def validate(frameworks: list[dict]) -> list[str]:
    """Every problem in the catalogue, as human-readable lines. Empty means clean."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for fw in frameworks:
        problems.extend(fw["_problems"])
        name = fw["file"]
        for field in TOP_FIELDS:
            if not fw.get(field):
                problems.append(f"{name}: missing top-level '{field}'")
        if fw.get("kind") and fw["kind"] not in KINDS:
            problems.append(f"{name}: kind must be one of {KINDS}")
        if not fw["controls"]:
            problems.append(f"{name}: no controls")
        for ctrl in fw["controls"]:
            cid = ctrl.get("id", f"<line {ctrl['_line']}>")
            for field in CONTROL_FIELDS:
                if ctrl.get(field) in (None, ""):
                    problems.append(f"{name}: {cid}: missing '{field}'")
            severity = ctrl.get("severity")
            if severity not in SEVERITY_WEIGHTS:
                problems.append(f"{name}: {cid}: severity '{severity}' is not one of {list(SEVERITY_WEIGHTS)}")
            elif ctrl.get("weight") != SEVERITY_WEIGHTS[severity]:
                problems.append(f"{name}: {cid}: weight {ctrl.get('weight')} does not match severity {severity}")
            if cid in seen:
                problems.append(f"{name}: {cid}: id already used in {seen[cid]}")
            seen[cid] = name
    return problems


def control_index(frameworks: list[dict]) -> dict[str, tuple[dict, dict]]:
    """control id -> (framework, control)."""
    return {c["id"]: (fw, c) for fw in frameworks for c in fw["controls"] if "id" in c}
