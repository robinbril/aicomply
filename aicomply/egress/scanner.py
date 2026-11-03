"""Find every outbound destination in a codebase and what data travels with it."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator

from aicomply.egress.asar import iter_asar

CATALOGUE = os.path.join(os.path.dirname(__file__), "vendors.json")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", "coverage", ".e2e"}
TEXT_EXT = {
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".astro", ".html", ".htm",
    ".py", ".go", ".rb", ".java", ".kt", ".swift", ".php", ".cs", ".rs", ".dart",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".example", ".tf", ".sh", ".map",
}
MAX_BYTES = 25_000_000
WINDOW_LINES = 4
WINDOW_CHARS = 400  # minified bundles put a whole app on one line

URL_RE = re.compile(r"\b(?:https?|wss?)://([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+|localhost)(?::\d+)?")
IMPORT_RE = re.compile(
    r"""(?:from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)|import\(\s*['"]([^'"]+)['"]\s*\)"""
    r"""|^\s*import\s+([A-Za-z_][\w.]*)|^\s*from\s+([A-Za-z_][\w.]*)\s+import)"""
)
CALL_RE = re.compile(
    r"\b(fetch|axios|ky|got|superagent|XMLHttpRequest|sendBeacon|WebSocket|EventSource|"
    r"requests\.(get|post|put|patch|delete)|httpx\.|urlopen|http\.(Get|Post|NewRequest)|"
    r"baseURL|base_url|api_base|apiBase|endpoint|dsn|webhook)\b|<(link|script|img|iframe)\b|@import\b",
    re.IGNORECASE,
)
ENV_RE = re.compile(r"\b([A-Z][A-Z0-9]*)_(?:API_KEY|KEY|TOKEN|DSN|WEBHOOK(?:_URL)?|SECRET_KEY|URL)\b")
SECRET_VALUE_RE = re.compile(
    r"((?:api[_-]?key|secret|token|password|passwd|dsn|webhook(?:_url)?|authorization|bearer)\s*[:=]\s*)(['\"]?)([^'\"\s,;]{8,})",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})")
COMMENT_RE = re.compile(r"^\s*(//|#|\*|/\*|<!--|--)")

PII_TERMS = {
    "email": r"e-?mail",
    "phone": r"phone|telefoon|mobile_number",
    "name": r"first_?name|last_?name|full_?name|achternaam|voornaam",
    "address": r"street|postcode|zip_?code|home_?address|adres",
    "national id": r"\bbsn\b|\bssn\b|social_security|passport|paspoort|id_?number",
    "financial": r"\biban\b|card_?number|salary|salaris",
    "date of birth": r"date_?of_?birth|\bdob\b|geboortedatum|birth_?date",
    "cv / resume": r"\bcv\b|resume|curriculum",
    "ip address": r"ip_?address|x-forwarded-for|remote_addr",
}
SPECIAL_TERMS = {
    "health data": r"health|medical|diagnos|medisch",
    "ethnicity / religion": r"ethnic|religion|religie",
    "biometrics": r"biometric|face_?embedding|fingerprint",
}
PAYLOAD_TERMS = {"prompt / messages": r"\bprompt\b|\bmessages\b|system_prompt|chat\.completions|\.generate\("}
RISKY_SETTINGS = {
    "sendDefaultPii enabled": r"send_?default_?pii\s*[:=]\s*(true|True)",
    "session replay without masking": r"mask_?all_?(text|inputs)\s*[:=]\s*(false|False)",
    "analytics autocapture": r"autocapture\s*[:=]\s*(true|True)",
    "prompt logging to vendor": r"(log_?prompts|store)\s*[:=]\s*(true|True)",
}
NON_EU = {"US", "CN"}
EU_HOST = re.compile(r"(^|\.)(eu|de|europe-west\d|eu-(west|central|north)-\d)[.-]|\.eu$|datadoghq\.eu")


def _compile(terms: dict) -> dict:
    return {k: re.compile(v, re.IGNORECASE) for k, v in terms.items()}


_PII, _SPECIAL, _PAYLOAD, _RISKY = map(_compile, (PII_TERMS, SPECIAL_TERMS, PAYLOAD_TERMS, RISKY_SETTINGS))


def load_catalogue(path: str = CATALOGUE) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _iter_texts(root: str, include_deps: bool, skipped: list[str]) -> Iterator[tuple[str, str]]:
    if os.path.isfile(root):
        yield from _file_texts(root, os.path.basename(root), skipped)
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if include_deps or d not in SKIP_DIRS)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            yield from _file_texts(full, os.path.relpath(full, root), skipped)


def _file_texts(full: str, rel: str, skipped: list[str]) -> Iterator[tuple[str, str]]:
    ext = os.path.splitext(full)[1].lower()
    try:
        size = os.path.getsize(full)
    except OSError:
        return
    if ext == ".asar":
        # Read in place whatever the size: a real app.asar is routinely over 100 MB.
        try:
            for inner, blob in iter_asar(full):
                if os.path.splitext(inner)[1].lower() in TEXT_EXT and b"\0" not in blob[:4096]:
                    yield f"{rel}!/{inner}", blob.decode("utf-8", "replace")
        except (ValueError, KeyError, TypeError, OSError) as exc:  # struct.error is a ValueError
            skipped.append(f"{rel}: not a readable asar archive ({type(exc).__name__})")
        return
    if size > MAX_BYTES:
        if ext in TEXT_EXT:
            skipped.append(f"{rel}: {size // 1_000_000} MB, over the {MAX_BYTES // 1_000_000} MB limit")
        return
    if ext not in TEXT_EXT and not os.path.basename(full).startswith(".env"):
        return
    with open(full, "rb") as f:
        blob = f.read()
    if b"\0" not in blob[:4096]:
        yield rel, blob.decode("utf-8", "replace")


class _Index:
    def __init__(self, catalogue: dict, own_hosts: list[str]):
        self.vendors = catalogue["vendors"]
        self.ignore = set(catalogue["ignore_hosts"])
        self.controls = catalogue["category_controls"]
        self.own = [h.lower() for h in own_hosts]
        self.by_package = {p: v for v in self.vendors for p in v["packages"]}
        self.by_id = {v["id"]: v for v in self.vendors}

    def env_vendor(self, prefix: str):
        return self.by_id.get(prefix.lower()) or self.by_id.get(prefix.lower().replace("_", "-"))

    def host_vendor(self, host: str):
        host = host.lower()
        if host in self.ignore or any(host == o or host.endswith("." + o) for o in self.own):
            return None, True
        for v in self.vendors:
            for h in v["hosts"]:
                if host == h or host.endswith("." + h) or (h.endswith("-runtime") and h in host):
                    return v, False
        return None, False

    def package_vendor(self, pkg: str):
        pkg = pkg.strip()
        if pkg in self.by_package:
            return self.by_package[pkg]
        for name, vendor in self.by_package.items():
            if pkg.startswith(name + "/") or pkg.startswith(name + "."):
                return vendor
        return None


def _statement(lines: list[str], i: int) -> str:
    """The line plus its continuation, up to WINDOW_LINES ahead, ending where the statement or tag ends."""
    out = [lines[i]]
    j = i
    while j < len(lines) - 1 and len(out) <= WINDOW_LINES and not lines[j].rstrip().endswith((";", ">", "}")):
        j += 1
        out.append(lines[j])
    return "\n".join(out)


def mask(snippet: str) -> str:
    """Evidence is shared with auditors and agents; a credential never travels inside it."""
    snippet = SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", snippet)
    return TOKEN_RE.sub("***", snippet)


def _hints(text: str) -> tuple[set, set, set]:
    pii = {k for k, r in _PII.items() if r.search(text)}
    special = {k for k, r in _SPECIAL.items() if r.search(text)}
    payload = {k for k, r in _PAYLOAD.items() if r.search(text)}
    return pii, special, payload


def scan(target: str, own_hosts: list[str] | None = None, include_deps: bool = False,
         extra_hosts: list[str] | None = None, catalogue: dict | None = None) -> dict:
    index = _Index(catalogue or load_catalogue(), own_hosts or [])
    dests: dict[str, dict] = {}
    settings: list[dict] = []
    skipped: list[str] = []
    files = 0

    def dest_for(key: str, vendor, host: str = "") -> dict:
        if key not in dests:
            dests[key] = {
                "key": key,
                "vendor": vendor["name"] if vendor else host,
                "category": vendor["category"] if vendor else "unknown",
                "region": vendor["region"] if vendor else "unknown",
                "note": vendor.get("note", "") if vendor else "",
                "hosts": set(), "evidence": [], "pii": set(), "special": set(), "payload": set(),
            }
        return dests[key]

    for rel, text in _iter_texts(target, include_deps, skipped):
        files += 1
        lines = text.splitlines()
        # An SDK import or a credential means the whole file can feed that vendor:
        # the data in reach is the data in the file. Bundles are too big for that.
        file_hints = _hints(text) if len(text) < 200_000 else (set(), set(), set())
        for i, line in enumerate(lines):
            if len(line) > 2000:
                chunks = [(m.start(), m.group(0)) for m in URL_RE.finditer(line)]
                minified = True
            else:
                chunks, minified = None, False
            is_comment = bool(COMMENT_RE.match(line)) and not minified
            for label, rx in _RISKY.items():
                if rx.search(line) and not is_comment:
                    settings.append({"setting": label, "where": f"{rel}:{i + 1}"})
            found = []
            for m in URL_RE.finditer(line):
                vendor, ignored = index.host_vendor(m.group(1))
                if ignored:
                    continue
                window_start = m.start()
                found.append((vendor, m.group(1), "url", window_start))
            for m in IMPORT_RE.finditer(line):
                pkg = next(g for g in m.groups() if g)
                vendor = index.package_vendor(pkg)
                if vendor:
                    found.append((vendor, "", "import", m.start()))
            for m in ENV_RE.finditer(line):
                vendor = index.env_vendor(m.group(1))
                if vendor:
                    found.append((vendor, "", "env", m.start()))
            for vendor, host, kind, pos in found:
                if is_comment:
                    continue
                if minified:
                    ctx = line[max(0, pos - WINDOW_CHARS): pos + WINDOW_CHARS]
                else:
                    ctx = _statement(lines, i)
                if kind in ("import", "env"):
                    strength = "import" if kind == "import" else "credential"
                else:
                    strength = "call" if CALL_RE.search(ctx) else "mention"
                if vendor is None and strength != "call":
                    continue  # an unknown host only matters when something actually calls it
                d = dest_for(vendor["id"] if vendor else host.lower(), vendor, host)
                if host:
                    d["hosts"].add(host.lower())
                pii, special, payload = file_hints if kind in ("import", "env") else _hints(ctx)
                d["pii"] |= pii
                d["special"] |= special
                d["payload"] |= payload
                if len(d["evidence"]) < 25:
                    snippet = (line[max(0, pos - 60): pos + 100] if minified else line).strip()
                    d["evidence"].append({"where": f"{rel}:{i + 1}", "kind": strength, "snippet": mask(snippet[:180])})

    for host in extra_hosts or []:
        vendor, ignored = index.host_vendor(host)
        if not ignored:
            d = dest_for(vendor["id"] if vendor else host.lower(), vendor, host)
            d["hosts"].add(host.lower())
            d["evidence"].append({"where": "--extra-hosts", "kind": "call", "snippet": host})

    out = []
    for d in dests.values():
        if not d["evidence"]:
            continue
        if d["region"] == "configurable" and d["hosts"] and all(EU_HOST.search(h) for h in d["hosts"]):
            d["region"] = "EU"  # every host this code talks to is the vendor's EU endpoint
        risk = _risk(d)
        out.append({
            **{k: v for k, v in d.items() if k not in ("hosts", "pii", "special", "payload")},
            "hosts": sorted(d["hosts"]),
            "data_hints": sorted(d["pii"]) + sorted(d["special"]) + sorted(d["payload"]),
            "special_category": bool(d["special"]),
            "personal_data": bool(d["pii"] or d["special"]),
            "controls": index.controls.get(d["category"], index.controls["unknown"]),
            **risk,
        })
    out.sort(key=lambda d: (-d["risk_score"], d["vendor"].lower()))
    return {
        "target": target,
        "files_scanned": files,
        "skipped": skipped,
        "destinations": out,
        "risky_settings": settings,
        "summary": {
            "destinations": len(out),
            "non_eu_with_personal_data": sum(1 for d in out if d["region"] in NON_EU and d["personal_data"]),
            "llm_providers": sorted(d["vendor"] for d in out if d["category"] == "llm"),
            "unknown_destinations": sorted(d["vendor"] for d in out if d["category"] == "unknown"),
        },
    }


def _risk(d: dict) -> dict:
    confirmed = any(e["kind"] in ("call", "import", "credential") for e in d["evidence"])
    likelihood = 5 if confirmed else 3
    if d["special"]:
        impact = 5
    elif d["pii"]:
        impact = 4
    elif d["category"] in ("analytics", "session-recording", "cdn") or d["payload"]:
        impact = 3  # behaviour, IP addresses and prompts are personal data more often than not
    else:
        impact = 2
    if d["region"] in ("US", "CN", "unknown") and (d["pii"] or d["special"] or d["payload"]):
        impact = min(5, impact + 1)
    return {"likelihood": likelihood, "impact": impact, "risk_score": likelihood * impact}


def failing_controls(egress: dict) -> dict[str, list[str]]:
    """control id -> destinations with personal data (or special data / prompts) in reach, any region."""
    out: dict[str, list[str]] = {}
    for d in egress.get("destinations", []):
        if d["personal_data"] or d["impact"] >= 4:
            for cid in d["controls"]:
                out.setdefault(cid, []).append(d["vendor"])
    return out
