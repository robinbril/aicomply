"""Check every due source, keep a baseline, and log what moved.

Three outcomes per source: unchanged, changed, broken. A broken check never
becomes the new baseline: the last good text and hash stay, so the first real
change after a repair still diffs against something sane.

State lives in registry/state.json (the baseline, committed), change records
in registry/changes/ (append-only: one file per detection, the detection part
is frozen, only the review part may move). Nothing here writes to frameworks/.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from aicomply.regsync.fetchers import FetchError, default_fetchers

FAILURE_THRESHOLD = 3  # one hiccup is normal, three in a row is a pattern
MAX_SHRINK = 0.6  # a page that loses 60% of its text is a broken fetch, not a change
RETRY_AFTER_FAILURE_DAYS = 1
REVIEW_STATUSES = ("open", "in_review", "processed", "not_relevant")
INTERVAL_TOLERANCE = timedelta(hours=12)


@dataclass
class Outcome:
    source: str
    result: str  # unchanged | changed | broken | new
    reason: str = ""
    change_file: str = ""


@dataclass
class SyncReport:
    outcomes: list = field(default_factory=list)

    def by(self, result: str) -> list:
        return [o for o in self.outcomes if o.result == result]


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_sources(registry_dir: str) -> list[dict]:
    return load_json(os.path.join(registry_dir, "sources.json"), {"sources": []})["sources"]


def is_due(source: dict, state: dict, now: datetime) -> bool:
    if not source.get("active", True):
        return False
    last = _parse(state.get("last_check"))
    if last is None:
        return True
    days = RETRY_AFTER_FAILURE_DAYS if state.get("failures") else source.get("interval_days", 7)
    # A weekly schedule that starts a few minutes early must not skip the week.
    return now - last >= timedelta(days=days) - INTERVAL_TOLERANCE


def text_diff(old: str, new: str, max_lines: int = 60) -> str:
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "previous", "current", lineterm=""))
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... ({len(diff) - max_lines} more lines)"]
    return "\n".join(diff)


def impacted_controls(source: dict, frameworks: list[dict]) -> list[dict]:
    slugs = set(source.get("frameworks", []))
    return [
        {"framework": fw["source"], "id": c["id"], "clause": c.get("clause", "")}
        for fw in frameworks
        if fw["source"] in slugs
        for c in fw["controls"]
    ]


def check_source(source: dict, state: dict, fetcher, now: datetime, accept_shrink: bool = False) -> tuple[dict, Outcome, dict | None]:
    """Returns (new_state, outcome, change_record_or_None). Pure apart from the fetch.

    `accept_shrink` is the way out of the shrink guard after a real restructure or
    repeal: the shrunken text is then recorded as a change instead of a failure.
    """
    state = dict(state)
    state["last_check"] = _iso(now)
    try:
        text = fetcher.fetch(source)
        old = state.get("text", "")
        if old and not accept_shrink and len(text) < len(old) * (1 - MAX_SHRINK):
            raise FetchError(
                f"suspicious shrink {len(old)} -> {len(text)} chars; baseline kept to avoid poisoning it"
            )
    except Exception as exc:  # noqa: BLE001 - one dead source must never abort or hide the run
        reason = exc.reason if isinstance(exc, FetchError) else f"unexpected {type(exc).__name__}: {exc}"
        exc = FetchError(reason)
        state["failures"] = state.get("failures", 0) + 1
        state["broken"] = state["failures"] >= FAILURE_THRESHOLD
        state["last_error"] = exc.reason
        return state, Outcome(source["id"], "broken", exc.reason), None

    new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    old_hash = state.get("hash")
    record = None
    if old_hash is None:
        result = "new"
    elif new_hash == old_hash:
        result = "unchanged"
    else:
        result = "changed"
        record = {
            "detection": {
                "source": source["id"],
                "source_name": source["name"],
                "detected_at": _iso(now),
                "old_hash": old_hash,
                "new_hash": new_hash,
                "diff": text_diff(state.get("text", ""), text),
                "frameworks": source.get("frameworks", []),
            },
            "review": {"status": "open", "reviewer": "", "reviewed_at": "", "note": ""},
        }
        state["last_change"] = _iso(now)
    state.update(hash=new_hash, text=text, last_success=_iso(now), failures=0, broken=False, last_error="")
    return state, Outcome(source["id"], result), record


def run_sync(
    registry_dir: str,
    frameworks: list[dict],
    only: str | None = None,
    dry_run: bool = False,
    fetchers: dict | None = None,
    now: datetime | None = None,
    force: bool = False,
    accept_shrink: bool = False,
) -> SyncReport:
    now = now or now_utc()
    fetchers = fetchers or default_fetchers()
    state_path = os.path.join(registry_dir, "state.json")
    all_state = load_json(state_path, {})
    report = SyncReport()
    for source in load_sources(registry_dir):
        if only and source["id"] != only:
            continue
        current = all_state.get(source["id"], {})
        if not (force or is_due(source, current, now)):
            continue
        new_state, outcome, record = check_source(
            source, current, fetchers[source["strategy"]], now, accept_shrink=accept_shrink
        )
        if record is not None:
            record["detection"]["impacted_controls"] = impacted_controls(source, frameworks)
            name = f"{now:%Y-%m-%dT%H%M%SZ}-{source['id']}-{record['detection']['new_hash'][:8]}.json"
            outcome.change_file = os.path.join("changes", name)
            if not dry_run:
                path = os.path.join(registry_dir, "changes", name)
                if os.path.exists(path):
                    raise FileExistsError(f"{path} already exists; a detection record is never overwritten")
                write_json(path, record)
        all_state[source["id"]] = new_state
        report.outcomes.append(outcome)
    if not dry_run:
        write_json(state_path, all_state)
    return report


# --- change records ---------------------------------------------------------


def list_changes(registry_dir: str, status: str | None = None) -> list[tuple[str, dict]]:
    folder = os.path.join(registry_dir, "changes")
    out = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            record = load_json(os.path.join(folder, name), {})
            if status is None or record.get("review", {}).get("status") == status:
                out.append((name, record))
    return out


def open_changes_by_framework(registry_dir: str) -> dict[str, list[dict]]:
    """framework slug -> open change detections (for the report and the matrix)."""
    out: dict[str, list[dict]] = {}
    for name, record in list_changes(registry_dir):
        if record["review"]["status"] in ("open", "in_review"):
            for slug in record["detection"].get("frameworks", []):
                out.setdefault(slug, []).append({"file": name, **record["detection"]})
    return out


def review_change(registry_dir: str, name: str, status: str, reviewer: str, note: str, now=None) -> dict:
    """Moves only the review half of a record. The detection half is frozen."""
    if status not in REVIEW_STATUSES:
        raise ValueError(f"status must be one of {REVIEW_STATUSES}")
    path = os.path.join(registry_dir, "changes", os.path.basename(name))
    record = load_json(path, None)
    if record is None:
        raise FileNotFoundError(path)
    record["review"] = {
        "status": status,
        "reviewer": reviewer,
        "reviewed_at": _iso(now or now_utc()),
        "note": note,
    }
    write_json(path, record)
    return record


def _summary_lines(source: dict, text: str) -> list[str]:
    if source["strategy"] == "html":
        return [text[:240] + ("..." if len(text) > 240 else "")] if text else []
    return text.splitlines()[1:]


def source_status(registry_dir: str) -> list[dict]:
    state = load_json(os.path.join(registry_dir, "state.json"), {})
    rows = []
    for s in load_sources(registry_dir):
        st = state.get(s["id"], {})
        rows.append({
            "id": s["id"],
            "name": s["name"],
            "strategy": s["strategy"],
            "frameworks": s.get("frameworks", []),
            "active": s.get("active", True),
            "last_success": st.get("last_success", ""),
            "last_change": st.get("last_change", ""),
            "broken": st.get("broken", False),
            "failures": st.get("failures", 0),
            "last_error": st.get("last_error", ""),
            "current": _summary_lines(s, st.get("text") or ""),
        })
    return rows
