"""Findings: one normalised queue of everything that needs attention.

Sources, in order of how badly each misleads a human if hidden:
  run      — failed, crashed or unpublished stage runs (run_status / directory evidence)
  lineage  — unsynced or inconsistent inputs, unrecorded provenance, degraded inputs
  source   — corpus files unreachable at their recorded path, or changed since inventory
  content  — the BRD gaps register, parser/data issues not already in it, graph blind spots
  review   — rules and gaps needing an SME, and the state of human annotations
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from . import registry as R
from .model import Snapshot, redact, sev_rank

CATEGORY_ORDER = ["run", "lineage", "source", "content", "review"]
REVIEW_GAP_TYPES = {"SME_REVIEW_REQUIRED", "MEDIUM_CONFIDENCE_RULE", "UNDOCUMENTED_ENUM", "CONSTRAINT_DISABLED"}
_sha_cache: dict[str, tuple] = {}
_sha_lock = threading.Lock()


def _sha256(p: Path) -> str | None:
    try:
        st = p.stat()
    except OSError:
        return None
    key, sig = str(p), (st.st_mtime_ns, st.st_size)
    with _sha_lock:
        hit = _sha_cache.get(key)
        if hit and hit[0] == sig:
            return hit[1]
    try:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None
    with _sha_lock:
        _sha_cache[key] = (sig, h)
    return h


def _f(category, severity, kind, title, detail=None, *, stage=None, run_version=None, subject=None,
       location=None, related=None, evidence=None, next_step=None, fid=None, count=1, members=None):
    return {"id": fid or f"{category}:{kind}:{stage or ''}:{(subject or {}).get('id', title)}",
            "category": category, "severity": severity, "kind": kind, "title": title,
            "detail": detail, "stage": stage, "run_version": run_version, "subject": subject,
            "location": location, "related": related or [], "evidence": evidence or [],
            "next_step": next_step, "count": count, "members": members or []}


# ---------------------------------------------------------------------------
# source files
# ---------------------------------------------------------------------------

def source_check(snap: Snapshot) -> dict | None:
    ws = snap.ws
    inv = snap.artifact(None, "01_inventory")
    if not inv:
        return None
    rows = []
    for fid, meta in sorted((inv.get("file_metadata") or {}).items()):
        recorded = meta.get("abs_path")
        recorded_ok = bool(recorded) and Path(recorded).is_file()
        p, how = ws.resolve_source(meta)
        now = _sha256(p) if p else None
        rows.append({"file_id": fid, "file": meta.get("file"), "recorded_reachable": recorded_ok,
                     "resolved_via": how, "resolved_path": ws.rel(p) if p else None,
                     "sha256_recorded": meta.get("sha256"), "sha256_now": now,
                     "changed": (now != meta.get("sha256")) if now and meta.get("sha256") else None})
    sd = inv.get("source_dir")
    return {
        "source_dir_display": redact(sd) if sd else None,
        "source_dir_reachable": bool(sd) and Path(sd).is_dir(),
        "files": rows,
        "unreachable": sum(1 for r in rows if not r["recorded_reachable"]),
        "missing": sum(1 for r in rows if r["resolved_path"] is None),
        "changed": sum(1 for r in rows if r["changed"]),
        "inventory_run_version": snap.stages["01_inventory"]["latest_run_version"],
    }


# ---------------------------------------------------------------------------
# annotations
# ---------------------------------------------------------------------------

def _rule_sig(r: dict) -> tuple:
    s = r.get("source") or {}
    return (s.get("kind"), s.get("statement_id") or s.get("constraint_name") or s.get("column") or s.get("view"),
            s.get("table"), r.get("condition_text"))


def annotation_status(snap: Snapshot, prun: dict | None) -> dict:
    ws = snap.ws
    path = ws.annotations_path
    out = {"present": path.is_file(), "path": ws.rel(path), "error": None, "entries": []}
    if not out["present"]:
        return out
    data, err = ws.load_json(path)
    if err or not isinstance(data, dict) or not isinstance(data.get("annotations"), dict):
        out["error"] = err or "expected an object with an 'annotations' map"
        return out
    rules_a = snap.artifact(prun, "05_rules") or {}
    rules = {r["rule_id"]: r for r in rules_a.get("business_rules", [])}
    prev = None
    if prun:
        older = [p for p in snap.pipeline_runs if p["anchor"] < prun["anchor"]]
        prev = older[0] if older else None
    prev_rules = {r["rule_id"]: r for r in (snap.artifact(prev, "05_rules") or {}).get("business_rules", [])} if prev else {}
    data_a = snap.artifact(prun, "03_data") or {}
    tables = set((data_a.get("tables") or {}).keys())
    columns = {c.get("column_id") for c in data_a.get("column_catalogue") or []}
    objects = set(((snap.artifact(prun, "02_parser") or {}).get("object_index") or {}).keys())
    for key, val in sorted(data["annotations"].items()):
        note = (val or {}).get("note") if isinstance(val, dict) else None
        entry = {"key": key, "owner": (val or {}).get("owner") if isinstance(val, dict) else None,
                 "note_length": len(note or ""), "status": "applied", "detail": None, "target": None}
        if key.startswith("BR-"):
            entry["target"] = {"kind": "rule", "id": key}
            if key not in rules:
                entry["status"], entry["detail"] = "orphaned", "no rule with this id in the current rules run"
            elif key in prev_rules and _rule_sig(prev_rules[key]) != _rule_sig(rules[key]):
                entry["status"] = "repointed"
                entry["detail"] = (f"{key} now names \"{rules[key].get('name')}\"; in the previous pipeline run it "
                                   f"named \"{prev_rules[key].get('name')}\" — rule ids are renumbered when rules change")
        elif key.startswith("table:"):
            entry["target"] = {"kind": "table", "id": key[6:]}
            if key[6:] not in tables:
                entry["status"], entry["detail"] = "orphaned", "table not in the current data dictionary"
        elif key.startswith("term:"):
            entry["target"] = {"kind": "column", "id": key[5:]}
            if key[5:] not in columns:
                entry["status"], entry["detail"] = "orphaned", "column not in the current data dictionary"
        elif key.startswith("object:"):
            entry["target"] = {"kind": "object", "id": key[7:]}
            if key[7:] not in objects:
                entry["status"], entry["detail"] = "orphaned", "object not in the current parser run"
        elif key.startswith("param:"):
            oid = key[6:].rsplit(":", 1)[0]
            entry["target"] = {"kind": "object", "id": oid}
            if oid not in objects:
                entry["status"], entry["detail"] = "orphaned", "object not in the current parser run"
        elif key != "executive_summary":
            entry["status"], entry["detail"] = "orphaned", "unrecognised annotation key format"
        out["entries"].append(entry)
    return out


# ---------------------------------------------------------------------------
# the queue
# ---------------------------------------------------------------------------

def collect(snap: Snapshot, prun: dict | None = None, src: dict | None = None, ann: dict | None = None) -> list[dict]:
    ws = snap.ws
    prun = prun if prun is not None else snap.current_pipeline_run()
    out: list[dict] = []

    # ---- run problems: anything newer than the published run that did not succeed
    for key in R.ORDER:
        st = snap.stages[key]
        latest_rv = st["latest_run_version"] or ""
        latest_sort = (st["latest"] or {}).get("sort_key") or ""
        for r in st["runs"] + st["attempts"]:
            # only what happened after the published run matters; earlier failures were superseded
            if r["published"] or r["sort_key"] <= latest_sort:
                continue
            if r["state"] in ("failed", "crashed"):
                e = r["error"] or {}
                where = f" at {e['where']}" if e.get("where") else ""
                item = e.get("last_item") or {}
                title = (f"{key} {'attempt' if r['attempt'] else 'run'} {r['run_version'] or r['id'][8:]} "
                         f"{r['state']}" + (f": {e['class']}{where}" if e.get("class") else ""))
                detail = e.get("message") or r["state_reason"]
                if item:
                    detail = f"{detail} (while processing {item.get('kind')} {item.get('id')})"
                out.append(_f("run", "high", f"run_{r['state']}", title, detail, stage=key,
                              run_version=r["run_version"], subject={"kind": "stage_run", "id": f"{key}/{r['id']}"},
                              evidence=r["evidence"] or [{"label": "run directory", "path": r["dir"]}],
                              next_step=f"latest.json still points at {latest_rv or 'nothing'}; fix the cause and re-run {key}"))
            elif r["state"] == "succeeded" and not r["attempt"]:
                out.append(_f("run", "high", "run_unpublished",
                              f"{key} run {r['run_version']} succeeded but was never published",
                              "run_meta.json says success but latest.json was not updated to point at it "
                              "(the pointer write failed). Downstream stages still read the older run.",
                              stage=key, run_version=r["run_version"], evidence=r["evidence"],
                              subject={"kind": "stage_run", "id": f"{key}/{r['id']}"}))

    # ---- lineage
    for key in R.ORDER:
        st = snap.stages[key]
        run = st["latest"]
        if not run:
            continue
        fr = st.get("freshness") or {}
        unrecorded = [c["stage"] for c in fr.get("causes", []) if c["kind"] == "unknown"]
        if unrecorded:
            what = (f"which {' or '.join(unrecorded)} run it consumed" if len(unrecorded) <= 2
                    else f"which runs of its {len(unrecorded)} inputs it consumed")
            out.append(_f("lineage", "low", "provenance_unrecorded", f"{key} does not record {what}",
                          "Staleness against those inputs cannot be checked for this run. Runs made with the "
                          "instrumented scripts record every input.", stage=key, run_version=run["run_version"],
                          evidence=run["evidence"], subject={"kind": "stage", "id": key},
                          fid=f"lineage:provenance:{key}"))
        for c in fr.get("causes", []):
            if c["kind"] == "unsynced":
                out.append(_f("lineage", "medium", "unsynced", f"{key} is out of date", c["text"], stage=key,
                              run_version=run["run_version"], evidence=run["evidence"],
                              subject={"kind": "stage", "id": key},
                              next_step=f"re-run {key} and the stages downstream of it"))
        for d in run["degraded"]:
            out.append(_f("lineage", "medium", "degraded", f"{key} ran with incomplete input: {d.get('input')}",
                          f"{d.get('reason')}. Its output may be smaller than a full run's, with no other signal.",
                          stage=key, run_version=run["run_version"], evidence=run["evidence"],
                          subject={"kind": "stage", "id": key}, fid=f"lineage:degraded:{key}:{d.get('input')}"))
    if prun and prun["consistency"] == "inconsistent":
        for inc in prun["inconsistencies"]:
            out.append(_f("lineage", "high", "inconsistent",
                          f"Pipeline run mixes {len(inc['versions'])} different {inc['stage']} runs",
                          "; ".join(f"{v['run_version']} consumed by {', '.join(v['consumed_by'])}" for v in inc["versions"]),
                          stage=inc["stage"], subject={"kind": "pipeline_run", "id": prun["id"]}))
    if prun and prun["missing_members"]:
        out.append(_f("lineage", "medium", "member_missing", "Pipeline run refers to runs that are no longer on disk",
                      ", ".join(f"{m['stage']} {m['run_version']}" for m in prun["missing_members"]),
                      subject={"kind": "pipeline_run", "id": prun["id"]}))

    # ---- source
    src = src if src is not None else source_check(snap)
    if src:
        inv_ev = [{"label": "inventory-artifact.json",
                   "path": ws.rel(snap.member_dir(None, "01_inventory") / "inventory-artifact.json")}]
        if src["unreachable"]:
            fb = len(src["files"]) - src["missing"]
            out.append(_f("source", "high", "source_unreachable",
                          f"Recorded source path not found for {src['unreachable']} of {len(src['files'])} files",
                          (f"The inventory records {src['source_dir_display']}. "
                           + (f"{fb} file(s) were found by relative path under src/"
                              + (" with identical contents." if not src["changed"] else ".") if fb else "No fallback copy was found.")
                           + " Re-running any stage after 01_inventory would crash (02, 03) or silently lose content (04–06)."),
                          stage="01_inventory", run_version=src["inventory_run_version"], evidence=inv_ev,
                          next_step="re-run 01_inventory against the current source directory first"))
        if src["changed"]:
            out.append(_f("source", "medium", "source_changed",
                          f"{src['changed']} source file(s) changed since the inventory run",
                          ", ".join(r["file"] for r in src["files"] if r["changed"]),
                          stage="01_inventory", run_version=src["inventory_run_version"], evidence=inv_ev,
                          next_step="re-run the pipeline from 01_inventory"))

    # ---- content (from the pipeline run's own artifacts)
    if prun:
        gaps = (snap.artifact(prun, "07_synthesis", "gaps_register.json") or {}).get("gaps", [])
        rules = {r["rule_id"]: r for r in (snap.artifact(prun, "05_rules") or {}).get("business_rules", [])}
        syn_dir = snap.member_dir(prun, "07_synthesis")
        for g in gaps:
            related = [{"kind": "rule", "id": rid} for rid in _as_list(g.get("related_rule_ids"))]
            loc = None
            for rel in related:
                src_ = (rules.get(rel["id"]) or {}).get("source") or {}
                if src_.get("line") is not None:
                    loc = {"object_id": src_.get("object_id"), "statement_id": src_.get("statement_id"),
                           "line": src_.get("line")}
                    break
            cat = "review" if g.get("gap_type") in REVIEW_GAP_TYPES else "content"
            out.append(_f(cat, g.get("severity", "low"), g.get("gap_type", "GAP"), g.get("title", g.get("gap_id")),
                          g.get("description"), stage=_detected_stage(g), run_version=prun["members"].get("07_synthesis"),
                          subject={"kind": "gap", "id": g.get("gap_id")}, location=loc, related=related,
                          evidence=[{"label": "gaps_register.json", "path": ws.rel(syn_dir / "gaps_register.json")}] if syn_dir else [],
                          fid=f"gap:{g.get('gap_id')}"))
        parser = snap.artifact(prun, "02_parser") or {}
        by_file: dict[str, list] = {}
        for i in parser.get("issues", []) or []:
            if i.get("type") == "syntax_error":
                by_file.setdefault(i.get("file"), []).append(i)
            elif i.get("severity") in ("error", "warning"):
                out.append(_f("content", "medium" if i["severity"] == "warning" else "high", i.get("type", "issue"),
                              redact(i.get("message", i.get("type")))[:300], stage="02_parser",
                              run_version=prun["members"].get("02_parser"),
                              location={"file": i.get("file"), "line": i.get("line")}))
        for fname, errs in sorted(by_file.items()):
            first = errs[0]
            out.append(_f("content", "critical", "syntax_error",
                          f"{len(errs)} syntax error(s) in {fname}",
                          "Objects from this file may still be recorded as parsed successfully with an incomplete "
                          f"statement tree. First error at line {first.get('line')}: "
                          + redact(first.get("message", ""))[:240],
                          stage="02_parser", run_version=prun["members"].get("02_parser"),
                          location={"file": fname, "line": first.get("line")}, fid=f"parser:syntax:{fname}"))
        data = snap.artifact(prun, "03_data") or {}
        for i in data.get("issues", []) or []:
            if i.get("type", "").startswith("constraint_"):
                continue                    # surfaced by the gaps register
            out.append(_f("content", {"error": "high", "warning": "medium"}.get(i.get("severity"), "low"),
                          i.get("type", "issue"), redact(i.get("message", i.get("type")))[:300], stage="03_data",
                          run_version=prun["members"].get("03_data"),
                          location={"file": i.get("file"), "line": i.get("line")}))
        graph = snap.artifact(prun, "08_graph") or {}
        for b in graph.get("blind_spots", []) or []:
            out.append(_f("content", "info", f"BLIND_SPOT_{b.get('kind')}", f"Blind spot: {str(b.get('kind', '')).replace('_', ' ').lower()}",
                          b.get("detail"), stage="08_graph", run_version=prun["members"].get("08_graph"),
                          fid=f"blind:{b.get('kind')}"))

    # ---- review: annotations
    ann = ann if ann is not None else annotation_status(snap, prun)
    if ann.get("error"):
        out.append(_f("review", "high", "annotations_unreadable", "brd_annotations.json could not be read",
                      f"{ann['error']}. 07_synthesis silently treats an unreadable file as empty, so no annotation "
                      "reaches the BRD.", evidence=[{"label": "brd_annotations.json", "path": ann["path"]}]))
    for e in ann.get("entries", []):
        if e["status"] == "repointed":
            out.append(_f("review", "high", "annotation_repointed", f"Annotation {e['key']} now attaches to a different rule",
                          e["detail"], subject=e["target"], evidence=[{"label": "brd_annotations.json", "path": ann["path"]}],
                          fid=f"ann:{e['key']}"))
        elif e["status"] == "orphaned":
            out.append(_f("review", "medium", "annotation_orphaned", f"Annotation {e['key']} matches nothing",
                          e["detail"], subject=e["target"], evidence=[{"label": "brd_annotations.json", "path": ann["path"]}],
                          fid=f"ann:{e['key']}"))

    out.sort(key=lambda f: (sev_rank(f["severity"]), CATEGORY_ORDER.index(f["category"]), f["title"]))
    return out


def attention(findings: list[dict], limit: int = 12) -> list[dict]:
    """The home-page list: everything run/lineage/source, plus high+ content and review,
    with same-kind content/review findings grouped into one row."""
    rows, groups = [], {}
    for f in findings:
        if f["category"] in ("run", "source") or (f["category"] == "lineage" and f["severity"] != "low"):
            rows.append(f)
            continue
        if f["category"] == "lineage":                 # low: grouped (e.g. unrecorded provenance)
            groups.setdefault(("lineage", f["kind"], f["severity"]), []).append(f)
            continue
        if sev_rank(f["severity"]) > sev_rank("high"):
            continue
        k = (f["category"], f["kind"], f["severity"])
        groups.setdefault(k, []).append(f)
    for (cat, kind, sev), fs in groups.items():
        if len(fs) == 1:
            rows.append(fs[0])
        else:
            head = dict(fs[0])
            head["id"] = f"group:{cat}:{kind}:{sev}"
            head["count"] = len(fs)
            head["title"] = _group_title(kind, fs)
            head["detail"] = "; ".join(x["title"] for x in fs[:6]) + (" …" if len(fs) > 6 else "")
            head["members"] = [x["id"] for x in fs]
            rows.append(head)
    rows.sort(key=lambda f: (sev_rank(f["severity"]), CATEGORY_ORDER.index(f["category"]), -f["count"]))
    return rows[:limit]


def next_steps(snap: Snapshot, src: dict | None) -> dict:
    running = [k for k in R.ORDER if (snap.stages[k]["newest"] or {}).get("state") == "running"]
    if running:
        return {"summary": f"{', '.join(running)} is running — wait for it to finish.", "stages": [], "commands": [],
                "running": running}
    need: dict[str, str] = {}
    if src and (src["unreachable"] or src["changed"]):
        need["01_inventory"] = ("recorded source path no longer exists" if src["unreachable"]
                                else "source files changed since the inventory run")
    for key in R.ORDER:
        st = snap.stages[key]
        newest = st["newest"]
        if st["latest"] is None and key != "08_graph":
            need.setdefault(key, "never run" if not st["runs"] else "no published run")
        elif newest and newest["state"] in ("failed", "crashed") and not newest.get("published"):
            need.setdefault(key, f"last attempt {newest['state']}")
        elif (st.get("freshness") or {}).get("value") in ("unsynced", "upstream_unsynced"):
            need.setdefault(key, "out of date")
    # anything downstream of a stage that will be re-run must follow it
    changed = True
    while changed:
        changed = False
        for key in list(need):
            for d in R.downstream_of(key):
                if d not in need and (snap.stages[d]["latest"] is not None):
                    need[d] = f"downstream of {key}"
                    changed = True
    if not need:
        return {"summary": "Nothing is stale or failed.", "stages": [], "commands": [], "running": []}
    stages = [k for k in R.ORDER if k in need]
    inv = snap.artifact(None, "01_inventory") or {}
    src_arg = "src"
    sd = inv.get("source_dir")
    if sd:
        try:
            src_arg = Path(sd).resolve().relative_to(snap.ws.repo).as_posix()
        except (ValueError, OSError):
            src_arg = "src"
    cmds = []
    for k in stages:
        script = R.BY_KEY[k]["script"]
        cmds.append(f"python .claude/scripts/{script}" + (f" {src_arg}" if k == "01_inventory" else ""))
    first = stages[0]
    return {"summary": f"Re-run {len(stages)} stage(s) starting at {first} ({need[first]}).",
            "stages": [{"stage": k, "reason": need[k]} for k in stages], "commands": cmds, "running": []}


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if s.startswith("[") and s.endswith("]"):
        return [x.strip().strip("'\"") for x in s[1:-1].split(",") if x.strip()]
    return [s]


def _detected_stage(g: dict) -> str | None:
    d = _as_list(g.get("detected_in"))
    m = {"inventory": "01_inventory", "parser": "02_parser", "data": "03_data", "logic": "04_logic",
         "rules": "05_rules", "diagram": "06_diagram"}
    return m.get(d[0]) if d else None


def _group_title(kind: str, fs: list[dict]) -> str:
    n = len(fs)
    names = {
        "SME_REVIEW_REQUIRED": f"{n} rules need business confirmation",
        "MEDIUM_CONFIDENCE_RULE": f"{n} medium-confidence rules worth confirming",
        "UNDOCUMENTED_ENUM": f"{n} permitted-value lists exist only in comments",
        "TRANSACTION_HAZARD": f"{n} transaction behaviours to preserve",
        "syntax_error": f"Syntax errors in {n} files",
        "annotation_orphaned": f"{n} annotations match nothing",
        "annotation_repointed": f"{n} annotations now attach to different rules",
        "provenance_unrecorded": f"{n} stages do not record every input they consumed",
    }
    return names.get(kind, f"{n} × {kind.replace('_', ' ').lower()}")
