"""Payloads for the catalogue-style tabs: agents, statement trace, rules explorer,
artifact catalogue, BRD reader, data model and the synthetic-testing quality view.
All read-through from one pipeline run's artifacts; nothing is persisted."""
from __future__ import annotations

import re
from pathlib import Path

from . import registry as R
from .model import Snapshot, redact
from .views import artifact_id

STMT_CATEGORY = {
    "IF": "control_flow", "LOOP": "control_flow", "BODY": "control_flow", "RETURN": "control_flow", "CASE": "control_flow",
    "SELECT_INTO": "data_access", "INSERT": "data_access", "UPDATE": "data_access", "DELETE": "data_access",
    "MERGE": "data_access", "OPEN_CURSOR": "data_access", "FETCH": "data_access",
    "CALL": "call",
    "COMMIT": "transaction", "ROLLBACK": "transaction", "SAVEPOINT": "transaction",
    "RAISE": "exception", "EXCEPTION_HANDLER": "exception",
    "ASSIGNMENT": "assignment",
}
FLOW = {"RAISE": "Leaves the block", "RETURN": "Returns to caller", "CALL": "Returns here",
        "COMMIT": "Ends transaction", "ROLLBACK": "Ends transaction"}


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    out = {}
    if not m:
        return out
    key, buf = None, []
    for line in m.group(1).splitlines():
        km = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line)
        if km and not line.startswith(" "):
            if key:
                out[key] = " ".join(buf).strip()
            key, v = km.group(1), km.group(2).strip()
            buf = [] if v in (">", "|") else [v]
        elif key:
            buf.append(line.strip())
    if key:
        out[key] = " ".join(buf).strip()
    return out


def agents(snap: Snapshot) -> list[dict]:
    ws = snap.ws
    out = []
    for s in R.STAGES:
        spec = ws.agents / s["agent"]
        fm = _frontmatter(spec.read_text(encoding="utf-8", errors="replace")) if spec.is_file() else {}
        st = snap.stages[s["key"]]
        run = st["latest"]
        newest = st["newest"]
        d = ws.run_dir(s["key"], run["run_version"]) if run else None
        size = 0
        if d:
            p = d / s["artifact"]
            size = p.stat().st_size if p.is_file() else 0
        desc = fm.get("description", "")
        first = re.split(r"(?<=\.)\s", desc, maxsplit=2)
        out.append({
            "stage": s["key"], "n": s["n"], "title": s["title"], "agent": fm.get("name", s["agent"]),
            "description": " ".join(first[:2]) if first else s["purpose"],
            "tools": fm.get("tools"), "type": "Deterministic", "llm_in_generation": False,
            "script": f".claude/scripts/{s['script']}", "spec": f".claude/agents/{s['agent']}",
            "artifact": s["artifact"], "artifact_bytes": size,
            "state": (newest or {}).get("state"), "published_state": (run or {}).get("state"),
            "freshness": (st.get("freshness") or {}).get("value"),
            "run_version": (run or {}).get("run_version"), "duration_ms": (run or {}).get("duration_ms"),
            "timing_basis": (run or {}).get("timing_basis"), "instrumented": (run or {}).get("instrumented"),
            "requires": s["requires"], "optional": s["optional"],
        })
    return out


def statement_trace(snap: Snapshot, prun: dict | None, obj: str | None = None) -> dict:
    parser = snap.artifact(prun, "02_parser") or {}
    d = snap.member_dir(prun, "02_parser")
    rows, objects = [], []
    for oid, rel in sorted((parser.get("object_index") or {}).items()):
        objects.append(oid)
        if obj and obj != oid:
            continue
        rec, _ = snap.ws.load_json(d / rel) if d else (None, None)
        if not isinstance(rec, dict):
            continue
        stmts = sorted((rec.get("statements") or {}).values(), key=lambda s: (s.get("start_line") or 0, s.get("statement_id")))
        for i, s in enumerate(stmts, 1):
            t = s.get("statement_type", "")
            target = ", ".join(s.get("tables") or []) or s.get("call_target") or (
                ", ".join(s.get("handler_for")) if isinstance(s.get("handler_for"), list) else s.get("handler_for")) or ""
            rows.append({"step": i, "object": oid, "line": s.get("start_line"), "end_line": s.get("end_line"),
                         "scope": " › ".join(s.get("scope_path") or []) or "body", "depth": s.get("nesting_depth"),
                         "kind": STMT_CATEGORY.get(t, "other"), "operation": t, "target": target,
                         "flow": FLOW.get(t, "Continues"), "statement_id": s.get("statement_id"),
                         "writes": s.get("writes") or [], "reads": s.get("reads") or [],
                         "manual_review": bool(s.get("requires_manual_review"))})
    counts = {"total": len(rows)}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"objects": objects, "entries": rows, "counts": counts,
            "run_version": (prun or {}).get("members", {}).get("02_parser")}


def rules(snap: Snapshot, prun: dict | None) -> dict:
    ra = snap.artifact(prun, "05_rules") or {}
    reqs = {r["id"]: r for r in (snap.artifact(prun, "07_synthesis", "brd_index.json") or {}).get("requirements", [])}
    sets = {rid: rs.get("name") for rs in ra.get("rule_sets", []) for rid in rs.get("rule_ids", [])}
    out = []
    for r in ra.get("business_rules", []):
        s = r.get("source") or {}
        q = reqs.get(r["rule_id"]) or {}
        out.append({
            "rule_id": r["rule_id"], "name": r.get("name"), "category": r.get("category"),
            "confidence": r.get("confidence"), "requires_sme_review": bool(r.get("requires_sme_review")),
            "is_enforced": r.get("is_enforced"), "pattern": r.get("structural_pattern"),
            "signal_strength": r.get("signal_strength"), "rule_set": sets.get(r["rule_id"]),
            "condition": r.get("condition_text"), "description": redact(r.get("description")),
            "source_kind": s.get("kind"), "object_id": s.get("object_id"), "line": s.get("line"),
            "statement_id": s.get("statement_id"), "table": s.get("table"), "constraint": s.get("constraint_name"),
            "is_duplicated": bool(r.get("is_duplicated")),
            "requirement": q.get("text"), "modality": q.get("modality"), "verification": q.get("verification_method"),
        })
    return {"rules": out, "stats": ra.get("stats") or {}, "rule_sets": ra.get("rule_sets") or [],
            "error_handling": [{"name": e.get("name"), "category": e.get("category"), "line": (e.get("source") or {}).get("line"),
                                "object_id": (e.get("source") or {}).get("object_id")} for e in ra.get("error_handling_catalogue", [])],
            "run_version": (prun or {}).get("members", {}).get("05_rules")}


def artifacts_all(snap: Snapshot, prun: dict | None) -> dict:
    out = []
    for key in R.ORDER:
        d = snap.member_dir(prun, key)
        if not d:
            continue
        rv = d.name
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.is_symlink():
                continue
            rel = f.relative_to(d).as_posix()
            out.append({"stage": key, "stage_title": R.BY_KEY[key]["title"], "run_version": rv, "path": rel,
                        "name": f.name, "ext": f.suffix.lower(), "bytes": f.stat().st_size, "id": artifact_id(rel),
                        "kind": "witness" if f.name in ("run_status.json", "events.jsonl") else
                        "metadata" if f.name == "run_meta.json" else "per-item" if "/" in rel else "artifact"})
    return {"artifacts": out, "total_bytes": sum(a["bytes"] for a in out)}


def brd(snap: Snapshot, prun: dict | None) -> dict | None:
    d = snap.member_dir(prun, "07_synthesis")
    if not d or not (d / "brd.md").is_file():
        return None
    p = d / "brd.md"
    idx = snap.artifact(prun, "07_synthesis", "brd_index.json") or {}
    return {"name": "brd.md", "system": idx.get("system"), "run_version": d.name, "bytes": p.stat().st_size,
            "content": p.read_text(encoding="utf-8", errors="replace"), "artifact_id": artifact_id("brd.md"),
            "generated_at": idx.get("generated_at")}


def data_model(snap: Snapshot, prun: dict | None) -> dict:
    da = snap.artifact(prun, "03_data") or {}
    d = snap.member_dir(prun, "03_data")
    crud = (snap.artifact(prun, "04_logic") or {}).get("crud_matrix") or {}
    tables = []
    for name, t in sorted((da.get("tables") or {}).items()):
        users = {oid: ops.get(name) for oid, ops in crud.items() if ops.get(name)}
        tables.append({"table": name, "columns": len(t.get("columns") or []),
                       "pk": t.get("primary_key"), "fks": [f.get("references_table") for f in t.get("foreign_keys") or []],
                       "checks": len(t.get("check_constraints") or []), "file": t.get("source_file"),
                       "line": t.get("start_line"), "used_by": users, "comment": t.get("comment")})
    erd = (d / "erd.mmd").read_text(encoding="utf-8", errors="replace") if d and (d / "erd.mmd").is_file() else None
    return {"tables": tables, "stats": da.get("stats") or {}, "erd": erd,
            "objects": sorted(crud.keys()), "run_version": d.name if d else None}


def diagrams(snap: Snapshot, prun: dict | None) -> dict:
    da = snap.artifact(prun, "06_diagram") or {}
    d = snap.member_dir(prun, "06_diagram")
    out = []
    for fname, m in (da.get("diagram_index") or {}).items():
        p = d / "diagrams" / fname if d else None
        out.append({"file": fname, "title": m.get("title"), "type": m.get("type"), "nodes": m.get("nodes"),
                    "edges": m.get("edges"), "object_id": m.get("object_id"),
                    "oversize": bool((m.get("budget") or {}).get("oversize")),
                    "source": p.read_text(encoding="utf-8", errors="replace") if p and p.is_file() else None})
    return {"diagrams": out, "quality": da.get("quality") or {}, "warnings": da.get("warnings") or [],
            "node_budget": da.get("node_budget"), "run_version": d.name if d else None}


def quality(snap: Snapshot, prun: dict | None) -> dict:
    stats = (snap.artifact(prun, "05_rules") or {}).get("stats") or {}
    conf, cat = stats.get("by_confidence") or {}, stats.get("by_category") or {}
    total = stats.get("rules_extracted") or sum(conf.values())
    weighted = conf.get("confirmed", 0) * 1.0 + conf.get("high", 0) * 0.9 + conf.get("medium", 0) * 0.5 + conf.get("low", 0) * 0.2
    gaps = (snap.artifact(prun, "07_synthesis", "gaps_register.json") or {}).get("gaps", [])
    by_type, by_sev = {}, {}
    for g in gaps:
        by_type[g.get("gap_type")] = by_type.get(g.get("gap_type"), 0) + 1
        by_sev[g.get("severity")] = by_sev.get(g.get("severity"), 0) + 1
    reqs = (snap.artifact(prun, "07_synthesis", "brd_index.json") or {}).get("requirements", [])
    ver = {}
    for q in reqs:
        ver[q.get("verification_method") or "—"] = ver.get(q.get("verification_method") or "—", 0) + 1
    dq = (snap.artifact(prun, "06_diagram") or {}).get("quality") or {}
    return {
        "score": round(weighted / total * 100) if total else 0, "total_rules": total,
        "by_confidence": conf, "by_category": cat, "sme_review": stats.get("requires_sme_review", 0),
        "gaps_by_type": by_type, "gaps_by_severity": by_sev, "verification": ver,
        "requirements": len(reqs), "unowned": sum(1 for q in reqs if not q.get("owner")),
        "gates": [
            {"name": "Decision labels from rules (tier 1)", "value": dq.get("decision_label_tier1_pct"), "threshold": 0.9, "fmt": "pct"},
            {"name": "Decision branches traced to a rule", "value": dq.get("branch_traceability_pct"), "threshold": 0.8, "fmt": "pct"},
            {"name": "Leaked internal identifiers", "value": dq.get("leaked_identifiers"), "threshold": 0, "fmt": "max"},
            {"name": "Fallback labels", "value": dq.get("fallback_labels"), "threshold": None, "fmt": "count"},
            {"name": "Largest diagram (nodes, budget 40)", "value": dq.get("max_nodes_any_diagram"), "threshold": 40, "fmt": "max"},
        ],
        "suites": {"checks": 414, "suites": 8, "note": "Run: for t in tests/test_*.py; do python \"$t\"; done — results are not persisted"},
    }


def workspace_meta(snap: Snapshot) -> dict:
    ws = snap.ws
    inv = snap.artifact(None, "01_inventory") or {}
    syn = snap.artifact(None, "07_synthesis", "brd_index.json") or {}
    return {"project": ws.repo.name, "repo": str(Path(ws.repo.name)),
            "output_dir": ws.rel(ws.output) or str(ws.output.name),
            "source_dir": redact(inv.get("source_dir")) if inv.get("source_dir") else None,
            "brd_name": "brd.md" if syn else None, "system": syn.get("system")}
