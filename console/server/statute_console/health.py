"""Harness self-checks (H1–H11). Read-only; each result names its evidence."""
from __future__ import annotations

import hashlib
import importlib.metadata as md
import platform
import re
from pathlib import Path

from . import registry as R
from .findings import annotation_status, source_check
from .model import Snapshot

EXPECTED_SCHEMA = {"01_inventory": "2.0", "02_parser": "1.0", "03_data": "2.0", "04_logic": "2.0",
                   "05_rules": "1.0", "06_diagram": "2.0", "07_synthesis": "2.0", "08_graph": "2.0"}
GENERIC_FLAGS = {"--output", "--output-root", "--verbose", "--run", "--help"}


def _check(cid, name, status, summary, details=None, evidence=None, remediation=None):
    return {"id": cid, "name": name, "status": status, "summary": summary, "details": details or [],
            "evidence": evidence or [], "remediation": remediation}


def _version(pkg):
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return None


def run_checks(snap: Snapshot) -> list[dict]:
    ws = snap.ws
    out = []

    # H1 interpreter and dependencies
    antlr, sqlglot = _version("antlr4-python3-runtime"), _version("sqlglot")
    notice = ws.scripts / "vendor" / "plsql_grammar" / "NOTICE.md"
    need = None
    if notice.is_file():
        m = re.search(r"antlr4-python3-runtime\s*==\s*([\d.]+)", notice.read_text(encoding="utf-8", errors="replace"))
        need = m.group(1) if m else None
    py_ok = tuple(int(x) for x in platform.python_version_tuple()[:2]) >= (3, 10)
    status = "pass" if py_ok and antlr and sqlglot and (need is None or antlr == need) else \
        ("fail" if not (antlr and sqlglot) else "warn")
    out.append(_check("H1", "Interpreter and dependencies", status,
                      f"Python {platform.python_version()} · antlr4-python3-runtime {antlr or 'missing'}"
                      f"{f' (grammar requires {need})' if need else ''} · sqlglot {sqlglot or 'missing'}",
                      ["Checked in the console's own interpreter; the pipeline must use the same one.",
                       "No dependency manifest exists in the repository, so versions are not pinned."],
                      [{"label": "NOTICE.md", "path": ws.rel(notice)}],
                      None if status == "pass" else "pip install antlr4-python3-runtime==4.13.2 sqlglot"))

    # H2 vendored grammar
    vend = ws.scripts / "vendor" / "plsql_grammar"
    needed = ["PlSqlLexer.py", "PlSqlParser.py", "PlSqlParserVisitor.py", "PlSqlLexerBase.py", "PlSqlParserBase.py"]
    missing = [f for f in needed if not (vend / f).is_file()]
    det = []
    built = ws.repo / "tools_antlr_build" / "grammar" / "PlSqlParser.py"
    if built.is_file() and (vend / "PlSqlParser.py").is_file():
        same = hashlib.md5(built.read_bytes()).digest() == hashlib.md5((vend / "PlSqlParser.py").read_bytes()).digest()
        det.append("Vendored parser matches tools_antlr_build output." if same
                   else "Vendored parser differs from tools_antlr_build output — regenerated but not copied?")
    out.append(_check("H2", "Vendored ANTLR grammar", "fail" if missing else "pass",
                      "All generated grammar files present" if not missing else f"Missing: {', '.join(missing)}",
                      det, [{"label": "vendor/plsql_grammar", "path": ws.rel(vend)}]))

    # H3 / H4 source reachability and drift
    src = source_check(snap)
    if src is None:
        out.append(_check("H3", "Source reachability", "not_applicable", "No inventory run yet"))
        out.append(_check("H4", "Source drift", "not_applicable", "No inventory run yet"))
    else:
        found = len(src["files"]) - src["missing"]
        st = "pass" if not src["unreachable"] else ("warn" if not src["missing"] else "fail")
        out.append(_check("H3", "Source reachability", st,
                          f"{len(src['files']) - src['unreachable']} of {len(src['files'])} files reachable at their "
                          f"recorded path; {found} located in total",
                          [f"Recorded source directory: {src['source_dir_display']} "
                           f"({'exists' if src['source_dir_reachable'] else 'not found'})"] +
                          [f"{r['file']}: {r['resolved_via']}" for r in src["files"] if not r["recorded_reachable"]][:20],
                          remediation=None if st == "pass" else
                          "Re-run 01_inventory against the current source directory before re-running later stages"))
        st = "pass" if not src["changed"] else "warn"
        out.append(_check("H4", "Source drift since inventory", st,
                          f"{src['changed']} changed · {found - src['changed']} identical (sha256)" if found else
                          "No source file could be located to compare",
                          [f"{r['file']} changed" for r in src["files"] if r["changed"]],
                          remediation=None if st == "pass" else "Re-run the pipeline from 01_inventory"))

    # H5 output tree integrity
    details, worst = [], "pass"
    for key in R.ORDER:
        s = snap.stages[key]
        if s["latest_error"]:
            details.append(f"{key}: latest.json {s['latest_error']}")
            worst = "fail"
        if s["latest_missing_dir"]:
            details.append(f"{key}: latest.json names {s['latest_run_version']}, which does not exist")
            worst = "fail"
        crashed = [r for r in s["runs"] if r["state"] == "crashed"]
        if crashed:
            details.append(f"{key}: {len(crashed)} run director{'y' if len(crashed) == 1 else 'ies'} with no recorded outcome")
            worst = "warn" if worst == "pass" else worst
        art = snap.artifact(None, key)
        if art and art.get("schema_version") and art.get("schema_version") != EXPECTED_SCHEMA[key] and key != "07_synthesis":
            details.append(f"{key}: schema_version {art.get('schema_version')} (console expects {EXPECTED_SCHEMA[key]})")
            worst = "warn" if worst == "pass" else worst
    out.append(_check("H5", "Output tree integrity", worst,
                      "Pointers, run metadata and schema versions are consistent" if worst == "pass" else
                      f"{len(details)} problem(s) in the output tree", details,
                      [{"label": "output/", "path": ws.rel(ws.output)}]))

    # H6 lineage consistency
    p = snap.current_pipeline_run()
    if not p:
        out.append(_check("H6", "Lineage of the current pipeline run", "not_applicable", "No pipeline run yet"))
    else:
        unk = [k for k in R.ORDER if any(c["kind"] == "unknown" for c in (snap.stages[k].get("freshness") or {}).get("causes", []))]
        st = "fail" if p["consistency"] == "inconsistent" else ("warn" if unk or p["inferred_members"] else "pass")
        det = [f"{i['stage']}: {len(i['versions'])} versions in use" for i in p["inconsistencies"]]
        det += [f"{k}: provenance not recorded for some inputs" for k in unk]
        det += [f"{m}: membership inferred by time" for m in p["inferred_members"]]
        summ = f"{p['id']} is {p['consistency']}"
        if st == "warn":
            summ += " as far as recorded — some provenance is unrecorded or inferred"
        out.append(_check("H6", "Lineage of the current pipeline run", st, summ, det))

    # H7 annotations
    ann = annotation_status(snap, p)
    if not ann["present"]:
        out.append(_check("H7", "Annotations file", "info", "No brd_annotations.json — nothing to merge",
                          ["07_synthesis reads it from the working directory; it is human-owned and never written by the pipeline."]))
    elif ann["error"]:
        out.append(_check("H7", "Annotations file", "fail", f"Unreadable: {ann['error']}",
                          ["07_synthesis silently treats an unreadable file as empty."],
                          [{"label": "brd_annotations.json", "path": ann["path"]}]))
    else:
        bad = [e for e in ann["entries"] if e["status"] != "applied"]
        out.append(_check("H7", "Annotations file", "warn" if bad else "pass",
                          f"{len(ann['entries'])} annotation(s); {len(bad)} orphaned or re-pointed",
                          [f"{e['key']}: {e['status']} — {e['detail']}" for e in bad],
                          [{"label": "brd_annotations.json", "path": ann["path"]}]))

    # H8 harness definitions vs code
    det, worst = [], "pass"
    for s in R.STAGES:
        script = ws.scripts / s["script"]
        agent = ws.agents / s["agent"]
        if not script.is_file():
            det.append(f"{s['key']}: script {s['script']} missing")
            worst = "fail"
            continue
        code = script.read_text(encoding="utf-8", errors="replace")
        flags = set(re.findall(r'add_argument\(\s*"(--[a-z][a-z0-9-]*)"', code))
        roots = {R.ROOT_FLAGS[m] for m in re.findall(r'"--([a-z]+)-root"', code) if m in R.ROOT_FLAGS}
        declared = set(R.inputs_of(s["key"]))
        if roots != declared:
            det.append(f"{s['key']}: script reads {sorted(roots) or 'nothing'}; registry declares {sorted(declared) or 'nothing'}")
            worst = "warn" if worst == "pass" else worst
        if not agent.is_file():
            det.append(f"{s['key']}: agent spec {s['agent']} missing")
            worst = "warn" if worst == "pass" else worst
            continue
        spec = agent.read_text(encoding="utf-8", errors="replace")
        used = set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", spec))
        unknown = sorted(f for f in used - flags - GENERIC_FLAGS if not f.startswith("--update"))
        if unknown:
            det.append(f"{s['key']}: agent spec mentions flags the script does not define: {', '.join(unknown)}")
            worst = "warn" if worst == "pass" else worst
        if s["key"] == "01_inventory" and "./checkpoints/" in spec:
            det.append("01_inventory: agent spec tells the agent to use --output ./checkpoints/, which writes no "
                       "run_meta.json or latest.json — stage 2 cannot consume that run")
            worst = "warn" if worst == "pass" else worst
    out.append(_check("H8", "Harness definitions match the scripts", worst,
                      "Registry, scripts and agent specs agree" if worst == "pass" else f"{len(det)} mismatch(es)",
                      det, [{"label": ".claude/agents", "path": ws.rel(ws.agents)}]))

    # H9 instrumentation
    latest = [snap.stages[k]["latest"] for k in R.ORDER if snap.stages[k]["latest"]]
    inst = [r for r in latest if r["instrumented"]]
    has_lib = (ws.scripts / "lib_runlog.py").is_file()
    st = "pass" if latest and len(inst) == len(latest) else ("info" if has_lib else "warn")
    out.append(_check("H9", "Run lifecycle instrumentation", st,
                      f"{len(inst)} of {len(latest)} published runs carry run_status.json / events.jsonl",
                      ["Runs produced before lib_runlog.py existed have no recorded start, failure or progress; "
                       "their running/crashed states are inferred from the directory."] if len(inst) < len(latest) else [],
                      remediation=None if st == "pass" else "Re-run the pipeline to produce instrumented runs"))

    # H10 tests / evaluation
    out.append(_check("H10", "Tests and evaluation results", "not_applicable",
                      "Not recorded — the 8 suites (414 checks) and evaluate_rules.py print results but persist nothing",
                      ["Run: for t in tests/test_*.py; do python \"$t\"; done"]))

    # H11 disk / retention
    det, total = [], 0
    for key in R.ORDER:
        s = snap.stages[key]
        size = 0
        sdir = ws.stage_dir(key)
        if sdir.is_dir():
            for f in sdir.rglob("*"):
                try:
                    if f.is_file():
                        size += f.stat().st_size
                except OSError:
                    pass
        total += size
        det.append(f"{key}: {len(s['runs'])} run(s), {len(s['attempts'])} failed attempt(s), {size / 1024:.0f} KB")
    out.append(_check("H11", "Run directories and retention", "info",
                      f"{sum(len(snap.stages[k]['runs']) for k in R.ORDER)} runs, {total / 1048576:.1f} MB — nothing prunes them",
                      det, remediation="Keep the last N runs per stage plus every run referenced by a kept pipeline run"))
    return out


_ = Path
