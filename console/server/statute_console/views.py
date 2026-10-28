"""API payload builders. Pure functions of a Snapshot."""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from . import registry as R
from .findings import annotation_status, attention, collect, next_steps, source_check
from .model import Snapshot, parse_iso, public_run, redact, sev_rank

TEXT_LIMIT = 2 * 1024 * 1024
TEXT_SUFFIXES = {".json", ".md", ".mmd", ".cypher", ".csv", ".txt", ".jsonl", ".sql"}


# ---------------------------------------------------------------------------
# status (home)
# ---------------------------------------------------------------------------

def status(snap: Snapshot) -> dict:
    src = source_check(snap)
    prun = snap.current_pipeline_run()
    ann = annotation_status(snap, prun)
    fs = collect(snap, prun, src, ann)
    stages = []
    for key in R.ORDER:
        st = snap.stages[key]
        stages.append({
            "stage": key, "title": st["title"], "n": st["n"], "purpose": st["purpose"],
            "latest": public_run(st["latest"]), "newest": public_run(st["newest"]),
            "freshness": st.get("freshness"),
            "key_stat": key_stat(snap, key),
            "worst_finding": _worst(fs, key),
            "run_count": len(st["runs"]), "attempt_count": len(st["attempts"]),
            "agent": R.BY_KEY[key]["agent"].replace("_agent.md", ""),
        })
    running = [s["stage"] for s in stages if (s["newest"] or {}).get("state") == "running"]
    recent = sorted([r for k in R.ORDER for r in snap.stages[k]["runs"] + snap.stages[k]["attempts"]],
                    key=lambda r: r["sort_key"], reverse=True)[:12]
    latest_activity = recent[0]["finished_at"] or recent[0]["started_at"] if recent else None
    counts = {s: sum(1 for f in fs if f["severity"] == s) for s in ("critical", "high", "medium", "low", "info")}
    return {
        "generated_at": snap.taken_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "corpus": corpus(snap, src),
        "running": running,
        "stages": stages,
        "attention": attention(fs),
        "finding_counts": counts,
        "pipeline_run": pipeline_summary(snap, prun) if prun else None,
        "next_steps": next_steps(snap, src),
        "recent": [_recent_row(snap, r) for r in recent],
        "latest_activity": latest_activity,
        "workspace": _workspace(snap),
        "kpis": kpis(snap, prun, stages),
        "annotations": {"present": ann["present"], "error": ann["error"],
                        "applied": sum(1 for e in ann["entries"] if e["status"] == "applied"),
                        "problems": sum(1 for e in ann["entries"] if e["status"] != "applied")},
    }


def kpis(snap: Snapshot, prun, stages) -> dict:
    def val(key, field):
        r = snap.stages[key]["latest"]
        return (((r or {}).get("summary") or {}).get("values") or {}).get(field)
    done = sum(1 for s in stages if (s["latest"] or {}).get("state") == "succeeded"
               and (s["freshness"] or {}).get("value") in ("current", "pinned", "unknown"))
    gaps = (snap.artifact(prun, "07_synthesis", "gaps_register.json") or {}).get("gaps", []) if prun else []
    files, size = 0, 0
    for key in R.ORDER:
        d = snap.member_dir(prun, key)
        if d:
            for f in d.rglob("*"):
                if f.is_file():
                    files += 1
                    size += f.stat().st_size
    inv = (snap.artifact(None, "01_inventory") or {}).get("summary") or {}
    syn = ((snap.runs.get(("07_synthesis", prun["anchor"])) or {}).get("summary") or {}).get("values", {}) if prun else {}
    return {
        "overall_pct": round(done / len(stages) * 100) if stages else 0, "stages_done": done, "stages_total": len(stages),
        "files": inv.get("total_files_ok"), "code_lines": inv.get("total_code_lines"),
        "objects": val("02_parser", "objects_parsed"), "statements": val("02_parser", "statements_extracted"),
        "tables": val("03_data", "tables_found"), "columns": val("03_data", "columns_total"),
        "rules": val("05_rules", "rules_extracted"), "sme": val("05_rules", "requires_sme_review"),
        "requirements": syn.get("requirements"), "gaps": len(gaps),
        "gaps_high": sum(1 for g in gaps if g.get("severity") in ("critical", "high")),
        "artifacts": files, "artifact_bytes": size, "span_ms": (prun or {}).get("span_ms"),
    }


def _workspace(snap):
    from .catalog import workspace_meta
    return workspace_meta(snap)


def corpus(snap: Snapshot, src: dict | None) -> dict:
    inv = snap.artifact(None, "01_inventory") or {}
    s = inv.get("summary") or {}
    return {"files": s.get("total_files_ok"), "code_lines": s.get("total_code_lines"),
            "lines": s.get("total_lines"), "roles": s.get("files_by_role"),
            "source_display": "src/" if src and src["missing"] == 0 and not src["source_dir_reachable"]
            else (src or {}).get("source_dir_display"),
            "source_reachable": bool(src) and src["unreachable"] == 0}


def _worst(fs, key):
    mine = [f for f in fs if f.get("stage") == key]
    if not mine:
        return None
    w = min(mine, key=lambda f: sev_rank(f["severity"]))
    return {"severity": w["severity"], "count": len(mine)}


def _recent_row(snap, r):
    return {"stage": r["stage"], "id": r["id"], "run_version": r["run_version"], "attempt": r["attempt"],
            "state": r["state"], "state_basis": r["state_basis"], "published": r["published"],
            "started_at": r["started_at"], "finished_at": r["finished_at"], "duration_ms": r["duration_ms"],
            "timing_basis": r["timing_basis"], "instrumented": r["instrumented"]}


def key_stat(snap: Snapshot, key: str) -> list[str]:
    r = snap.stages[key]["latest"]
    v = ((r or {}).get("summary") or {}).get("values") or {}
    a = snap.artifact(None, key) or {}
    if key == "01_inventory":
        s = a.get("summary") or {}
        return [f"{s.get('total_files_ok', '?')} files", f"{s.get('total_code_lines', '?')} code lines"]
    if key == "02_parser":
        return [f"{v.get('objects_parsed', '?')} objects · {v.get('statements_extracted', '?')} statements",
                f"{v.get('parse_errors', 0)} parse errors"]
    if key == "03_data":
        return [f"{v.get('tables_found', '?')} tables · {v.get('columns_total', '?')} columns",
                f"{v.get('comment_only_enums', 0)} comment-only enums"]
    if key == "04_logic":
        return [f"{v.get('objects_processed', '?')} objects analysed",
                f"{v.get('objects_with_transaction_hazards', 0)} with transaction hazards"]
    if key == "05_rules":
        return [f"{v.get('rules_extracted', '?')} rules", f"{v.get('requires_sme_review', 0)} need SME review"]
    if key == "06_diagram":
        st = a.get("stats") or {}
        return [f"{st.get('diagrams_generated', '?')} diagrams",
                f"largest {v.get('max_nodes_any_diagram', '?')} nodes (budget {a.get('node_budget', '?')})"]
    if key == "07_synthesis":
        return [f"{v.get('requirements', '?')} requirements", f"{v.get('gaps', '?')} open matters"]
    if key == "08_graph":
        n = sum((v.get("nodes") or {}).values()) if isinstance(v.get("nodes"), dict) else "?"
        e = sum((v.get("relationships") or {}).values()) if isinstance(v.get("relationships"), dict) else "?"
        return [f"{n} nodes · {e} relationships", f"{len(a.get('blind_spots') or [])} blind spots"]
    return []


# ---------------------------------------------------------------------------
# pipeline runs
# ---------------------------------------------------------------------------

def pipeline_summary(snap: Snapshot, p: dict) -> dict:
    syn = snap.runs.get(("07_synthesis", p["anchor"])) or {}
    counts = ((syn.get("summary") or {}).get("values")) or {}
    gaps = (snap.artifact(p, "07_synthesis", "gaps_register.json") or {}).get("gaps", [])
    sev = {s: sum(1 for g in gaps if g.get("severity") == s) for s in ("critical", "high", "medium", "low")}
    rules = (snap.artifact(p, "05_rules") or {}).get("stats") or {}
    diag = snap.artifact(p, "06_diagram") or {}
    deliverables = []
    for key, name, label in (("07_synthesis", "brd.md", "Business Requirements Document"),
                             ("07_synthesis", "brd_index.json", "BRD machine index"),
                             ("07_synthesis", "gaps_register.json", "Gaps register"),
                             ("03_data", "erd.mmd", "Entity-relationship diagram"),
                             ("08_graph", "import.cypher", "Graph export (Cypher)")):
        d = snap.member_dir(p, key)
        if d and (d / name).is_file():
            deliverables.append({"label": label, "stage": key, "run_version": p["members"].get(key),
                                 "artifact_id": artifact_id(name), "path": snap.ws.rel(d / name)})
    return {**p, "counts": counts, "open_matters": sev, "rules_need_review": rules.get("requires_sme_review"),
            "diagrams": len(diag.get("diagram_index") or {}), "deliverables": deliverables}


def pipeline_detail(snap: Snapshot, p: dict) -> dict:
    members = []
    for key in R.ORDER:
        rv = p["members"].get(key)
        r = snap.runs.get((key, rv)) if rv else None
        members.append({"stage": key, "title": R.BY_KEY[key]["title"], "run": public_run(r),
                        "inferred": key in p["inferred_members"],
                        "is_published": bool(r) and r["published"],
                        "latest_run_version": snap.stages[key]["latest_run_version"]})
    return {**pipeline_summary(snap, p), "member_runs": members, "timeline": timeline(snap, p),
            "lineage": lineage(snap, p)}


def timeline(snap: Snapshot, p: dict) -> dict:
    rows = []
    for key in R.ORDER:
        rv = p["members"].get(key)
        r = snap.runs.get((key, rv)) if rv else None
        if not r or not r["started_at"]:
            continue
        rows.append({"stage": key, "run_version": rv, "start": r["started_at"],
                     "end": r["finished_at"] or r["started_at"], "basis": r["timing_basis"],
                     "duration_ms": r["duration_ms"], "state": r["state"]})
    rows.sort(key=lambda x: x["start"])
    gaps, prev = [], None
    for row in rows:
        if prev:
            a, b = parse_iso(prev["end"]), parse_iso(row["start"])
            if a and b and (b - a).total_seconds() > 0:
                gaps.append({"after": prev["stage"], "before": row["stage"], "start": prev["end"],
                             "end": row["start"], "ms": int((b - a).total_seconds() * 1000)})
        prev = row
    starts = [parse_iso(r["start"]) for r in rows]
    ends = [parse_iso(r["end"]) for r in rows]
    span = int((max(ends) - min(starts)).total_seconds() * 1000) if rows else 0
    busy = sum(r["duration_ms"] or 0 for r in rows)
    return {"rows": rows, "gaps": gaps, "span_ms": span, "in_stage_ms": busy,
            "between_ms": sum(g["ms"] for g in gaps),
            "partial": any(r["basis"] != "recorded" for r in rows)}


def lineage(snap: Snapshot, p: dict) -> dict:
    nodes, edges = [], []
    for key in R.ORDER:
        rv = p["members"].get(key)
        r = snap.runs.get((key, rv)) if rv else None
        nodes.append({"stage": key, "title": R.BY_KEY[key]["title"], "run_version": rv,
                      "state": (r or {}).get("state"), "freshness": (snap.stages[key].get("freshness") or {}).get("value")
                      if r and r["published"] else ("superseded" if r else None),
                      "inferred": key in p["inferred_members"], "provenance_gaps": (r or {}).get("provenance_gaps", [])})
        if not r:
            continue
        for u in r["upstream"]:
            member = p["members"].get(u["stage"])
            edges.append({"from": u["stage"], "to": key, "run_version": u["run_version"],
                          "resolved": u["resolved"], "present": u["present"], "optional": u["optional"],
                          "matches_member": u["run_version"] == member if u["run_version"] else None})
        for g in r.get("provenance_gaps", []):
            edges.append({"from": g, "to": key, "run_version": None, "resolved": "unrecorded",
                          "present": None, "optional": g in R.BY_KEY[key]["optional"], "matches_member": None})
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# stage runs
# ---------------------------------------------------------------------------

def stage_info(snap: Snapshot, key: str) -> dict:
    s = R.BY_KEY[key]
    st = snap.stages[key]
    return {**{k: s[k] for k in ("key", "n", "title", "purpose", "script", "agent", "requires", "optional", "artifact")},
            "dir": st["dir"], "downstream": R.downstream_of(key),
            "latest_run_version": st["latest_run_version"], "freshness": st.get("freshness"),
            "runs": [public_run(r) for r in st["runs"]], "attempts": [public_run(r) for r in st["attempts"]]}


def stage_run_detail(snap: Snapshot, key: str, rid: str) -> dict | None:
    r = snap.runs.get((key, rid))
    if not r:
        return None
    d = snap.ws.run_dir(key, rid)
    consumers = []
    if r["run_version"]:
        for k2 in R.downstream_of(key):
            for r2 in snap.stages[k2]["runs"]:
                if any(u["stage"] == key and u["run_version"] == r["run_version"] for u in r2["upstream"]):
                    consumers.append({"stage": k2, "run_version": r2["run_version"], "published": r2["published"]})
    latest = {u["stage"]: snap.stages[u["stage"]]["latest_run_version"] for u in r["upstream"] if u["stage"] in snap.stages}
    meta, _ = snap.ws.load_json(d / "run_meta.json") if d else (None, None)
    if r.get("summary"):
        text = summary_text(key, r["summary"]["values"] or {}, snap_artifact_for_run(snap, key, d))
    else:
        # never print a stats sentence from an empty summary ("Parsed ? objects…")
        p = r.get("progress") or {}
        how_far = f" It reached {p.get('done')} of {p.get('total')} {p.get('unit')}." if p.get("total") else ""
        text = [{"running": "Running — no summary until the stage finishes." + how_far,
                 "failed": "Failed before writing its summary (run_meta.json); no outputs were published." + how_far,
                 "crashed": "Stopped without recording an outcome; no outputs were published." + how_far,
                 }.get(r["state"], "No summary recorded.")]
    return {**public_run(r), "title": R.BY_KEY[key]["title"],
            "freshness": snap.stages[key].get("freshness") if r["published"] else None,
            "summary_text": text,
            "consumers": consumers, "upstream_latest": latest,
            "pipeline_runs": [p["id"] for p in snap.pipeline_runs if p["members"].get(key) == r["run_version"]],
            "rerun_command": f"python .claude/scripts/{R.BY_KEY[key]['script']}",
            "run_meta": _redact_obj(meta) if isinstance(meta, dict) else None}


def snap_artifact_for_run(snap, key, d):
    if not d:
        return {}
    data, _ = snap.ws.load_json(d / R.BY_KEY[key]["artifact"])
    return data if isinstance(data, dict) else {}


def summary_text(key: str, v: dict, art: dict) -> list[str]:
    if key == "01_inventory":
        s = art.get("summary") or {}
        roles = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in (s.get("files_by_role") or {}).items())
        return [f"Catalogued {s.get('total_files_ok', v.get('total_files_ok', '?'))} source files "
                f"({s.get('total_lines', '?')} lines, {s.get('total_code_lines', '?')} code): {roles}.",
                f"{len(s.get('files_with_warnings') or [])} file(s) with warnings; {s.get('total_files_unreadable', 0)} unreadable."]
    if key == "02_parser":
        return [f"Parsed {v.get('objects_parsed', '?')} objects ({v.get('package_members', 0)} package members) into "
                f"{v.get('statements_extracted', '?')} statements with control-flow graphs.",
                f"{v.get('parse_errors', 0)} parse errors · {v.get('unresolved_calls', 0)} unresolved calls · "
                f"{v.get('dynamic_sql_blocks', 0)} dynamic SQL blocks.",
                f"{art.get('files_passthrough', 0)} file(s) passed through to 03_data."]
    if key == "03_data":
        return [f"{v.get('tables_found', '?')} tables, {v.get('columns_total', '?')} columns, {v.get('indexes_found', 0)} indexes, "
                f"{v.get('sequences_found', 0)} sequences.",
                f"{v.get('declared_foreign_keys', 0)} declared and {v.get('inferred_foreign_keys', 0)} inferred foreign keys; "
                f"{v.get('check_constraints', 0)} CHECK constraints ({v.get('disabled_constraints', 0)} disabled).",
                f"{v.get('comment_only_enums', 0)} permitted-value lists exist only in comments."]
    if key == "04_logic":
        return [f"Analysed {v.get('objects_processed', '?')} objects: {v.get('statements_translated', '?')} pseudocode lines, "
                f"{v.get('variable_slices', 0)} variable slices.",
                f"{v.get('objects_exceeding_cyclomatic_threshold', 0)} over the cyclomatic threshold; "
                f"{v.get('objects_with_transaction_hazards', 0)} with transaction hazards."]
    if key == "05_rules":
        cats = ", ".join(f"{n} {k.lower().replace('_', ' ')}" for k, n in (v.get("by_category") or {}).items() if n)
        conf = ", ".join(f"{n} {k}" for k, n in (v.get("by_confidence") or {}).items() if n)
        return [f"Extracted {v.get('rules_extracted', '?')} business rules ({cats}).",
                f"Confidence: {conf}. {v.get('requires_sme_review', 0)} need SME review; "
                f"{v.get('duplicates_merged', 0)} duplicates merged."]
    if key == "06_diagram":
        st = art.get("stats") or {}
        return [f"Rendered {st.get('diagrams_generated', '?')} diagrams ({st.get('process_flows', '?')} process flows, "
                f"{st.get('state_models', '?')} state model, {st.get('dataflow', '?')} data-flow map).",
                f"Decision labels from rules: {round(100 * (v.get('decision_label_tier1_pct') or 0))}% · "
                f"branch traceability {round(100 * (v.get('branch_traceability_pct') or 0))}% · "
                f"largest diagram {v.get('max_nodes_any_diagram', '?')} nodes (budget {art.get('node_budget', '?')})."]
    if key == "07_synthesis":
        return [f"BRD with {v.get('requirements', '?')} requirements across {v.get('capabilities', '?')} capabilities; "
                f"{v.get('gaps', '?')} open matters; {v.get('annotations_applied', 0)} human annotations applied."]
    if key == "08_graph":
        n = v.get("nodes") or {}
        e = v.get("relationships") or {}
        return [f"Knowledge graph: {sum(n.values()) if n else '?'} nodes across {len(n)} labels, "
                f"{sum(e.values()) if e else '?'} relationships across {len(e)} types.",
                f"{len(art.get('blind_spots') or [])} declared blind spots; {len(art.get('supported_questions') or [])} answerable questions."]
    return []


def _redact_obj(o):
    if isinstance(o, dict):
        return {k: _redact_obj(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_redact_obj(v) for v in o]
    if isinstance(o, str):
        return redact(o)
    return o


def stage_run_items(snap: Snapshot, key: str, rid: str) -> dict | None:
    d = snap.ws.run_dir(key, rid)
    if d is None:
        return None
    art = snap_artifact_for_run(snap, key, d)
    durations, item_status = _item_timing(snap, d)
    cols, rows = [], []
    if key == "01_inventory":
        cols = ["file", "role", "status", "lines", "code lines", "warnings"]
        for fid, m in sorted((art.get("file_metadata") or {}).items()):
            lc = m.get("line_counts") or {}
            rows.append({"id": fid, "kind": "file", "file": m.get("file"), "role": m.get("file_role"),
                         "status": m.get("status"), "lines": lc.get("total_lines"), "code lines": lc.get("code_lines"),
                         "warnings": len(m.get("warnings") or [])})
    elif key == "02_parser":
        cols = ["object", "type", "parse status", "statements", "issues", "duration"]
        for oid, rel in (art.get("object_index") or {}).items():
            o, _ = snap.ws.load_json(d / rel)
            o = o if isinstance(o, dict) else {}
            rows.append({"id": oid, "kind": "object", "object": oid, "type": o.get("type"),
                         "parse status": o.get("parse_status"), "statements": len(o.get("statements") or {}),
                         "issues": len(o.get("parse_issues") or []), "duration": durations.get(("object", oid))})
    elif key == "03_data":
        cols = ["table", "columns", "checks", "foreign keys", "file"]
        for t, m in sorted((art.get("tables") or {}).items()):
            rows.append({"id": t, "kind": "table", "table": t, "columns": len(m.get("columns") or []),
                         "checks": len(m.get("check_constraints") or []), "foreign keys": len(m.get("foreign_keys") or []),
                         "file": m.get("source_file")})
    elif key == "04_logic":
        cols = ["object", "shape", "cyclomatic", "cognitive", "hazards"]
        for oid, rel in (art.get("object_index") or {}).items():
            o, _ = snap.ws.load_json(d / rel)
            o = o if isinstance(o, dict) else {}
            cx = o.get("complexity") or {}
            rows.append({"id": oid, "kind": "object", "object": oid, "shape": (o.get("shape") or {}).get("shape"),
                         "cyclomatic": (cx.get("cyclomatic") or {}).get("score"),
                         "cognitive": (cx.get("cognitive") or {}).get("score"),
                         "hazards": len((o.get("transactions") or {}).get("hazards") or [])})
    elif key == "05_rules":
        cols = ["rule", "name", "category", "confidence", "SME review", "line"]
        for r in art.get("business_rules") or []:
            rows.append({"id": r["rule_id"], "kind": "rule", "rule": r["rule_id"], "name": r.get("name"),
                         "category": r.get("category"), "confidence": r.get("confidence"),
                         "SME review": r.get("requires_sme_review"), "line": (r.get("source") or {}).get("line")})
    elif key == "06_diagram":
        cols = ["diagram", "type", "nodes", "edges", "budget"]
        for f, m in (art.get("diagram_index") or {}).items():
            b = m.get("budget") or {}
            rows.append({"id": f, "kind": "diagram", "diagram": f, "type": m.get("type"), "nodes": m.get("nodes"),
                         "edges": m.get("edges"), "budget": "over budget" if b.get("oversize") else "within"})
    elif key == "07_synthesis":
        idx, _ = snap.ws.load_json(d / "brd_index.json")
        cols = ["requirement", "heading", "confidence", "needs review"]
        for q in (idx or {}).get("requirements") or []:
            rows.append({"id": q["id"], "kind": "rule", "requirement": q["id"], "heading": q.get("heading"),
                         "confidence": q.get("confidence"), "needs review": q.get("needs_review")})
    elif key == "08_graph":
        cols = ["label", "nodes"]
        for lab, n in ((art.get("stats") or {}).get("nodes") or {}).items():
            rows.append({"id": lab, "kind": "label", "label": lab, "nodes": n})
    for row in rows:
        st = item_status.get((row["kind"], row["id"]))
        if st:
            row["event_status"] = st
    return {"columns": cols, "rows": rows}


def _item_timing(snap, d):
    events, _ = snap.ws.cache.load_jsonl(d / "events.jsonl")
    starts, durations, status = {}, {}, {}
    for e in events:
        it = e.get("item")
        if not it:
            continue
        k = (it.get("kind"), it.get("id"))
        t = parse_iso(e.get("time"))
        if e.get("type") == "item.started":
            starts[k] = t
        else:
            status[k] = e.get("status")
            if k in starts and t and starts[k]:
                durations[k] = int((t - starts[k]).total_seconds() * 1000)
    return durations, status


def stage_run_findings(snap: Snapshot, key: str, rid: str) -> list[dict] | None:
    d = snap.ws.run_dir(key, rid)
    if d is None:
        return None
    art = snap_artifact_for_run(snap, key, d)
    out = []

    def add(sev, kind, title, loc=None, detail=None):
        out.append({"severity": sev, "kind": kind, "title": redact(title)[:300], "location": loc,
                    "detail": redact(detail)[:600] if detail else None})
    if key == "01_inventory":
        for fid, m in (art.get("file_metadata") or {}).items():
            for w in m.get("warnings") or []:
                add("low", "file_warning", f"{m.get('file')}: {w}", {"file_id": fid, "file": m.get("file")})
    elif key in ("02_parser", "03_data"):
        sev = {"error": "high", "warning": "medium", "info": "info"}
        for i in art.get("issues") or []:
            add("critical" if i.get("type") == "syntax_error" else sev.get(i.get("severity"), "low"),
                i.get("type", "issue"), f"{i.get('type')}: {i.get('message', '')}",
                {"file": i.get("file"), "line": i.get("line")})
    elif key == "04_logic":
        for oid, rel in (art.get("object_index") or {}).items():
            o, _ = snap.ws.load_json(d / rel)
            for h in ((o or {}).get("transactions") or {}).get("hazards") or []:
                add({"high": "high", "info": "info"}.get(h.get("severity"), "medium"), h.get("hazard", "hazard"),
                    f"{oid}: {str(h.get('hazard', '')).replace('_', ' ').lower()}",
                    {"object_id": oid, "line": ([x.get("line") for x in h.get("occurrences", [])] or [None])[0]},
                    h.get("explanation"))
            cx = ((o or {}).get("complexity") or {}).get("cyclomatic") or {}
            if cx.get("exceeds_threshold"):
                add("medium", "high_complexity", f"{oid}: cyclomatic {cx.get('score')} > threshold {cx.get('threshold')}",
                    {"object_id": oid})
    elif key == "05_rules":
        for r in art.get("business_rules") or []:
            if r.get("requires_sme_review") or r.get("confidence") in ("low", "medium"):
                add("high" if r.get("requires_sme_review") else "low",
                    "sme_review" if r.get("requires_sme_review") else "medium_confidence",
                    f"{r['rule_id']} {r.get('name')} ({r.get('confidence')} confidence)",
                    {"rule_id": r["rule_id"], "line": (r.get("source") or {}).get("line")}, r.get("condition_text"))
    elif key == "06_diagram":
        for w in art.get("warnings") or []:
            add("medium" if w.get("kind") == "OVERSIZE" else "low", w.get("kind", "warning"),
                f"{w.get('diagram')}: {w.get('detail')}")
    elif key == "07_synthesis":
        gaps, _ = snap.ws.load_json(d / "gaps_register.json")
        for g in (gaps or {}).get("gaps") or []:
            add(g.get("severity", "low"), g.get("gap_type", "gap"), f"{g.get('gap_id')} {g.get('title')}",
                {"gap_id": g.get("gap_id")}, g.get("description"))
    elif key == "08_graph":
        for b in art.get("blind_spots") or []:
            add("info", f"blind_spot_{b.get('kind')}", f"Blind spot: {b.get('kind')}", None, b.get("detail"))
    out.sort(key=lambda f: sev_rank(f["severity"]))
    return out


# ---------------------------------------------------------------------------
# artifacts and events
# ---------------------------------------------------------------------------

def artifact_id(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def list_artifacts(snap: Snapshot, key: str, rid: str) -> list[dict] | None:
    d = snap.ws.run_dir(key, rid)
    if d is None:
        return None
    out = []
    for f in sorted(d.rglob("*")):
        if not f.is_file() or f.is_symlink():
            continue
        rel = f.relative_to(d).as_posix()
        try:
            size = f.stat().st_size
        except OSError:
            continue
        kind = ("witness" if f.name in ("run_status.json", "events.jsonl") else
                "metadata" if f.name == "run_meta.json" else
                "per-item" if "/" in rel else "artifact")
        out.append({"id": artifact_id(rel), "path": rel, "bytes": size, "kind": kind,
                    "suffix": f.suffix.lower()})
        if len(out) >= 5000:
            break
    return out


def read_artifact(snap: Snapshot, key: str, rid: str, aid: str) -> dict | None:
    d = snap.ws.run_dir(key, rid)
    if d is None:
        return None
    for a in list_artifacts(snap, key, rid) or []:
        if a["id"] == aid:
            p = (d / a["path"]).resolve()
            try:
                p.relative_to(d.resolve())
            except ValueError:
                return None
            if a["suffix"] not in TEXT_SUFFIXES:
                return {**a, "text": None, "truncated": False, "reason": "binary or unsupported type"}
            with open(p, "rb") as fh:
                raw = fh.read(TEXT_LIMIT + 1)
            text = raw[:TEXT_LIMIT].decode("utf-8", errors="replace")
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            return {**a, "text": redact(text) if a["suffix"] in (".json", ".jsonl") else text,
                    "truncated": len(raw) > TEXT_LIMIT, "sha256": h,
                    "content_type": mimetypes.guess_type(p.name)[0] or "text/plain"}
    return None


def run_events(snap: Snapshot, key: str, rid: str, after: int = 0, limit: int = 1000) -> dict | None:
    d = snap.ws.run_dir(key, rid)
    if d is None:
        return None
    events, err = snap.ws.cache.load_jsonl(d / "events.jsonl")
    sel = [_clean_event(e) for e in events if int(e.get("seq") or 0) > after][:limit]
    return {"events": sel, "error": None if err == "missing" else err, "available": err != "missing",
            "last_seq": max([int(e.get("seq") or 0) for e in events] or [0])}


def recent_events(snap: Snapshot, since: str | None = None, limit: int = 500, max_runs: int = 40) -> dict:
    runs = sorted([r for k in R.ORDER for r in snap.stages[k]["runs"] + snap.stages[k]["attempts"] if r["instrumented"]],
                  key=lambda r: r["sort_key"], reverse=True)[:max_runs]
    rows = []
    for r in runs:
        d = snap.ws.run_dir(r["stage"], r["id"])
        if not d:
            continue
        events, _ = snap.ws.cache.load_jsonl(d / "events.jsonl")
        for e in events:
            if since and (e.get("time") or "") <= since:
                continue
            ce = _clean_event(e)
            ce["run_id"] = r["id"]
            rows.append(ce)
    rows.sort(key=lambda e: (e.get("time") or "", e.get("seq") or 0))
    total = len(rows)
    rows = rows[-limit:]
    return {"events": rows, "total": total, "truncated": total > len(rows),
            "cursor": rows[-1]["time"] if rows else since,
            "uninstrumented_runs": sum(1 for k in R.ORDER for r in snap.stages[k]["runs"] if not r["instrumented"])}


def _clean_event(e: dict) -> dict:
    out = {k: e.get(k) for k in ("event_id", "seq", "time", "type", "stage", "run_version", "status",
                                 "severity", "item", "progress", "traceparent") if e.get(k) is not None}
    if e.get("message"):
        out["message"] = redact(e["message"])[:500]
    if e.get("data"):
        out["data"] = _redact_obj(e["data"])
    return out


_ = Path
