"""Command line: python -m aicomply <command>."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from aicomply import __version__
from aicomply.frameworks import load_frameworks, validate
from aicomply.scoring import exit_code, load_findings, score_all

HOME = os.environ.get("AICOMPLY_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _frameworks(args) -> list[dict]:
    if not os.path.isdir(args.frameworks):
        sys.exit(f"no catalogue at {args.frameworks}: run from a checkout of the repository, "
                 "or point --frameworks (and --registry) at one, or set AICOMPLY_HOME")
    return load_frameworks(args.frameworks)


def cmd_validate(args) -> int:
    fws = _frameworks(args)
    problems = validate(fws)
    total = sum(len(f["controls"]) for f in fws)
    for p in problems:
        print(p)
    print(f"{len(fws)} frameworks, {total} controls, {len(problems)} problems")
    return 1 if problems else 0


def cmd_score(args) -> int:
    from aicomply.render.markdown import score_table

    scores = score_all(_frameworks(args), load_findings(args.findings))
    print(json.dumps(scores, indent=2) if args.json else score_table(scores))
    return exit_code(scores)


def cmd_audit(args) -> int:
    from aicomply.egress.scanner import failing_controls
    from aicomply.regsync.sync import list_changes, open_changes_by_framework, source_status
    from aicomply.render.html import render
    from aicomply.render.markdown import audit_report, score_table
    from aicomply.riskmatrix import build_register

    fws = _frameworks(args)
    findings = load_findings(args.findings)
    scores = score_all(fws, findings)
    egress = None
    if args.egress:
        with open(args.egress, encoding="utf-8") as f:
            egress = json.load(f)
    audit_date = date.fromisoformat(args.date) if args.date else date.today()
    open_changes = open_changes_by_framework(args.registry)
    register = build_register(fws, findings, failing_controls(egress or {}), scores, audit_date, open_changes)
    known = {c["id"] for fw in fws for c in fw["controls"]}
    meta = {
        "system": args.system,
        "date": audit_date.isoformat(),
        "controls": len(known),
        "assessed": len(known & set(findings)),
    }
    os.makedirs(args.out, exist_ok=True)
    html = render(register, scores, meta, egress, source_status(args.registry), list_changes(args.registry))
    files = {
        "risk-matrix.html": html,
        "audit-report.md": audit_report(meta, scores, register, egress, open_changes),
        "risk-register.json": json.dumps({"meta": meta, "scores": scores, "register": register}, indent=2),
    }
    for name, content in files.items():
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            f.write(content)
    print(score_table(scores))
    print("\nWrote " + ", ".join(os.path.join(args.out, n) for n in files))
    return exit_code(scores)


def cmd_egress(args) -> int:
    from aicomply.egress.scanner import scan

    extra = []
    if args.extra_hosts:
        with open(args.extra_hosts, encoding="utf-8") as f:
            extra = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    result = scan(args.target, own_hosts=args.own, include_deps=args.include_deps, extra_hosts=extra)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    for d in result["destinations"]:
        hints = ", ".join(d["data_hints"]) or "-"
        print(f"{d['risk_score']:>3}  {d['vendor']:<34} {d['category']:<18} {d['region']:<13} {hints}")
    for s in result["risky_settings"]:
        print(f"  !  {s['setting']} at {s['where']}")
    for s in result["skipped"]:
        print(f"  ?  not scanned: {s}")
    sm = result["summary"]
    print(f"\n{result['files_scanned']} files, {sm['destinations']} destinations, "
          f"{sm['non_eu_with_personal_data']} outside the EU with personal data in reach")
    return 1 if args.strict and (sm["non_eu_with_personal_data"] or result["risky_settings"]) else 0


def cmd_sync(args) -> int:
    from aicomply.regsync.sync import run_sync

    report = run_sync(args.registry, _frameworks(args), only=args.source, dry_run=args.dry_run,
                      force=args.force, accept_shrink=args.accept_shrink)
    for o in report.outcomes:
        extra = o.reason or o.change_file
        print(f"{o.result:<10} {o.source}{'  ' + extra if extra else ''}")
    if not report.outcomes:
        print("nothing due (use --force to check every source now)")
    changed, broken = report.by("changed"), report.by("broken")
    print(f"\n{len(report.outcomes)} checked, {len(changed)} changed, {len(broken)} broken"
          + ("  (dry run, nothing written)" if args.dry_run else ""))
    return 2 if changed else (1 if broken else 0)


def cmd_sources(args) -> int:
    from aicomply.regsync.sync import source_status

    for s in source_status(args.registry):
        state = "BROKEN" if s["broken"] else (s["last_success"][:10] or "never")
        print(f"{s['id']:<18} {s['strategy']:<7} {state:<11} -> {', '.join(s['frameworks'])}")
        for line in s["current"][: args.lines]:
            print(f"{'':>20}{line}")
    return 0


def cmd_changes(args) -> int:
    from aicomply.regsync.sync import list_changes

    items = list_changes(args.registry, None if args.all else "open")
    for name, r in items:
        d = r["detection"]
        print(f"{r['review']['status']:<12} {name}\n    {d['source_name']}: {len(d.get('impacted_controls', []))} controls to re-check")
        if args.diff:
            print("\n".join("    " + line for line in d["diff"].splitlines()))
    if not items:
        print("no open changes" if not args.all else "no changes recorded")
    return 0


def cmd_review(args) -> int:
    from aicomply.regsync.sync import review_change

    record = review_change(args.registry, args.change, args.status, args.reviewer, args.note)
    print(f"{args.change}: {record['review']['status']} by {record['review']['reviewer']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aicomply", description="Score AI systems against the EU AI Act, GDPR and ISO standards.")
    p.add_argument("--version", action="version", version=f"aicomply {__version__}")
    p.add_argument("--frameworks", default=os.path.join(HOME, "frameworks"), help="control catalogue folder")
    p.add_argument("--registry", default=os.path.join(HOME, "registry"), help="regulation source registry folder")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="check the control catalogue").set_defaults(fn=cmd_validate)

    s = sub.add_parser("score", help="score a findings file")
    s.add_argument("findings")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_score)

    a = sub.add_parser("audit", help="score + risk matrix + report")
    a.add_argument("--findings", required=True)
    a.add_argument("--egress", help="egress.json from `aicomply egress`")
    a.add_argument("--system", default="AI system", help="name shown on the report")
    a.add_argument("--date", help="audit date, YYYY-MM-DD (default today)")
    a.add_argument("--out", default="audit", help="output folder")
    a.set_defaults(fn=cmd_audit)

    e = sub.add_parser("egress", help="static scan of outbound data flows")
    e.add_argument("target", help="source folder, built bundle folder, single file or .asar")
    e.add_argument("--own", action="append", default=[], help="first-party host suffix, repeatable")
    e.add_argument("--extra-hosts", help="file with one host per line (e.g. from REA on a binary)")
    e.add_argument("--include-deps", action="store_true", help="also scan node_modules and virtualenvs")
    e.add_argument("--out", help="write egress.json")
    e.add_argument("--strict", action="store_true", help="exit 1 on personal data outside the EU or a risky setting")
    e.set_defaults(fn=cmd_egress)

    y = sub.add_parser("sync", help="check the official sources for changes")
    y.add_argument("--source", help="only this source id")
    y.add_argument("--dry-run", action="store_true")
    y.add_argument("--force", action="store_true", help="ignore the check interval")
    y.add_argument("--accept-shrink", action="store_true",
                   help="after a real restructure or repeal: record a much shorter text as a change instead of a failure")
    y.set_defaults(fn=cmd_sync)

    so = sub.add_parser("sources", help="state of every watched source")
    so.add_argument("--lines", type=int, default=4)
    so.set_defaults(fn=cmd_sources)

    c = sub.add_parser("changes", help="list detected source changes")
    c.add_argument("--all", action="store_true", help="include reviewed changes")
    c.add_argument("--diff", action="store_true")
    c.set_defaults(fn=cmd_changes)

    r = sub.add_parser("review", help="record the human review of a change")
    r.add_argument("change", help="file name in registry/changes/")
    r.add_argument("--status", required=True, choices=["in_review", "processed", "not_relevant"])
    r.add_argument("--reviewer", required=True)
    r.add_argument("--note", default="")
    r.set_defaults(fn=cmd_review)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
