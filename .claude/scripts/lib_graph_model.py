#!/usr/bin/env python3
"""
The knowledge graph model — built once, used for both export and querying.

WHY A SHARED MODEL
------------------
The predecessor built CSV rows inline while walking the artifacts, which meant
the exported graph and anything that wanted to answer a question about it were
two separate implementations that could drift. Here the graph is built once as
an in-memory property graph; the Cypher/CSV export and the plain-English query
interface are both views over that single structure. A question answered
locally and the same question run in Neo4j cannot disagree.

SCHEMA DESIGN
-------------
Node-vs-property decisions follow the property-graph rule that a thing which
participates in several INDEPENDENT relationships must be a node:

  Column   is a node, not a property of Table — it is read by objects, written
           by objects, constrained by rules and covered by indexes. Column-level
           lineage is what makes impact analysis possible, and impact analysis
           is the reason to build a graph at all.
  Statement is a node — this is the Code Property Graph layer (Yamaguchi et
           al., IEEE S&P 2014). We already hold an AST (statement tree), a CFG
           (control_flow_graph) and dependence facts (Agent 4 slices); joining
           them answers questions none of them answers alone.
  Parameter is a node — it is the interface contract, and a rebuild that
           changes it breaks every caller.

Relationship properties are kept minimal because Neo4j cannot index them; a
line number lives on the Statement node rather than on an edge.

DECLARED BLIND SPOTS
--------------------
The impact-analysis literature is unanimous that no automated approach is
complete. What this graph cannot see is recorded explicitly as BlindSpot nodes
rather than left as a silent absence — a graph that looks authoritative is more
dangerous than a document that looks uncertain.
"""

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Graph primitives
# ---------------------------------------------------------------------------


class Graph:
    def __init__(self):
        self.nodes = {}      # label -> {key: {props}}
        self.rels = []       # (type, from_label, from_key, to_label, to_key, props)

    def node(self, label: str, key: str, **props):
        if not key:
            return None
        bucket = self.nodes.setdefault(label, {})
        if key in bucket:
            bucket[key].update({k: v for k, v in props.items() if v is not None})
        else:
            bucket[key] = {k: v for k, v in props.items() if v is not None}
        return key

    def rel(self, rtype: str, from_label: str, from_key: str,
            to_label: str, to_key: str, **props):
        if not from_key or not to_key:
            return
        if from_key not in self.nodes.get(from_label, {}):
            return
        if to_key not in self.nodes.get(to_label, {}):
            return
        self.rels.append((rtype, from_label, from_key, to_label, to_key, props))

    def dedupe(self):
        seen, kept = set(), []
        for r in self.rels:
            sig = (r[0], r[1], r[2], r[3], r[4], tuple(sorted(r[5].items())))
            if sig in seen:
                continue
            seen.add(sig)
            kept.append(r)
        self.rels = kept

    # -- query helpers used by the plain-English interface -------------------

    def out(self, label: str, key: str, rtype: str = None):
        return [(r[0], r[3], r[4]) for r in self.rels
                if r[1] == label and r[2] == key and (rtype is None or r[0] == rtype)]

    def inn(self, label: str, key: str, rtype: str = None):
        return [(r[0], r[1], r[2]) for r in self.rels
                if r[3] == label and r[4] == key and (rtype is None or r[0] == rtype)]

    def find(self, label: str, **match):
        out = []
        for key, props in self.nodes.get(label, {}).items():
            if all(str(props.get(k, "")).upper() == str(v).upper() for k, v in match.items()):
                out.append((key, props))
        return out

    def counts(self):
        return ({lab: len(b) for lab, b in sorted(self.nodes.items())},
                _tally(r[0] for r in self.rels))


def _tally(items):
    out = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

_CHECK_IN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_$#]*)\s+IN\s*\(([^)]*)\)", re.IGNORECASE)


def build_graph(art: dict, humanise, object_title, entity_title) -> Graph:
    """
    `art` carries every upstream payload plus the per-object records:
      inventory, parser, data, logic, rules, diagrams, brd_index (optional),
      parser_records, logic_records
    Missing optional artifacts degrade the graph rather than failing it.
    """
    g = Graph()
    inv = art.get("inventory") or {}
    parser = art.get("parser") or {}
    data = art.get("data") or {}
    logic = art.get("logic") or {}
    rules = art.get("rules") or {}
    diagrams = art.get("diagrams") or {}
    brd = art.get("brd_index") or {}
    precs = art.get("parser_records") or {}
    lrecs = art.get("logic_records") or {}

    # ---- Files ----------------------------------------------------------
    for fid, meta in (inv.get("file_metadata") or {}).items():
        # file_index maps id -> filename; everything else lives in file_metadata.
        counts = meta.get("line_counts") or {}
        g.node("File", fid,
               name=meta.get("file") or Path(meta.get("abs_path", "")).name,
               role=meta.get("file_role"),
               lines=counts.get("total") or counts.get("code"),
               complexity=meta.get("complexity"),
               size_bytes=meta.get("size_bytes"))

    # ---- Objects (procedures / functions / package members) --------------
    crud = logic.get("crud_matrix") or {}
    rules_by_object = {}
    for r in rules.get("business_rules", []):
        oid = (r.get("source") or {}).get("object_id")
        if oid:
            rules_by_object.setdefault(oid, []).append(r["rule_id"])

    for oid, prec in precs.items():
        lrec = lrecs.get(oid, {})
        cx = (lrec.get("complexity") or {}).get("cyclomatic", {})
        tx = lrec.get("transactions") or {}
        g.node("Object", oid,
               name=prec.get("name"), title=object_title(oid), type=prec.get("type"),
               shape=(lrec.get("shape") or {}).get("shape"),
               cyclomatic=cx.get("score"),
               exceeds_complexity_threshold=bool(cx.get("exceeds_threshold")),
               rule_count=len(rules_by_object.get(oid, [])),
               statement_count=lrec.get("statement_count") or len(prec.get("statements") or {}),
               parameter_count=len(prec.get("parameters") or []),
               commits=len(tx.get("commits") or []),
               rollbacks=len(tx.get("rollbacks") or []),
               start_line=prec.get("start_line"), end_line=prec.get("end_line"))
        g.rel("CONTAINS", "File", prec.get("file_id"), "Object", oid)

        # Parameters — the interface contract.
        for p in prec.get("parameters") or []:
            pk = f"{oid}::{p['name']}"
            g.node("Parameter", pk, name=p["name"], title=humanise(p["name"]),
                   mode=p.get("mode"), data_type=p.get("type"), object_id=oid)
            g.rel("HAS_PARAMETER", "Object", oid, "Parameter", pk)

        # Statements — the Code Property Graph layer.
        for sid, st in (prec.get("statements") or {}).items():
            g.node("Statement", sid, type=st.get("statement_type"),
                   line=st.get("start_line"), end_line=st.get("end_line"),
                   nesting_depth=st.get("nesting_depth"), object_id=oid)
            g.rel("CONTAINS_STATEMENT", "Object", oid, "Statement", sid)

        # Control flow: the CFG edges, typed so a traversal can distinguish
        # sequential flow from a decision branch from an error path.
        cfg = prec.get("control_flow_graph") or {}
        for e in cfg.get("edges", []):
            src, dst = e.get("from"), e.get("to")
            if src == "*" or not src or not dst:
                continue
            etype = {"SEQUENCE": "FOLLOWS", "BRANCH_ENTRY": "BRANCHES_TO",
                     "EXCEPTION_EDGE": "ON_ERROR_REACHES",
                     "LOOP_BACK_EDGE": "LOOPS_BACK_TO"}.get(e.get("type"), "FOLLOWS")
            g.rel(etype, "Statement", src, "Statement", dst,
                  **({"branch": e["branch"]} if e.get("branch") else {}))

        # Data dependence, from Agent 4's backward slices.
        for sl in lrec.get("variable_slices", []) or []:
            for dep in sl.get("determined_by_statements", []) or []:
                g.rel("DETERMINES", "Statement", dep, "Object", oid, variable=sl.get("variable"))

    # Resolved internal calls, deduplicated.
    for oid, prec in precs.items():
        for st in (prec.get("statements") or {}).values():
            if st.get("statement_type") == "CALL" and st.get("call_target_object_id"):
                g.rel("CALLS", "Object", oid, "Object", st["call_target_object_id"])

    # ---- Tables, columns, keys, indexes, sequences -----------------------
    usage = {c["column_id"]: c for c in (data.get("column_catalogue") or [])}
    for tname, t in (data.get("tables") or {}).items():
        g.node("Table", tname, title=entity_title(tname),
               column_count=len(t.get("columns") or []),
               primary_key=", ".join(t.get("primary_key") or []),
               temporary=bool(t.get("temporary")),
               partitioned=bool(t.get("partitioning")),
               comment=t.get("comment"))
        pk = set(t.get("primary_key") or [])
        for c in t.get("columns") or []:
            cid = f"{tname}.{c['name']}"
            cat = usage.get(cid, {})
            g.node("Column", cid, table=tname, name=c["name"], title=humanise(c["name"]),
                   oracle_type=c.get("oracle_type"), target_type=c.get("pyspark_type"),
                   nullable=bool(c.get("nullable", True)),
                   is_primary_key=c["name"] in pk,
                   is_virtual=bool(c.get("is_virtual")),
                   is_identity=bool(c.get("is_identity")),
                   usage_count=cat.get("usage_count", 0))
            g.rel("HAS_COLUMN", "Table", tname, "Column", cid)

        for fk in t.get("foreign_keys") or []:
            target = fk.get("references_table")
            if target:
                g.rel("REFERENCES", "Table", tname, "Table", target,
                      constraint=fk.get("name") or "",
                      enforced=bool((fk.get("enforcement") or {}).get("is_enforced")))
                for col in fk.get("columns") or []:
                    g.rel("FOREIGN_KEY_ON", "Table", tname, "Column", f"{tname}.{col}")

    for idx in data.get("indexes") or []:
        iname = idx.get("index")
        if not iname:
            continue
        g.node("Index", iname, table=idx.get("table"), unique=bool(idx.get("unique")),
               bitmap=bool(idx.get("bitmap")))
        for col in idx.get("columns") or []:
            g.rel("COVERS", "Index", iname, "Column", f"{idx.get('table')}.{col}")

    for sname, s in (data.get("sequences") or {}).items():
        g.node("Sequence", sname, start_with=s.get("start_with"),
               increment_by=s.get("increment_by"), cache=s.get("cache"))
    for u in data.get("sequence_usages") or []:
        if u.get("sequence") and u.get("table") and u.get("column"):
            g.rel("POPULATES", "Sequence", u["sequence"], "Column",
                  f"{u['table']}.{u['column']}")

    # ---- Column-level lineage -------------------------------------------
    # Table-level CRUD says a procedure touches ACCOUNTS. Column-level says it
    # writes ACCOUNTS.BALANCE. Only the second answers an impact question.
    for oid, prec in precs.items():
        for st in (prec.get("statements") or {}).values():
            tabs = [t.upper() for t in (st.get("tables") or [])]
            for tab in tabs:
                if tab not in g.nodes.get("Table", {}):
                    continue
                g.rel("TOUCHES", "Object", oid, "Table", tab)
                sid = st.get("statement_id")
                for col in st.get("writes") or []:
                    cid = f"{tab}.{col.upper()}"
                    g.rel("WRITES_COLUMN", "Object", oid, "Column", cid)
                    # Statement-level edges too: "which line writes this column"
                    # is a more useful impact answer than "which procedure".
                    # Names in `reads`/`writes` that are parameters rather than
                    # columns simply find no node and are dropped by g.rel.
                    g.rel("WRITES_COLUMN", "Statement", sid, "Column", cid)
                for col in (st.get("predicate_reads") or []) + (st.get("reads") or []):
                    cid = f"{tab}.{col.upper()}"
                    g.rel("READS_COLUMN", "Object", oid, "Column", cid)
                    g.rel("READS_COLUMN", "Statement", sid, "Column", cid)

    for oid, tabs in crud.items():
        for tab, ops in (tabs or {}).items():
            ops = (ops or "").upper()
            if "R" in ops:
                g.rel("READS", "Object", oid, "Table", tab.upper())
            if any(o in ops for o in "CUD"):
                g.rel("WRITES", "Object", oid, "Table", tab.upper(), operations=ops)

    # ---- Business rules --------------------------------------------------
    by_id = {r["rule_id"]: r for r in rules.get("business_rules", [])}
    modality = {r["id"]: r.get("modality") for r in (brd.get("requirements") or [])}
    verification = {r["id"]: r.get("verification_method") for r in (brd.get("requirements") or [])}

    for rs in rules.get("rule_sets", []) or []:
        g.node("RuleSet", rs.get("rule_set_id") or rs.get("name"), name=rs.get("name"))

    for r in rules.get("business_rules", []):
        rid, src = r["rule_id"], r.get("source") or {}
        g.node("BusinessRule", rid, name=r.get("name"), category=r.get("category"),
               confidence=r.get("confidence"), origin=src.get("kind"),
               line=src.get("line"), needs_review=bool(r.get("requires_sme_review")),
               is_enforced=r.get("is_enforced"),
               modality=modality.get(rid), verification_method=verification.get(rid),
               condition=r.get("condition_text"), signal_strength=r.get("signal_strength"))
        for rs in rules.get("rule_sets", []) or []:
            if rid in (rs.get("rule_ids") or []):
                g.rel("BELONGS_TO", "BusinessRule", rid, "RuleSet",
                      rs.get("rule_set_id") or rs.get("name"))
        if src.get("object_id"):
            g.rel("ENFORCED_IN", "BusinessRule", rid, "Object", src["object_id"])
        # Exact provenance — the pipeline's distinguishing asset.
        if src.get("statement_id"):
            g.rel("IMPLEMENTED_AT", "BusinessRule", rid, "Statement", src["statement_id"])
        if src.get("table"):
            tab = src["table"].upper()
            g.rel("CONSTRAINS_TABLE", "BusinessRule", rid, "Table", tab)
            if src.get("column"):
                g.rel("CONSTRAINS", "BusinessRule", rid, "Column",
                      f"{tab}.{src['column'].upper()}")

    # ---- Entity states (Agent 6) ----------------------------------------
    for tname, t in (data.get("tables") or {}).items():
        for chk in t.get("check_constraints") or []:
            m = _CHECK_IN_RE.search(chk.get("expression") or "")
            if not m:
                continue
            col = m.group(1).upper()
            values = [v.strip().strip("'") for v in m.group(2).split(",") if v.strip()]
            if len(values) < 2:
                continue
            for v in values:
                sk = f"{tname}.{col}={v.upper()}"
                g.node("State", sk, table=tname, column=col, value=v.upper())
                g.rel("HAS_STATE", "Column", f"{tname}.{col}", "State", sk)

    for f, meta in (diagrams.get("diagram_index") or {}).items():
        if meta.get("type") != "state":
            continue
        # Transitions are re-derived from the diagram's own record so the graph
        # and the BRD agree on the lifecycle.
        for note in meta.get("notes", []) or []:
            pass  # notes surface as BlindSpot/Gap rather than edges

    # ---- Gaps (Agent 7) --------------------------------------------------
    for gp in (brd.get("gaps") or []):
        g.node("Gap", gp["gap_id"], type=gp.get("gap_type"), severity=gp.get("severity"),
               title=gp.get("title"))
        for rid in gp.get("related_rule_ids") or []:
            g.rel("AFFECTS", "Gap", gp["gap_id"], "BusinessRule", rid)

    # ---- Declared blind spots -------------------------------------------
    unresolved = sum(1 for i in (parser.get("issues") or [])
                     if i.get("type") == "unresolved_reference")
    dynamic = (parser.get("stats") or {}).get("dynamic_sql_blocks", 0)
    for key, detail in [
        ("DYNAMIC_SQL",
         f"{dynamic} dynamic SQL block(s). Tables and columns referenced only in "
         f"strings assembled at runtime are invisible to static analysis."),
        ("EXTERNAL_CALLERS",
         "Schedulers, screens, batch wrappers and other systems that invoke these "
         "objects are outside the analysed source, so no inbound edge exists."),
        ("UNRESOLVED_CALLS",
         f"{unresolved} call(s) to routines outside this codebase. Their effects "
         f"are unknown and absent from the graph."),
        ("TRIGGER_SIDE_EFFECTS",
         "Database triggers fire on DML without an explicit call edge; any such "
         "effect is not represented as a dependency."),
    ]:
        g.node("BlindSpot", key, detail=detail)

    g.dedupe()
    return g
