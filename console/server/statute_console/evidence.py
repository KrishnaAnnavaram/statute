"""Evidence pages: any requirement, rule, gap, object, statement, table, column or
file, with its provenance path back to a source line and what else refers to it.

Read-through only: everything comes from the artifacts of one pipeline run.
"""
from __future__ import annotations

from pathlib import Path

from .model import Snapshot, redact

KINDS = ("rule", "requirement", "gap", "object", "statement", "table", "column", "file")


class Ctx:
    """Lazily loaded artifacts of one pipeline run."""

    def __init__(self, snap: Snapshot, prun: dict | None):
        self.snap, self.prun, self.ws = snap, prun, snap.ws
        self._c = {}

    def art(self, key, fname=None):
        k = (key, fname)
        if k not in self._c:
            self._c[k] = self.snap.artifact(self.prun, key, fname) or {}
        return self._c[k]

    def rv(self, key):
        return (self.prun or {}).get("members", {}).get(key) if self.prun else \
            self.snap.stages[key]["latest_run_version"]

    @property
    def rules(self):
        if "rules" not in self._c:
            self._c["rules"] = {r["rule_id"]: r for r in self.art("05_rules").get("business_rules", [])}
        return self._c["rules"]

    @property
    def requirements(self):
        if "reqs" not in self._c:
            self._c["reqs"] = {r["id"]: r for r in self.art("07_synthesis", "brd_index.json").get("requirements", [])}
        return self._c["reqs"]

    @property
    def gaps(self):
        if "gaps" not in self._c:
            self._c["gaps"] = {g["gap_id"]: g for g in
                               self.art("07_synthesis", "gaps_register.json").get("gaps", [])}
        return self._c["gaps"]

    @property
    def inventory(self):
        return self.art("01_inventory")

    def object_record(self, oid):
        k = ("obj", oid)
        if k not in self._c:
            rel = (self.art("02_parser").get("object_index") or {}).get(oid)
            d = self.snap.member_dir(self.prun, "02_parser")
            data = None
            if rel and d:
                p = (d / rel).resolve()
                try:
                    p.relative_to(d.resolve())
                    data, _ = self.ws.load_json(p)
                except ValueError:
                    data = None
            self._c[k] = data if isinstance(data, dict) else None
        return self._c[k]

    def logic_record(self, oid):
        k = ("logic", oid)
        if k not in self._c:
            rel = (self.art("04_logic").get("object_index") or {}).get(oid)
            d = self.snap.member_dir(self.prun, "04_logic")
            data = None
            if rel and d:
                data, _ = self.ws.load_json(d / rel)
            self._c[k] = data if isinstance(data, dict) else None
        return self._c[k]

    def file_meta(self, file_id):
        return (self.inventory.get("file_metadata") or {}).get(file_id)

    def object_ids(self):
        return list((self.art("02_parser").get("object_index") or {}).keys())

    def object_of_statement(self, sid: str):
        prefix = sid.rsplit("__STMT_", 1)[0]
        for oid in sorted(self.object_ids(), key=len, reverse=True):
            if prefix.endswith("__" + oid):
                return oid
        return None

    def diagrams(self):
        return self.art("06_diagram").get("diagram_index") or {}


def _ref(kind, id_, label=None, stage=None, rv=None, detail=None):
    return {"kind": kind, "id": id_, "label": label or id_, "stage": stage, "run_version": rv, "detail": detail}


def _short_object(oid: str) -> str:
    return oid.split(".", 1)[-1] if "." in oid else oid


def _location_of_rule(ctx: Ctx, r: dict) -> dict | None:
    s = r.get("source") or {}
    if s.get("statement_id"):
        oid = s.get("object_id") or ctx.object_of_statement(s["statement_id"])
        obj = ctx.object_record(oid) if oid else None
        fid = (obj or {}).get("file_id")
        meta = ctx.file_meta(fid) if fid else None
        return {"file_id": fid, "file": (meta or {}).get("file"), "line": s.get("line"),
                "object_id": oid, "statement_id": s["statement_id"]}
    if s.get("table"):
        t = (ctx.art("03_data").get("tables") or {}).get(s["table"]) or {}
        line = None
        for c in t.get("check_constraints") or []:
            if c.get("name") == s.get("constraint_name"):
                line = c.get("line") or t.get("start_line")
        return {"file": t.get("source_file"), "file_id": _file_id_for(ctx, t.get("source_file")),
                "line": line or t.get("start_line"), "table": s["table"],
                "constraint": s.get("constraint_name")}
    return None


def _file_id_for(ctx: Ctx, fname: str | None) -> str | None:
    if not fname:
        return None
    for fid, f in (ctx.inventory.get("file_index") or {}).items():
        if f == fname:
            return fid
    return None


# ---------------------------------------------------------------------------

def search(snap: Snapshot, prun: dict | None, q: str, limit: int = 40) -> list[dict]:
    ctx = Ctx(snap, prun)
    q = (q or "").strip().lower()
    if not q:
        return []
    cands = []
    for rid, r in ctx.rules.items():
        cands.append(_ref("rule", rid, f"{rid} · {r.get('name')}", detail=r.get("category")))
    for gid, g in ctx.gaps.items():
        cands.append(_ref("gap", gid, f"{gid} · {g.get('title')}", detail=g.get("severity")))
    for oid in ctx.object_ids():
        cands.append(_ref("object", oid, oid, detail="object"))
    for t in (ctx.art("03_data").get("tables") or {}):
        cands.append(_ref("table", t, t, detail="table"))
    for c in ctx.art("03_data").get("column_catalogue") or []:
        cands.append(_ref("column", c.get("column_id"), c.get("column_id"), detail=c.get("oracle_type")))
    for fid, f in (ctx.inventory.get("file_index") or {}).items():
        cands.append(_ref("file", fid, f, detail="source file"))
    hits = []
    for c in cands:
        hay = f"{c['id']} {c['label']}".lower()
        if q in hay:
            score = 0 if c["id"].lower() == q else (1 if c["id"].lower().startswith(q) else 2)
            hits.append((score, len(c["label"]), c))
    if "__stmt_" in q:
        oid = ctx.object_of_statement(q.upper()) if q else None
        if oid:
            hits.append((0, 0, _ref("statement", q.upper(), q.upper(), detail=oid)))
    hits.sort(key=lambda h: (h[0], h[1]))
    return [h[2] for h in hits[:limit]]


def entity(snap: Snapshot, prun: dict | None, kind: str, id_: str) -> dict | None:
    ctx = Ctx(snap, prun)
    fn = {"rule": _rule, "requirement": _rule, "gap": _gap, "object": _object, "statement": _statement,
          "table": _table, "column": _column, "file": _file}.get(kind)
    if not fn:
        return None
    out = fn(ctx, id_)
    if out is not None:
        out["pipeline_run"] = (prun or {}).get("id")
    return out


def _rule(ctx: Ctx, rid: str):
    r = ctx.rules.get(rid)
    if not r:
        return None
    req = ctx.requirements.get(rid)
    loc = _location_of_rule(ctx, r)
    path = []
    if req:
        trace = next((t for t in ctx.art("07_synthesis", "brd_index.json").get("traceability", [])
                      if t.get("rule_id") == rid), None)
        path.append(_ref("requirement", rid, rid, "07_synthesis", ctx.rv("07_synthesis"),
                         detail=f"brd.md · {trace.get('figure')}" if trace and trace.get("figure") else "brd.md"))
    path.append(_ref("rule", rid, f"{rid} ({r.get('source', {}).get('kind')})", "05_rules", ctx.rv("05_rules")))
    if loc and loc.get("statement_id"):
        path.append(_ref("statement", loc["statement_id"], loc["statement_id"], "02_parser", ctx.rv("02_parser")))
    if loc and loc.get("object_id"):
        path.append(_ref("object", loc["object_id"], loc["object_id"], "02_parser", ctx.rv("02_parser")))
    if loc and loc.get("table"):
        path.append(_ref("table", loc["table"], f"{loc['table']} · constraint {loc.get('constraint')}",
                         "03_data", ctx.rv("03_data")))
    if loc and loc.get("file"):
        path.append(_ref("file", loc.get("file_id") or loc["file"],
                         f"{loc['file']}" + (f" : line {loc['line']}" if loc.get("line") else " : line not recorded"),
                         "01_inventory", ctx.rv("01_inventory")))
    diagrams = [{"diagram": d, "title": m.get("title")} for d, m in ctx.diagrams().items()
                if rid in (m.get("rule_ids") or [])]
    gaps = [{"id": g["gap_id"], "title": g.get("title"), "severity": g.get("severity")}
            for g in ctx.gaps.values() if rid in str(g.get("related_rule_ids") or "")]
    rule_set = next((rs for rs in ctx.art("05_rules").get("rule_sets", []) if rid in rs.get("rule_ids", [])), None)
    return {
        "kind": "rule", "id": rid, "title": r.get("name"),
        "facts": {"category": r.get("category"), "confidence": r.get("confidence"),
                  "needs SME review": r.get("requires_sme_review"),
                  "enforced by database": r.get("is_enforced"),
                  "pattern": r.get("structural_pattern"), "signal strength": r.get("signal_strength"),
                  "rule set": (rule_set or {}).get("name")},
        "condition": r.get("condition_text"),
        "description": redact(r.get("description")),
        "requirement": None if not req else {
            "text": req.get("text"), "formal": req.get("formal"), "modality": req.get("modality"),
            "type": req.get("type"), "verification": req.get("verification_method"),
            "needs_review": req.get("needs_review"), "owner": req.get("owner"), "priority": req.get("priority")},
        "location": loc, "provenance": path,
        "appears_in": diagrams, "gaps": gaps,
        "note": ("Rule ids (BR-nnn) are reassigned whenever the rule set changes; annotate with care."),
    }


def _gap(ctx: Ctx, gid: str):
    g = ctx.gaps.get(gid)
    if not g:
        return None
    rel_ids = [x.strip().strip("'\"") for x in str(g.get("related_rule_ids") or "").strip("[]").split(",") if x.strip()]
    related = [{"id": rid, "name": (ctx.rules.get(rid) or {}).get("name")} for rid in rel_ids]
    loc = None
    for rid in rel_ids:
        if rid in ctx.rules:
            loc = _location_of_rule(ctx, ctx.rules[rid])
            break
    path = [_ref("gap", gid, gid, "07_synthesis", ctx.rv("07_synthesis"))]
    for rid in rel_ids:
        path.append(_ref("rule", rid, rid, "05_rules", ctx.rv("05_rules")))
    if loc and loc.get("file"):
        path.append(_ref("file", loc.get("file_id") or loc["file"], f"{loc['file']} : line {loc.get('line')}",
                         "01_inventory", ctx.rv("01_inventory")))
    return {"kind": "gap", "id": gid, "title": g.get("title"),
            "facts": {"severity": g.get("severity"), "type": g.get("gap_type"), "detected in": g.get("detected_in")},
            "description": redact(g.get("description")), "related_rules": related, "location": loc,
            "provenance": path}


def _object(ctx: Ctx, oid: str):
    obj = ctx.object_record(oid)
    if not obj:
        return None
    meta = ctx.file_meta(obj.get("file_id")) or {}
    logic = ctx.logic_record(oid) or {}
    cx = logic.get("complexity") or {}
    rules = [{"id": rid, "name": r.get("name"), "line": (r.get("source") or {}).get("line"),
              "category": r.get("category"), "confidence": r.get("confidence")}
             for rid, r in sorted(ctx.rules.items()) if (r.get("source") or {}).get("object_id") == oid]
    diagrams = [{"diagram": d, "title": m.get("title"), "nodes": m.get("nodes")}
                for d, m in ctx.diagrams().items() if m.get("object_id") == oid]
    crud = (ctx.art("04_logic").get("crud_matrix") or {}).get(oid) or {}
    cap = next((c for c in ctx.art("07_synthesis", "brd_index.json").get("capabilities", []) if c.get("id") == oid), None)
    hazards = [{"hazard": h.get("hazard"), "severity": h.get("severity"),
                "lines": [o.get("line") for o in h.get("occurrences", [])], "explanation": h.get("explanation")}
               for h in (logic.get("transactions") or {}).get("hazards", [])]
    return {
        "kind": "object", "id": oid, "title": (cap or {}).get("title") or _short_object(oid),
        "facts": {"type": obj.get("type"), "parse status": obj.get("parse_status"),
                  "lines": f"{obj.get('start_line')}–{obj.get('end_line')}",
                  "statements": len(obj.get("statements") or {}), "parameters": len(obj.get("parameters") or []),
                  "shape": (logic.get("shape") or {}).get("shape"),
                  "cyclomatic": (cx.get("cyclomatic") or {}).get("score"),
                  "cyclomatic threshold": (cx.get("cyclomatic") or {}).get("threshold"),
                  "cognitive": (cx.get("cognitive") or {}).get("score")},
        "description": redact(logic.get("narrative")),
        "location": {"file_id": obj.get("file_id"), "file": meta.get("file"), "line": obj.get("start_line")},
        "provenance": [_ref("object", oid, oid, "02_parser", ctx.rv("02_parser")),
                       _ref("file", obj.get("file_id"), f"{meta.get('file')} : lines {obj.get('start_line')}–{obj.get('end_line')}",
                            "01_inventory", ctx.rv("01_inventory"))],
        "rules": rules, "appears_in": diagrams, "crud": crud, "hazards": hazards,
        "parse_issues": [redact(i.get("message", i.get("type")))[:300] for i in obj.get("parse_issues") or []],
    }


def _statement(ctx: Ctx, sid: str):
    oid = ctx.object_of_statement(sid)
    obj = ctx.object_record(oid) if oid else None
    st = ((obj or {}).get("statements") or {}).get(sid)
    if not st:
        return None
    meta = ctx.file_meta(obj.get("file_id")) or {}
    rules = [{"id": rid, "name": r.get("name")} for rid, r in sorted(ctx.rules.items())
             if (r.get("source") or {}).get("statement_id") == sid
             or any(s.get("statement_id") == sid for s in r.get("sources") or [])]
    nodes = [{"diagram": d, "node": n} for d, m in ctx.diagrams().items()
             for n, origin in (m.get("node_origins") or {}).items() if origin == sid]
    return {
        "kind": "statement", "id": sid, "title": f"{st.get('statement_type')} at line {st.get('start_line')}",
        "facts": {"type": st.get("statement_type"), "lines": f"{st.get('start_line')}–{st.get('end_line')}",
                  "nesting depth": st.get("nesting_depth"), "scope": " › ".join(st.get("scope_path") or []),
                  "tables": ", ".join(st.get("tables") or []) or None,
                  "requires manual review": st.get("requires_manual_review")},
        "location": {"file_id": obj.get("file_id"), "file": meta.get("file"), "line": st.get("start_line"),
                     "object_id": oid},
        "provenance": [_ref("statement", sid, sid, "02_parser", ctx.rv("02_parser")),
                       _ref("object", oid, oid, "02_parser", ctx.rv("02_parser")),
                       _ref("file", obj.get("file_id"), f"{meta.get('file')} : line {st.get('start_line')}",
                            "01_inventory", ctx.rv("01_inventory"))],
        "rules": rules, "appears_in": nodes, "parent": st.get("parent_id"),
    }


def _table(ctx: Ctx, tname: str):
    t = (ctx.art("03_data").get("tables") or {}).get(tname)
    if not t:
        return None
    cols = [{"name": c.get("name"), "type": c.get("oracle_type"), "nullable": c.get("nullable"),
             "line": c.get("line")} for c in t.get("columns") or []]
    checks = [{"name": c.get("name"), "expression": c.get("expression"),
               "enforced": (c.get("enforcement") or {}).get("is_enforced"),
               "state": f"{(c.get('enforcement') or {}).get('status')} {(c.get('enforcement') or {}).get('validated')}"}
              for c in t.get("check_constraints") or []]
    fks = [{"name": f.get("name"), "columns": f.get("columns"), "references": f.get("references_table"),
            "on_delete": f.get("on_delete"), "kind": f.get("relationship_type")} for f in t.get("foreign_keys") or []]
    crud = {oid: m.get(tname) for oid, m in (ctx.art("04_logic").get("crud_matrix") or {}).items() if m.get(tname)}
    rules = [{"id": rid, "name": r.get("name")} for rid, r in sorted(ctx.rules.items())
             if (r.get("source") or {}).get("table") == tname]
    fid = _file_id_for(ctx, t.get("source_file"))
    return {"kind": "table", "id": tname, "title": tname,
            "facts": {"columns": len(cols), "primary key": ", ".join(t.get("primary_key") or []) if isinstance(t.get("primary_key"), list) else t.get("primary_key"),
                      "temporary": t.get("temporary"), "comment": t.get("comment")},
            "location": {"file_id": fid, "file": t.get("source_file"), "line": t.get("start_line")},
            "provenance": [_ref("table", tname, tname, "03_data", ctx.rv("03_data")),
                           _ref("file", fid or t.get("source_file"), f"{t.get('source_file')} : line {t.get('start_line')}",
                                "01_inventory", ctx.rv("01_inventory"))],
            "columns": cols, "checks": checks, "foreign_keys": fks, "crud": crud, "rules": rules}


def _column(ctx: Ctx, cid: str):
    c = next((x for x in ctx.art("03_data").get("column_catalogue") or [] if x.get("column_id") == cid), None)
    if not c:
        return None
    return {"kind": "column", "id": cid, "title": cid,
            "facts": {"type": c.get("oracle_type"), "nullable": c.get("nullable"),
                      "primary key": c.get("is_primary_key"), "permitted values": ", ".join(c.get("enum_values") or []) or None,
                      "values documented in": c.get("enum_source"), "description": c.get("description")},
            "provenance": [_ref("column", cid, cid, "03_data", ctx.rv("03_data")),
                           _ref("table", c.get("table"), c.get("table"), "03_data", ctx.rv("03_data"))],
            "used_by": [{"id": o} for o in c.get("used_by_objects") or []]}


def _file(ctx: Ctx, fid: str):
    meta = ctx.file_meta(fid)
    if not meta:
        fid2 = _file_id_for(ctx, fid)
        meta = ctx.file_meta(fid2) if fid2 else None
        fid = fid2 or fid
    if not meta:
        return None
    p, how = ctx.ws.resolve_source(meta)
    objects = [oid for oid in ctx.object_ids() if (ctx.object_record(oid) or {}).get("file_id") == fid]
    lc = meta.get("line_counts") or {}
    return {"kind": "file", "id": fid, "title": meta.get("file"),
            "facts": {"role": meta.get("file_role"), "complexity": meta.get("complexity"),
                      "lines": lc.get("total_lines"), "code lines": lc.get("code_lines"),
                      "status": meta.get("status"), "encoding": meta.get("encoding_used"),
                      "sha256 (recorded)": (meta.get("sha256") or "")[:16] + "…",
                      "located via": how},
            "warnings": meta.get("warnings") or [],
            "location": {"file_id": fid, "file": meta.get("file"), "line": 1},
            "provenance": [_ref("file", fid, meta.get("file"), "01_inventory", ctx.rv("01_inventory"))],
            "objects": [{"id": o} for o in objects]}


def source_window(snap: Snapshot, prun: dict | None, file_id: str, line: int, context: int = 3) -> dict | None:
    ctx = Ctx(snap, prun)
    meta = ctx.file_meta(file_id)
    if not meta:
        return None
    p, how = ctx.ws.resolve_source(meta)
    if not p:
        return {"file": meta.get("file"), "available": False, "reason": "source file not reachable", "lines": []}
    context = max(0, min(int(context), 25))
    try:
        text = p.read_text(encoding=meta.get("encoding_used") or "utf-8", errors="replace").splitlines()
    except OSError:
        return {"file": meta.get("file"), "available": False, "reason": "source file unreadable", "lines": []}
    line = max(1, int(line))
    lo, hi = max(1, line - context), min(len(text), line + context)
    return {"file": meta.get("file"), "available": True, "located_via": how, "focus": line,
            "lines": [{"n": i, "text": text[i - 1][:400]} for i in range(lo, hi + 1)]}


__all__ = ["search", "entity", "source_window", "KINDS"]
_ = Path
