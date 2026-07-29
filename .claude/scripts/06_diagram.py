#!/usr/bin/env python3
"""
Stage 6: VISUAL MODEL (deterministic, no LLM)
=============================================

Produces the BRD's visual layer. Zero LLM calls, 100% deterministic.

WHY THIS AGENT WAS REDESIGNED
-----------------------------
The previous version formatted Mermaid strings inline while walking the
control-flow graph. That single choice caused every defect it had: there was
nothing to count, so the documented `--max-nodes` budget was declared and
never implemented; there was nothing but strings to assert on, so the test
suite could only check syntax; and the renderer could never be changed.

Measured state of the old output on this codebase:
  - component diagram: 5 nodes, **0 edges** (no internal calls exist here) —
    an expensive way to print a list
  - flow diagrams: every node labelled `ASSIGNMENT L29` / `Decision L38`,
    conveying position but no meaning
  - four sibling branches of one IF all labelled `elsif`
  - `NESTED_BLOCK#5` (a parser-internal name) leaked into user-facing output

ARCHITECTURE
------------
    LOAD -> RESOLVE -> MODEL -> REDUCE -> ORDER -> RENDER -> VALIDATE -> WRITE

Stages up to ORDER never emit a character of Mermaid; RENDER is the only
Mermaid-aware code. Everything is asserted against the intermediate
`DiagramSpec`, which is what makes the quality gates in tests/test_diagram.py
meaningful rather than cosmetic. Swapping in a Graphviz backend later means
writing one new renderer, not rewriting the agent.

WHAT IT DRAWS
-------------
  D1  ERD                  - owned by Agent 3; indexed here so the BRD has a
                             single visual index (two generators for one
                             diagram would be an architecture smell)
  D2  System data-flow map - objects x tables with C/R/U/D edges. Replaces the
                             0-edge component diagram
  D3  Process flow         - per object, CFG joined to Agent 5's rules on
                             statement_id so decisions read as business text
  D4  Entity state model   - states from a CHECK IN-list, transitions from
                             UPDATEs that write that column. The only place
                             this agent derives new knowledge, so it carries
                             the strictest evidence bar: a transition whose
                             source or target cannot be resolved is marked
                             inferred or omitted, never invented
  D5  CRUD matrix          - markdown table; tabular data belongs in a table

DESIGN REFERENCES
-----------------
  Moody (2009) The "Physics" of Notations, IEEE TSE 35(6)
      semantic transparency, dual coding, complexity management, graphic economy
  Shneiderman (1996) The Eyes Have It
      overview first, zoom and filter, details on demand
  Shneiderman, Mayer, McKay & Heller (1977) CACM 20(6)
      detailed statement-level flowcharts showed no measurable benefit -> draw
      decisions and outcomes, collapse straight-line runs
  Purchase (1997, 2002) graph drawing aesthetics
      edge crossings dominate comprehension -> bound graph size
  VEIL (arXiv 2511.05066, 2025) dominator-ordered CFG layout
      emission order changes the renderer's result -> emit in source order
  Green & Blackwell, Cognitive Dimensions of Notations
      hidden dependencies -> print BR-ids so diagram and rule catalogue connect
  BABOK v3 - data flow diagrams, state modelling, CRUD matrix
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DESIGN_REFERENCES = [
    {"work": "Moody, D.L. (2009) The 'Physics' of Notations, IEEE TSE 35(6):756-779",
     "applied": "Semantic transparency (business text on nodes), dual coding "
                "(text + shape + colour), complexity management (node budget), "
                "graphic economy (six node kinds)."},
    {"work": "Shneiderman, B. (1996) The Eyes Have It, IEEE Visual Languages",
     "applied": "Output is an information hierarchy: data-flow overview -> "
                "per-object process flow -> rule detail reached by BR-id."},
    {"work": "Shneiderman, Mayer, McKay & Heller (1977) CACM 20(6):373-381",
     "applied": "Detailed statement-level flowcharts showed no measurable "
                "benefit; straight-line runs are collapsed and only decisions, "
                "loops, error paths and outcomes are drawn."},
    {"work": "Purchase, H. (1997/2002) graph drawing aesthetics",
     "applied": "Edge crossings dominate comprehension and scale with graph "
                "size; a hard node budget is enforced."},
    {"work": "VEIL: Reading Control Flow Graphs Like Code (arXiv 2511.05066)",
     "applied": "Nodes are emitted in source order so the renderer's layout "
                "follows reading order."},
    {"work": "BABOK v3 - Data Flow Diagrams, State Modelling, CRUD matrix",
     "applied": "Diagram selection: what belongs in a requirements document."},
]

DEFAULT_NODE_BUDGET = 40

# Identifiers that must never reach a user-facing label.
_INTERNAL_ID_PATTERNS = [
    re.compile(r"STMT_\d+"),
    re.compile(r"NESTED_BLOCK#\d+"),
    re.compile(r"__[0-9A-F]{8}\b"),
    re.compile(r"\bIF#\d+\."),
]


def generate_run_version() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H.%M.%S.") + f"{now.microsecond // 1000:03d}Z"


def load_run(root: str, run: str, artifact_filename: str) -> tuple[dict, str]:
    root_path = Path(root)
    if run == "latest":
        pointer = json.loads((root_path / "latest.json").read_text(encoding="utf-8"))
        run_version = pointer["run_version"]
    else:
        run_version = run
    payload = json.loads((root_path / run_version / artifact_filename).read_text(encoding="utf-8"))
    return payload, run_version


# ---------------------------------------------------------------------------
# MODEL - renderer-agnostic intermediate representation
# ---------------------------------------------------------------------------

# Kept deliberately small. Moody's graphic economy principle: every additional
# symbol type costs the reader discrimination effort, so six kinds carry all
# the meaning rather than one per statement type.
KIND_DECISION = "DECISION"
KIND_PROCESS = "PROCESS"
KIND_LOOP = "LOOP"
KIND_ERROR = "ERROR"
KIND_TERMINAL = "TERMINAL"
KIND_DATA = "DATA"
KIND_OBJECT = "OBJECT"
KIND_STATE = "STATE"

# Structure a reader needs to see the shape of the logic. Never collapsed,
# whatever the node budget.
_NEVER_COLLAPSE = {KIND_DECISION, KIND_LOOP, KIND_ERROR, KIND_TERMINAL}


@dataclass
class Node:
    id: str
    kind: str
    label: str
    sublabel: str = ""
    rule_ids: list = field(default_factory=list)
    source_line: int | None = None
    emphasis: str = ""            # warning | inferred | external
    origin_id: str = ""           # real statement/object id - artifact only
    label_tier: int = 3           # 1 rule-derived, 2 structured field, 3 fallback


@dataclass
class Edge:
    src: str
    dst: str
    kind: str = "FLOW"            # FLOW|BRANCH|LOOP_BACK|EXCEPTION|CRUD|TRANSITION
    label: str = ""
    rule_id: str = ""
    emphasis: str = ""


@dataclass
class DiagramSpec:
    diagram_id: str
    type: str
    title: str
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    budget_report: dict = field(default_factory=dict)
    object_id: str = ""
    entity: str = ""
    note_anchors: dict = field(default_factory=dict)   # node_id -> note text

    def node_ids(self) -> set:
        return {n.id for n in self.nodes}


# ---------------------------------------------------------------------------
# RESOLVE - join indexes built once
# ---------------------------------------------------------------------------

_SOURCE_CACHE: dict = {}


def source_lines(abs_path: str) -> list:
    if abs_path not in _SOURCE_CACHE:
        try:
            _SOURCE_CACHE[abs_path] = Path(abs_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            _SOURCE_CACHE[abs_path] = []
    return _SOURCE_CACHE[abs_path]


def raw_snippet(abs_path: str, start: int, end: int) -> str:
    lines = source_lines(abs_path)
    if not lines or not start or start < 1:
        return ""
    cleaned = [re.sub(r"--.*", "", l) for l in lines[start - 1:end]]
    return re.sub(r"\s+", " ", " ".join(cleaned)).strip()


class Indexes:
    """Every join the builders need, resolved once."""

    def __init__(self, parser_artifact, data_artifact, logic_artifact,
                 rules_artifact, inventory):
        self.rules_by_object_line = {}
        self.rules_by_object = {}
        for r in (rules_artifact or {}).get("business_rules", []):
            src = r.get("source", {})
            oid, line = src.get("object_id"), src.get("line")
            if not oid:
                continue
            self.rules_by_object.setdefault(oid, []).append(r)
            if line is not None:
                self.rules_by_object_line.setdefault((oid, line), []).append(r)

        self.crud = (logic_artifact or {}).get("crud_matrix", {}) or {}

        self.metrics = {}
        self.logic_index = (logic_artifact or {}).get("object_index", {}) or {}

        self.tables = (data_artifact or {}).get("tables", {}) or {}
        self.known_tables = {t.upper() for t in self.tables}

        self.file_abs = {fid: meta["abs_path"]
                         for fid, meta in (inventory or {}).get("file_metadata", {}).items()}

        self.object_index = parser_artifact["object_index"]

    def rule_at(self, object_id: str, line: int):
        """Highest-signal rule anchored at this source line, if any."""
        hits = self.rules_by_object_line.get((object_id, line), [])
        if not hits:
            return None
        return max(hits, key=lambda r: r.get("signal_strength", 0))

    def rule_in_span(self, object_id: str, start: int, end: int):
        """
        A rule describing a decision is not always anchored on the decision's
        own line. Agent 5 merges a guarded RAISE into the IF that guards it but
        records the RAISE's line, so `IF p_amount <= 0 THEN RAISE ...` spanning
        lines 35-37 carries its rule at 36. Searching the statement's span
        recovers it; exact-line matches still win.
        """
        exact = self.rule_at(object_id, start)
        if exact is not None:
            return exact
        candidates = [(line, r) for (oid, line), rules in self.rules_by_object_line.items()
                      if oid == object_id and start <= line <= (end or start)
                      for r in rules]
        if not candidates:
            return None
        return min(candidates, key=lambda pair: pair[0])[1]

    def rule_count(self, object_id: str) -> int:
        return len(self.rules_by_object.get(object_id, []))


def load_object_metrics(indexes: Indexes, logic_dir: Path) -> None:
    for object_id, rel in indexes.logic_index.items():
        p = logic_dir / rel
        if not p.exists():
            continue
        o = json.loads(p.read_text(encoding="utf-8"))
        cx = o.get("complexity", {}).get("cyclomatic", {})
        indexes.metrics[object_id] = {
            "cyclomatic": cx.get("score"),
            "exceeds": bool(cx.get("exceeds_threshold")),
            "shape": (o.get("shape") or {}).get("shape", ""),
        }


# ---------------------------------------------------------------------------
# MODEL: D2 - system data-flow map
# ---------------------------------------------------------------------------

_CRUD_WORDS = {"C": "creates", "R": "reads", "U": "updates", "D": "deletes"}


def build_dataflow_spec(indexes: Indexes, parser_root: Path, budget: int) -> DiagramSpec:
    """
    Objects and the tables they touch.

    The predecessor drew a call graph. On this codebase that graph has zero
    edges, because nothing calls anything internally - it rendered five
    disconnected boxes. Joining Agent 4's CRUD matrix answers the question a
    stakeholder actually asks: what touches my data, and how?
    """
    spec = DiagramSpec(diagram_id="system_dataflow", type="dataflow",
                       title="System data flow: programs and the data they touch")
    seq = _IdSeq()
    obj_nodes, table_nodes = {}, {}

    for object_id in indexes.object_index:
        m = indexes.metrics.get(object_id, {})
        bits = []
        n_rules = indexes.rule_count(object_id)
        if n_rules:
            bits.append(f"{n_rules} rule{'s' if n_rules != 1 else ''}")
        if m.get("cyclomatic") is not None:
            bits.append(f"CC {m['cyclomatic']}")
        if m.get("shape"):
            bits.append(m["shape"].replace("_", " ").title())
        node = Node(id=seq.next(), kind=KIND_OBJECT,
                    label=short_object_name(object_id), sublabel=" · ".join(bits),
                    origin_id=object_id, label_tier=1,
                    emphasis="warning" if m.get("exceeds") else "")
        obj_nodes[object_id] = node
        spec.nodes.append(node)

    for object_id, tables in indexes.crud.items():
        if object_id not in obj_nodes:
            continue
        for table, ops in sorted((tables or {}).items()):
            key = table.upper()
            if key not in table_nodes:
                # A table Agent 3 never saw is reported, not silently drawn as
                # if it were part of the known schema.
                known = key in indexes.known_tables
                table_nodes[key] = Node(
                    id=seq.next(), kind=KIND_DATA, label=key,
                    sublabel="" if known else "not in DDL",
                    emphasis="" if known else "external", origin_id=key, label_tier=1)
                spec.nodes.append(table_nodes[key])
            ordered = "".join(c for c in "CRUD" if c in (ops or "").upper())
            spec.edges.append(Edge(src=obj_nodes[object_id].id, dst=table_nodes[key].id,
                                   kind="CRUD", label=ordered or "?"))

    # Resolved internal calls, deduplicated - the old agent emitted one edge
    # per call site, so a helper called three times drew three arrows.
    seen_calls = set()
    for object_id, rel in indexes.object_index.items():
        p = parser_root / rel
        if not p.exists():
            continue
        obj = json.loads(p.read_text(encoding="utf-8"))
        for stmt in obj.get("statements", {}).values():
            if stmt.get("statement_type") != "CALL":
                continue
            target = stmt.get("call_target_object_id")
            if target and target in obj_nodes:
                pair = (object_id, target)
                if pair in seen_calls:
                    continue
                seen_calls.add(pair)
                spec.edges.append(Edge(src=obj_nodes[object_id].id,
                                       dst=obj_nodes[target].id, kind="FLOW", label="calls"))

    if not spec.edges:
        spec.notes.append("No data access or internal calls were resolved for these objects.")
    reduce_dataflow(spec, budget)
    return spec


def reduce_dataflow(spec: DiagramSpec, budget: int) -> None:
    """Keep the most-connected tables; report the rest rather than hiding them."""
    original = len(spec.nodes)
    if original <= budget:
        spec.budget_report = {"original_nodes": original, "emitted_nodes": original,
                              "budget": budget, "collapsed": []}
        return
    degree = {}
    for e in spec.edges:
        degree[e.dst] = degree.get(e.dst, 0) + 1
    tables = [n for n in spec.nodes if n.kind == KIND_DATA]
    keep_count = max(1, budget - (len(spec.nodes) - len(tables)))
    ranked = sorted(tables, key=lambda n: (-degree.get(n.id, 0), n.label))
    dropped = {n.id for n in ranked[keep_count:]}
    if not dropped:
        return
    spec.nodes = [n for n in spec.nodes if n.id not in dropped]
    spec.edges = [e for e in spec.edges if e.dst not in dropped and e.src not in dropped]
    spec.notes.append(f"{len(dropped)} less-referenced tables omitted to stay within "
                      f"the {budget}-node budget.")
    spec.budget_report = {"original_nodes": original, "emitted_nodes": len(spec.nodes),
                          "budget": budget,
                          "collapsed": [f"omitted {len(dropped)} low-degree tables"]}


def short_object_name(object_id: str) -> str:
    """PROC-.SP_TRANSFER_FUNDS -> SP_TRANSFER_FUNDS (package members keep ::)."""
    name = object_id.split("-.", 1)[-1] if "-." in object_id else object_id
    return name.replace("::", " :: ")


class _IdSeq:
    """Short, stable node ids. The old agent used the full statement id, giving
    ~110-character node names repeated twice per edge."""

    def __init__(self, prefix: str = "N"):
        self.prefix, self.n = prefix, 0

    def next(self) -> str:
        self.n += 1
        return f"{self.prefix}{self.n}"


# ---------------------------------------------------------------------------
# MODEL: D3 - per-object process flow
# ---------------------------------------------------------------------------

_KIND_BY_STATEMENT = {
    "IF": KIND_DECISION, "CASE": KIND_DECISION,
    "LOOP": KIND_LOOP, "FOR_LOOP": KIND_LOOP, "WHILE_LOOP": KIND_LOOP,
    "EXCEPTION_HANDLER": KIND_ERROR, "RAISE": KIND_ERROR,
    "RETURN": KIND_TERMINAL,
    "UPDATE": KIND_DATA, "INSERT": KIND_DATA, "DELETE": KIND_DATA,
    "MERGE": KIND_DATA, "SELECT_INTO": KIND_DATA,
    "COMMIT": KIND_TERMINAL, "ROLLBACK": KIND_TERMINAL,
}

_BRANCH_LABEL_CLEANUP = {
    "true": "yes", "false": "otherwise", "elsif": "otherwise if",
    "loop body": "each row",
}


def classify_statement(stmt: dict) -> str:
    return _KIND_BY_STATEMENT.get(stmt["statement_type"], KIND_PROCESS)


def label_for_statement(stmt: dict, object_id: str, indexes: Indexes,
                        abs_path: str) -> tuple:
    """
    Strict priority ladder. Tier-1 coverage is a published quality metric,
    not an implementation detail - "Decision (line 38)" tells a business
    reader nothing, and that was every label the old agent produced.
    """
    st = stmt["statement_type"]
    line = stmt.get("start_line")

    # A rule may be anchored at this line because it describes the BRANCH that
    # starts here, not this statement. Only a decision may take its label from
    # a rule; otherwise an UPDATE that happens to open an ELSIF branch gets
    # drawn as a data store bearing the ELSIF's condition — wrong shape and
    # wrong meaning at once. Branch rules belong on the edge.
    if st in ("IF", "CASE"):
        rule = indexes.rule_in_span(object_id, line, stmt.get("end_line", line))
        if rule and rule.get("condition_text"):
            return humanise_condition(rule["condition_text"]) + "?", [rule["rule_id"]], 1

    if st in ("UPDATE", "INSERT", "DELETE", "MERGE"):
        tables = ", ".join(t.upper() for t in (stmt.get("tables") or [])) or "data"
        verb = {"UPDATE": "Update", "INSERT": "Insert into",
                "DELETE": "Delete from", "MERGE": "Merge into"}[st]
        return f"{verb} {tables}", [], 2
    if st == "SELECT_INTO":
        tables = ", ".join(t.upper() for t in (stmt.get("tables") or [])) or "data"
        return f"Look up {tables}", [], 2
    if st == "EXCEPTION_HANDLER":
        handlers = ", ".join(stmt.get("handler_for") or []) or "error"
        return f"On error: {handlers}", [], 2
    if st == "CALL":
        return f"Call {stmt.get('call_target', 'external routine')}", [], 2
    if st == "RAISE":
        text = raw_snippet(abs_path, line, stmt.get("end_line", line))
        m = re.search(r"RAISE\s+([A-Za-z_][A-Za-z0-9_$#]*)", text, re.IGNORECASE)
        return (f"Raise {m.group(1)}" if m else "Raise error"), [], 2
    if st in ("COMMIT", "ROLLBACK"):
        return st.capitalize(), [], 2
    if st in ("LOOP", "FOR_LOOP", "WHILE_LOOP"):
        return "Repeat for each row", [], 2
    if st == "RETURN":
        text = raw_snippet(abs_path, line, stmt.get("end_line", line)).rstrip(";")
        value = re.sub(r"^\s*RETURN\s*", "", text, flags=re.IGNORECASE).strip()
        return (f"Return {trim(value)}" if value else "Return"), [], 2
    if st == "ASSIGNMENT":
        # "Assignment (line 35)" tells a business reader nothing. The target
        # and value are one re-slice away and turn a tier-3 fallback into a
        # readable step.
        text = raw_snippet(abs_path, line, stmt.get("end_line", line)).rstrip(";")
        lhs, sep, rhs = text.partition(":=")
        if sep and lhs.strip():
            return f"Set {readable(lhs.strip())} to {trim(rhs.strip())}", [], 2

    return f"{st.replace('_', ' ').title()} (line {line})", [], 3


def readable(identifier: str) -> str:
    ident = re.sub(r"^[pv]_", "", identifier.split(".")[-1], flags=re.IGNORECASE)
    return " ".join(p.capitalize() for p in ident.split("_") if p) or identifier


def trim(text: str, limit: int = 46) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def humanise_condition(cond: str) -> str:
    """Trim a source condition to something readable without changing meaning."""
    text = re.sub(r"\s+", " ", cond).strip()
    # Strip only a wrapper that encloses the WHOLE expression. A blanket
    # strip("()") amputated the closing paren of `NVL(x, y - 9999)`, leaving a
    # label that looked truncated and unbalanced.
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        for i, ch in enumerate(text):
            depth += (ch == "(") - (ch == ")")
            if depth == 0 and i < len(text) - 1:
                break
        else:
            text = text[1:-1].strip()
            continue
        break
    text = re.sub(r"\bv_|\bp_", "", text, flags=re.IGNORECASE)
    return text if len(text) <= 70 else text[:67].rstrip() + "..."


def build_flow_spec(object_id: str, obj: dict, indexes: Indexes,
                    budget: int) -> DiagramSpec | None:
    statements = obj.get("statements", {})
    cfg = obj.get("control_flow_graph", {"nodes": [], "edges": []})
    if not cfg.get("nodes"):
        return None
    abs_path = indexes.file_abs.get(obj.get("file_id"), "")

    spec = DiagramSpec(diagram_id=f"flow_{short_object_name(object_id)}",
                       type="process_flow",
                       title=f"Process flow: {short_object_name(object_id)}",
                       object_id=object_id)

    # ORDER: source order, so the renderer's layered layout follows reading
    # order rather than dictionary iteration order (VEIL).
    cfg_ids = [sid for sid in cfg["nodes"] if sid in statements]
    cfg_ids.sort(key=lambda sid: (statements[sid].get("start_line") or 0, sid))

    # START, and an "any statement fails" node when the object has handlers,
    # are added after collapsing — so reserve their slots or the emitted
    # diagram lands just over the budget it was supposed to respect.
    reserved = 1 + (1 if any(e.get("from") == "*" for e in cfg.get("edges", [])) else 0)
    remap = collapse_runs(cfg_ids, statements, max(1, budget - reserved))

    seq = _IdSeq()
    node_for_group, original_count = {}, len(cfg_ids)
    for sid in cfg_ids:
        group = remap[sid]
        if group in node_for_group:
            continue
        members = [s for s in cfg_ids if remap[s] == group]
        if len(members) > 1:
            first, last = statements[members[0]], statements[members[-1]]
            tables = sorted({t.upper() for m in members
                             for t in (statements[m].get("tables") or [])})
            node = Node(id=seq.next(), kind=KIND_PROCESS,
                        label=f"{len(members)} steps",
                        sublabel=("touches " + ", ".join(tables)) if tables else
                                 f"lines {first['start_line']}-{last.get('end_line', last['start_line'])}",
                        source_line=first["start_line"], origin_id=members[0], label_tier=2)
        else:
            stmt = statements[members[0]]
            label, rule_ids, tier = label_for_statement(stmt, object_id, indexes, abs_path)
            node = Node(id=seq.next(), kind=classify_statement(stmt), label=label,
                        rule_ids=rule_ids, source_line=stmt.get("start_line"),
                        origin_id=members[0], label_tier=tier)
        node_for_group[group] = node
        spec.nodes.append(node)

    start = Node(id="START", kind=KIND_TERMINAL, label=short_object_name(object_id),
                 origin_id=object_id, label_tier=1)
    spec.nodes.insert(0, start)

    top_level = [s for s in statements.values() if s.get("parent_id") is None
                 and s["statement_id"] in remap]
    if top_level:
        first_stmt = min(top_level, key=lambda s: (s.get("start_line") or 0, s["statement_id"]))
        target = node_for_group.get(remap[first_stmt["statement_id"]])
        if target:
            spec.edges.append(Edge(src="START", dst=target.id))

    any_error = None
    for e in cfg.get("edges", []):
        dst_stmt = e.get("to")
        if e.get("from") == "*":
            if dst_stmt not in remap:
                continue
            if any_error is None:
                any_error = Node(id=seq.next(), kind=KIND_ERROR, label="Any statement fails",
                                 label_tier=1)
                spec.nodes.append(any_error)
            spec.edges.append(Edge(src=any_error.id, dst=node_for_group[remap[dst_stmt]].id,
                                   kind="EXCEPTION", label=e.get("on", "error")))
            continue
        src_stmt = e.get("from")
        if src_stmt not in remap or dst_stmt not in remap:
            continue
        src_node = node_for_group[remap[src_stmt]]
        dst_node = node_for_group[remap[dst_stmt]]
        if src_node.id == dst_node.id:
            continue  # collapsed away
        etype = e.get("type")
        if etype == "EXCEPTION_EDGE":
            spec.edges.append(Edge(src_node.id, dst_node.id, "EXCEPTION", "error"))
        elif etype == "LOOP_BACK_EDGE":
            spec.edges.append(Edge(src_node.id, dst_node.id, "LOOP_BACK", "repeat"))
        elif etype == "BRANCH_ENTRY":
            label, rule_id = branch_label(e.get("branch", ""), object_id,
                                          statements.get(dst_stmt),
                                          statements.get(src_stmt), indexes)
            # The CFG calls handler dispatch and loop entry "branches" too, but
            # they are not decision outcomes: `WHEN E_INSUFFICIENT_BALANCE` is
            # already fully informative, and Agent 5 anchors that rule at the
            # RAISE site by design. Typing them apart keeps the traceability
            # metric honest instead of penalising correct behaviour.
            kind = {KIND_DECISION: "BRANCH", KIND_ERROR: "EXCEPTION",
                    KIND_LOOP: "LOOP_ENTRY"}.get(src_node.kind, "FLOW")
            spec.edges.append(Edge(src_node.id, dst_node.id, kind, label, rule_id))
        else:
            spec.edges.append(Edge(src_node.id, dst_node.id, "FLOW"))

    dedupe_edges(spec)
    # When an object is nothing but decisions, raises, handlers and terminals,
    # no legal collapse can reach the budget — every remaining node is
    # protected. Structure wins over the budget, but the excess is declared
    # rather than quietly exceeded, so Agent 7 can tell the reader.
    oversize = len(spec.nodes) > budget
    if oversize:
        spec.notes.append(
            f"This procedure needs {len(spec.nodes)} nodes to show its decisions and "
            f"error paths, above the {budget}-node readability budget. Nothing was "
            f"dropped; consider reviewing it in sections.")
    spec.budget_report = {"original_nodes": original_count,
                          "emitted_nodes": len(spec.nodes), "budget": budget,
                          "oversize": oversize,
                          "collapsed": collapse_summary(cfg_ids, remap, statements)}
    return spec


def branch_label(raw_branch: str, object_id: str, target_stmt, source_stmt,
                 indexes: Indexes) -> tuple:
    """
    Name a branch by the rule it enacts.

    Four sibling branches of one IF previously all rendered as `elsif`, so the
    three interest tiers were indistinguishable. Agent 5 anchors ELSIF/ELSE
    rules at the branch's first line — but the PRIMARY branch's rule sits on
    the IF statement itself, so that one needs the second lookup or the "yes"
    arrow silently loses its BR-id.
    """
    base = _BRANCH_LABEL_CLEANUP.get((raw_branch or "").lower(), raw_branch or "")
    # WHEN(NO_DATA_FOUND) is parser syntax; the handler name is the useful part.
    m = re.match(r"^WHEN\((.*)\)$", base, re.IGNORECASE)
    if m:
        base = m.group(1)
    # NESTED_BLOCK#5 and IF#3.ELSIF1 are parser-internal names, never shown.
    if re.match(r"^(NESTED_BLOCK|IF)#", base):
        base = ""

    rule = None
    if target_stmt is not None:
        rule = indexes.rule_at(object_id, target_stmt.get("start_line"))
    if rule is None and (raw_branch or "").lower() in ("true", "then") and source_stmt is not None:
        rule = indexes.rule_at(object_id, source_stmt.get("start_line"))
    if rule:
        outcome = (rule.get("outcome_text") or "").strip()
        text = f"{rule['rule_id']} · {outcome}" if outcome else rule["rule_id"]
        return trim(text, 58), rule["rule_id"]
    return base, ""


def collapse_runs(cfg_ids: list, statements: dict, budget: int) -> dict:
    """
    Tiered, deterministic collapse. Detail is lost from the boring parts first.

    Invariant: no decision, loop, error path or terminal is ever removed. A
    reader must always be able to see the shape of the logic; what they lose
    is the run of assignments between two decisions.
    """
    remap = {sid: sid for sid in cfg_ids}
    if len(cfg_ids) <= budget:
        return remap

    def collapsible(sid):
        return classify_statement(statements[sid]) not in _NEVER_COLLAPSE

    # Tier 1 - merge contiguous collapsible siblings sharing a parent.
    run, runs = [], []
    for sid in cfg_ids:
        parent = statements[sid].get("parent_id")
        if collapsible(sid) and (not run or statements[run[-1]].get("parent_id") == parent):
            run.append(sid)
        else:
            if len(run) > 1:
                runs.append(run)
            run = [sid] if collapsible(sid) else []
    if len(run) > 1:
        runs.append(run)
    for r in runs:
        for sid in r:
            remap[sid] = r[0]

    # There is deliberately no second tier. An earlier version merged every
    # collapsible child of a parent regardless of adjacency, which fused
    # statements at lines 33 and 124 into one node and implied they run
    # together - the diagram met its budget by misrepresenting the flow. Once
    # contiguous runs are merged, the only way to shrink further is to delete
    # decisions or error paths, which the invariant forbids. The caller
    # declares the diagram oversize instead.
    return remap


def collapse_summary(cfg_ids: list, remap: dict, statements: dict) -> list:
    """Itemise what was hidden. Silent truncation would be worse than a big
    diagram - Agent 7 prints this in the gaps register."""
    groups = {}
    for sid in cfg_ids:
        groups.setdefault(remap[sid], []).append(sid)
    out = []
    for head, members in groups.items():
        if len(members) > 1:
            first, last = statements[members[0]], statements[members[-1]]
            out.append(f"{len(members)} statements collapsed "
                       f"(lines {first['start_line']}-{last.get('end_line', last['start_line'])})")
    return out


def dedupe_edges(spec: DiagramSpec) -> None:
    seen, kept = set(), []
    for e in spec.edges:
        key = (e.src, e.dst, e.kind, e.label)
        if key in seen:
            continue
        seen.add(key)
        kept.append(e)
    spec.edges = kept


# ---------------------------------------------------------------------------
# MODEL: D4 - entity state model
# ---------------------------------------------------------------------------

_CHECK_IN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_$#]*)\s+IN\s*\(([^)]*)\)", re.IGNORECASE)


def discover_state_attributes(indexes: Indexes) -> dict:
    """A CHECK constraint of the form `col IN ('A','B','C')` defines a state set."""
    out = {}
    for table, meta in indexes.tables.items():
        for chk in meta.get("check_constraints", []) or []:
            m = _CHECK_IN_RE.search(chk.get("expression") or "")
            if not m:
                continue
            values = [v.strip().strip("'") for v in m.group(2).split(",") if v.strip()]
            if len(values) >= 2:
                out[table.upper()] = {"column": m.group(1).upper(), "states": values,
                                       "constraint": chk.get("name", "")}
    return out


def build_state_specs(indexes: Indexes, parser_root: Path) -> list:
    """
    Transitions from UPDATEs that write the state column.

    This is the only place this agent derives knowledge that exists nowhere
    upstream, so it carries the strictest evidence bar: a transition whose
    target cannot be read from the source is dropped, and one whose origin
    cannot be determined is drawn from a neutral entry point and marked
    inferred. A fabricated state edge in a BRD is worse than no state diagram,
    because a reviewer cannot tell it is wrong.
    """
    specs = []
    for table, info in sorted(discover_state_attributes(indexes).items()):
        column, states = info["column"], info["states"]
        transitions = []

        for object_id, rel in indexes.object_index.items():
            p = parser_root / rel
            if not p.exists():
                continue
            obj = json.loads(p.read_text(encoding="utf-8"))
            abs_path = indexes.file_abs.get(obj.get("file_id"), "")
            statements = obj.get("statements", {})
            for stmt in statements.values():
                if stmt["statement_type"] != "UPDATE":
                    continue
                if table.upper() not in {t.upper() for t in (stmt.get("tables") or [])}:
                    continue
                if column not in {c.upper() for c in (stmt.get("writes") or [])}:
                    continue
                text = raw_snippet(abs_path, stmt["start_line"], stmt.get("end_line", stmt["start_line"]))
                m = re.search(rf"{column}\s*=\s*'([^']+)'", text, re.IGNORECASE)
                if not m:
                    continue  # target unresolvable - drop rather than guess
                target = m.group(1).upper()
                if target not in {s.upper() for s in states}:
                    continue
                guard_rule = nearest_guard_rule(stmt, statements, object_id, indexes)
                origin, confidence = "", "inferred"
                if guard_rule:
                    for s in states:
                        if re.search(rf"'{re.escape(s)}'", guard_rule.get("condition_text", ""),
                                     re.IGNORECASE):
                            origin, confidence = s.upper(), "confirmed"
                            break
                transitions.append({
                    "from": origin, "to": target,
                    "label": guard_rule["rule_id"] if guard_rule else "",
                    "guard": humanise_condition(guard_rule["condition_text"]) if guard_rule else "",
                    "confidence": confidence, "object_id": object_id,
                })

        if not transitions:
            continue

        spec = DiagramSpec(diagram_id=f"state_{table}", type="state",
                           title=f"{table}: {column.replace('_', ' ').title()} lifecycle",
                           entity=table)
        seq = _IdSeq("S")
        node_by_state = {}
        for s in states:
            n = Node(id=seq.next(), kind=KIND_STATE, label=s.upper(), origin_id=s, label_tier=1)
            node_by_state[s.upper()] = n
            spec.nodes.append(n)
        for t in transitions:
            dst = node_by_state.get(t["to"])
            if dst is None:
                continue
            src = node_by_state.get(t["from"]) if t["from"] else None
            label = " · ".join(x for x in (t["label"], t["guard"]) if x)
            if src is None:
                spec.edges.append(Edge("[*]", dst.id, "TRANSITION",
                                        label or "set on create", emphasis="inferred"))
            else:
                spec.edges.append(Edge(src.id, dst.id, "TRANSITION", label))
        dedupe_edges(spec)

        reachable = {e.dst for e in spec.edges} | {e.src for e in spec.edges}
        for s, n in node_by_state.items():
            if n.id not in reachable:
                note = (f"Permitted by {info['constraint']} but no code in this "
                        f"repository transitions into it.")
                spec.notes.append(f"State {s}: {note}")
                # Anchor the note to the state it is about — attaching every
                # note to the first node points the reader at the wrong state.
                spec.note_anchors[n.id] = note
        if any(e.emphasis == "inferred" for e in spec.edges):
            spec.notes.append("Transitions drawn from the entry point could not be tied to a "
                              "specific prior state and are marked inferred.")
        spec.budget_report = {"original_nodes": len(spec.nodes),
                              "emitted_nodes": len(spec.nodes), "budget": None, "collapsed": []}
        specs.append(spec)
    return specs


def nearest_guard_rule(stmt: dict, statements: dict, object_id: str, indexes: Indexes):
    """Walk up parent_id to the controlling decision and take its rule."""
    current, hops = stmt, 0
    while current is not None and hops < 12:
        parent_id = current.get("parent_id")
        if not parent_id or parent_id not in statements:
            return None
        parent = statements[parent_id]
        if parent["statement_type"] in ("IF", "CASE"):
            rule = indexes.rule_at(object_id, current.get("start_line")) or \
                   indexes.rule_at(object_id, parent.get("start_line"))
            if rule:
                return rule
        current, hops = parent, hops + 1
    return None


# ---------------------------------------------------------------------------
# MODEL: D5 - CRUD matrix
# ---------------------------------------------------------------------------

def build_crud_markdown(indexes: Indexes) -> tuple:
    """
    Tabular data belongs in a table, not a node-link graph (Moody: cognitive
    fit). Agent 4 has computed this since its redesign and nothing rendered it.
    """
    matrix = {oid: (tabs or {}) for oid, tabs in indexes.crud.items() if tabs}
    if not matrix:
        return "", {}
    tables = sorted({t.upper() for tabs in matrix.values() for t in tabs})
    header = "| Program | " + " | ".join(tables) + " |"
    sep = "|---" * (len(tables) + 1) + "|"
    rows = []
    for oid in sorted(matrix):
        cells = []
        for t in tables:
            ops = ""
            for k, v in matrix[oid].items():
                if k.upper() == t:
                    ops = "".join(c for c in "CRUD" if c in (v or "").upper())
            cells.append(ops or "")
        rows.append(f"| {short_object_name(oid)} | " + " | ".join(cells) + " |")
    legend = ("\n*C = creates, R = reads, U = updates, D = deletes. "
              "Derived from the DML statements each program executes.*")
    return "\n".join([header, sep, *rows]) + "\n" + legend, matrix


# ---------------------------------------------------------------------------
# RENDER - the only Mermaid-aware code
# ---------------------------------------------------------------------------

_SHAPES = {
    KIND_DECISION: ("{\"", "\"}"),
    KIND_LOOP: ("[/\"", "\"/]"),
    KIND_ERROR: ("[\"", "\"]"),
    KIND_TERMINAL: ("([\"", "\"])"),
    KIND_DATA: ("[(\"", "\")]"),
    KIND_OBJECT: ("[\"", "\"]"),
    KIND_PROCESS: ("[\"", "\"]"),
}

_EDGE_STYLE = {
    "FLOW": "-->", "BRANCH": "-->", "LOOP_BACK": "-.->", "LOOP_ENTRY": "-->",
    "EXCEPTION": "-.->", "CRUD": "-->", "TRANSITION": "-->",
}


def esc(text: str) -> str:
    """Quote-safe label text. Unquoted labels are lexed as markup - a handler
    label like WHEN(NO_DATA_FOUND) opens a node shape at the '(' and kills the
    parse for the whole diagram."""
    return (text or "").replace('"', "#quot;").replace("\n", " ").strip()


class MermaidRenderer:
    def render(self, spec: DiagramSpec) -> str:
        if spec.type == "state":
            return self._render_state(spec)
        return self._render_flowchart(spec)

    def _render_flowchart(self, spec: DiagramSpec) -> str:
        direction = "LR" if spec.type == "dataflow" else "TD"
        lines = [f"flowchart {direction}"]
        for n in spec.nodes:
            open_s, close_s = _SHAPES.get(n.kind, _SHAPES[KIND_PROCESS])
            text = esc(n.label)
            if n.sublabel:
                text += "<br/>" + esc(n.sublabel)
            line = f"    {n.id}{open_s}{text}{close_s}"
            if n.emphasis:
                line += f":::{n.emphasis}"
            elif n.kind == KIND_ERROR:
                line += ":::errorNode"
            elif n.kind == KIND_DATA:
                line += ":::dataNode"
            lines.append(line)
        for e in spec.edges:
            arrow = _EDGE_STYLE.get(e.kind, "-->")
            if e.label:
                lines.append(f'    {e.src} {arrow}|"{esc(e.label)}"| {e.dst}')
            else:
                lines.append(f"    {e.src} {arrow} {e.dst}")
        lines += [
            "    classDef warning fill:#fff4e5,stroke:#d97706,stroke-width:2px",
            "    classDef external fill:#f5f5f5,stroke:#999,stroke-dasharray: 4 2",
            "    classDef inferred fill:#f5f5f5,stroke:#999,stroke-dasharray: 4 2",
            "    classDef errorNode fill:#fdecea,stroke:#c0392b",
            "    classDef dataNode fill:#eaf3fb,stroke:#2c6fad",
        ]
        return "\n".join(lines) + "\n"

    def _render_state(self, spec: DiagramSpec) -> str:
        lines = ["stateDiagram-v2"]
        for n in spec.nodes:
            lines.append(f"    {n.id} : {esc(n.label)}")
        for e in spec.edges:
            label = f" : {esc(e.label)}" if e.label else ""
            lines.append(f"    {e.src} --> {e.dst}{label}")
        for node_id, note in spec.note_anchors.items():
            lines.append(f"    note right of {node_id}")
            lines.append(f"        {esc(note)}")
            lines.append("    end note")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# VALIDATE
# ---------------------------------------------------------------------------

def validate_spec(spec: DiagramSpec, budget: int) -> list:
    problems = []
    ids = spec.node_ids()
    for e in spec.edges:
        for endpoint in (e.src, e.dst):
            if endpoint not in ids and endpoint != "[*]":
                problems.append(f"{spec.diagram_id}: edge references undeclared node {endpoint}")
    for n in spec.nodes:
        blob = f"{n.label} {n.sublabel}"
        for pat in _INTERNAL_ID_PATTERNS:
            if pat.search(blob):
                problems.append(f"{spec.diagram_id}: internal identifier leaked in label "
                                f"'{blob[:60]}'")
    for e in spec.edges:
        for pat in _INTERNAL_ID_PATTERNS:
            if pat.search(e.label or ""):
                problems.append(f"{spec.diagram_id}: internal identifier leaked in edge label "
                                f"'{e.label[:60]}'")
    # Exceeding the budget is permitted only when declared. An undeclared
    # overrun means the collapse logic failed silently, which is the bug the
    # dead --max-nodes flag used to hide.
    if (spec.type == "process_flow" and len(spec.nodes) > budget
            and not spec.budget_report.get("oversize")):
        problems.append(f"{spec.diagram_id}: {len(spec.nodes)} nodes exceeds budget "
                        f"{budget} without being declared oversize")
    if not spec.nodes:
        problems.append(f"{spec.diagram_id}: no nodes")
    return problems


def validate_mermaid(text: str, diagram_id: str) -> list:
    problems = []
    if not text.strip():
        return [f"{diagram_id}: empty output"]
    head = text.splitlines()[0].strip()
    if not (head.startswith("flowchart ") or head.startswith("stateDiagram")):
        problems.append(f"{diagram_id}: missing diagram declaration")
    for i, line in enumerate(text.splitlines(), 1):
        if line.count('"') % 2 != 0:
            problems.append(f"{diagram_id}:{i}: unbalanced quotes")
    for m in re.finditer(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*)", text, re.MULTILINE):
        if m.group(1)[0].isdigit():
            problems.append(f"{diagram_id}: node id starts with a digit")
    return problems


# ---------------------------------------------------------------------------
# WRITE
# ---------------------------------------------------------------------------

def quality_metrics(specs: list) -> dict:
    flows = [s for s in specs if s.type == "process_flow"]
    decisions = [n for s in flows for n in s.nodes if n.kind == KIND_DECISION]
    tier1 = [n for n in decisions if n.label_tier == 1]
    branches = [e for s in flows for e in s.edges if e.kind == "BRANCH"]
    traced = [e for e in branches if e.rule_id]
    all_nodes = [n for s in specs for n in s.nodes]
    return {
        "decision_nodes": len(decisions),
        "decision_label_tier1_pct": round(len(tier1) / len(decisions), 4) if decisions else 1.0,
        "branch_edges": len(branches),
        "branch_traceability_pct": round(len(traced) / len(branches), 4) if branches else 1.0,
        "max_nodes_any_diagram": max((len(s.nodes) for s in specs), default=0),
        "fallback_labels": sum(1 for n in all_nodes if n.label_tier == 3),
        "total_nodes": len(all_nodes),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 6: Deterministic PL/SQL visual model generator")
    ap.add_argument("--parser-root", default="output/parser")
    ap.add_argument("--parser-run", default="latest")
    ap.add_argument("--data-root", default="output/data")
    ap.add_argument("--data-run", default="latest")
    ap.add_argument("--logic-root", default="output/logic")
    ap.add_argument("--logic-run", default="latest")
    ap.add_argument("--rules-root", default="output/rules")
    ap.add_argument("--rules-run", default="latest")
    ap.add_argument("--inventory-root", default="output/inventory")
    ap.add_argument("--inventory-run", default="latest")
    ap.add_argument("--output-root", default="output/diagram")
    ap.add_argument("--output", default=None)
    ap.add_argument("--max-nodes", type=int, default=DEFAULT_NODE_BUDGET,
                    help="Hard node budget per process-flow diagram.")
    args = ap.parse_args()

    parser_artifact, parser_run_version = load_run(args.parser_root, args.parser_run,
                                                   "parser_artifact.json")
    parser_root = Path(args.parser_root) / parser_run_version

    degraded = []

    def optional(root, run, fname, label):
        try:
            payload, version = load_run(root, run, fname)
            return payload, version, Path(root) / version
        except (FileNotFoundError, KeyError):
            degraded.append(label)
            return {}, None, Path(".")

    inventory, inv_version, _ = optional(args.inventory_root, args.inventory_run,
                                          "inventory-artifact.json", "inventory")
    data_artifact, data_version, data_dir = optional(args.data_root, args.data_run,
                                                      "data_artifact.json", "data")
    logic_artifact, logic_version, logic_dir = optional(args.logic_root, args.logic_run,
                                                         "logic_artifact.json", "logic")
    rules_artifact, rules_version, _ = optional(args.rules_root, args.rules_run,
                                                 "rules_artifact.json", "rules")

    indexes = Indexes(parser_artifact, data_artifact, logic_artifact, rules_artifact, inventory)
    if logic_version:
        load_object_metrics(indexes, logic_dir)

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    diagrams_dir = run_dir / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    # ---- MODEL -----------------------------------------------------------
    specs = [build_dataflow_spec(indexes, parser_root, args.max_nodes)]
    specs.extend(build_state_specs(indexes, parser_root))
    for object_id, rel in indexes.object_index.items():
        p = parser_root / rel
        if not p.exists():
            continue
        obj = json.loads(p.read_text(encoding="utf-8"))
        spec = build_flow_spec(object_id, obj, indexes, args.max_nodes)
        if spec:
            specs.append(spec)

    # ---- VALIDATE + RENDER + WRITE ---------------------------------------
    renderer = MermaidRenderer()
    problems, diagram_index, warnings = [], {}, []
    for spec in specs:
        problems.extend(validate_spec(spec, args.max_nodes))
        text = renderer.render(spec)
        problems.extend(validate_mermaid(text, spec.diagram_id))
        fname = f"{spec.diagram_id}.mmd"
        (diagrams_dir / fname).write_text(text, encoding="utf-8")
        entry = {"type": spec.type, "title": spec.title,
                 "nodes": len(spec.nodes), "edges": len(spec.edges),
                 "budget": spec.budget_report, "notes": spec.notes}
        if spec.object_id:
            entry["object_id"] = spec.object_id
            entry["node_origins"] = {n.id: n.origin_id for n in spec.nodes if n.origin_id}
            entry["rule_ids"] = sorted({r for n in spec.nodes for r in n.rule_ids} |
                                       {e.rule_id for e in spec.edges if e.rule_id})
        if spec.entity:
            entry["entity"] = spec.entity
        diagram_index[fname] = entry
        for note in spec.notes:
            warnings.append({"kind": "DIAGRAM_NOTE", "diagram": spec.diagram_id, "detail": note})
        if spec.budget_report.get("collapsed"):
            warnings.append({"kind": "DETAIL_COLLAPSED", "diagram": spec.diagram_id,
                             "detail": "; ".join(spec.budget_report["collapsed"])})
        if spec.budget_report.get("oversize"):
            warnings.append({"kind": "OVERSIZE", "diagram": spec.diagram_id,
                             "object_id": spec.object_id,
                             "detail": f"{len(spec.nodes)} nodes exceeds the "
                                       f"{args.max_nodes}-node readability budget"})

    if problems:
        print("=== Diagram Agent FAILED validation ===", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        sys.exit(1)

    crud_md, crud_raw = build_crud_markdown(indexes)
    erd_path = str(data_dir / "erd.mmd") if data_version and (data_dir / "erd.mmd").exists() else None

    metrics = quality_metrics(specs)
    metrics["leaked_identifiers"] = 0
    metrics["degraded_inputs"] = degraded

    diagrams_artifact = {
        "pipeline_stage": "6_diagram", "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {"parser_run_version": parser_run_version,
                     "data_run_version": data_version,
                     "logic_run_version": logic_version,
                     "rules_run_version": rules_version,
                     "inventory_run_version": inv_version},
        "design_references": DESIGN_REFERENCES,
        "node_budget": args.max_nodes,
        "diagram_index": diagram_index,
        "erd_reference": erd_path,
        "crud_matrix": {"markdown": crud_md, "raw": crud_raw},
        "quality": metrics,
        "warnings": warnings,
        "stats": {"diagrams_generated": len(specs),
                  "dataflow": sum(1 for s in specs if s.type == "dataflow"),
                  "state_models": sum(1 for s in specs if s.type == "state"),
                  "process_flows": sum(1 for s in specs if s.type == "process_flow")},
    }
    (run_dir / "diagrams_artifact.json").write_text(
        json.dumps(diagrams_artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        (run_dir / "run_meta.json").write_text(json.dumps(
            {"stage": "6_diagram", "run_version": run_version, "status": "success",
             "generated_at": diagrams_artifact["generated_at"],
             "upstream": diagrams_artifact["upstream"], "quality": metrics},
            indent=2), encoding="utf-8")
        (Path(args.output_root) / "latest.json").write_text(json.dumps(
            {"run_version": run_version, "path": f"{run_version}/diagrams_artifact.json",
             "updated_at": diagrams_artifact["generated_at"]}, indent=2), encoding="utf-8")

    print("=== Diagram Agent Complete ===")
    print(f"Data-flow map          : {diagrams_artifact['stats']['dataflow']}")
    print(f"State models           : {diagrams_artifact['stats']['state_models']}")
    print(f"Process flows          : {diagrams_artifact['stats']['process_flows']}")
    print(f"ERD (from Agent 3)     : {'indexed' if erd_path else 'not available'}")
    print(f"Decision labels tier-1 : {metrics['decision_label_tier1_pct']:.0%}")
    print(f"Branch traceability    : {metrics['branch_traceability_pct']:.0%}")
    print(f"Largest diagram        : {metrics['max_nodes_any_diagram']} nodes "
          f"(budget {args.max_nodes})")
    if degraded:
        print(f"Degraded (missing)     : {', '.join(degraded)}")
    print(f"Output                 : {run_dir / 'diagrams_artifact.json'}")
    print("==============================")


if __name__ == "__main__":
    main()
