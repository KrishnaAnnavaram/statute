#!/usr/bin/env python3
"""
Stage 2: PARSER (deterministic, no LLM)
----------------------------------------
Reads the latest (or a pinned) inventory run produced by 00_inventory.py,
and for every file routed as parse-worthy, performs full structural
extraction of PL/SQL objects: packages (spec + body + members), standalone
procedures/functions, and triggers.

Parsing engine: a real ANTLR4 parse tree, generated from the Oracle PL/SQL
grammar (antlr/grammars-v4, Apache 2.0) — see
.claude/scripts/vendor/plsql_grammar/NOTICE.md for provenance. Individual
DML statements (SELECT/UPDATE/INSERT/DELETE/MERGE) are additionally handed
to sqlglot (dialect="oracle") for table/column/predicate breakdown.

Zero LLM calls. 100% deterministic — same input always produces the same
output (aside from generated_at timestamps and run_version folder names).

Output: output/parser/<run_version>/{raw_structure/*.json, parser_artifact.json,
run_meta.json}, plus output/parser/latest.json.

Usage:
    python .claude/scripts/02_parser.py [--inventory-run latest|<version>]
                                        [--inventory-root output/inventory]
                                        [--output-root output/parser]
                                        [--output <path>] [--verbose]
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_VENDOR_DIR = Path(__file__).parent / "vendor" / "plsql_grammar"
sys.path.insert(0, str(_VENDOR_DIR))

from antlr4 import FileStream, CommonTokenStream  # noqa: E402
from antlr4.error.ErrorListener import ErrorListener  # noqa: E402
from PlSqlLexer import PlSqlLexer  # noqa: E402
from PlSqlParser import PlSqlParser  # noqa: E402

import sqlglot  # noqa: E402


# ---------------------------------------------------------------------------
# Run versioning (same convention as 00_inventory.py)
# ---------------------------------------------------------------------------

def generate_run_version() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H.%M.%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Phase 0 — load inventory, route files
# ---------------------------------------------------------------------------

PARSE_WORTHY_ROLES = {"package", "procedure", "function", "trigger", "mixed"}
PASSTHROUGH_ROLES = {"schema_ddl", "seed_data"}


def load_inventory(inventory_root: str, inventory_run: str) -> tuple[dict, str, Path]:
    root = Path(inventory_root)
    if inventory_run == "latest":
        latest_path = root / "latest.json"
        if not latest_path.exists():
            raise FileNotFoundError(f"No inventory runs found: {latest_path} does not exist")
        pointer = json.loads(latest_path.read_text(encoding="utf-8"))
        run_version = pointer["run_version"]
    else:
        run_version = inventory_run

    artifact_path = root / run_version / "inventory-artifact.json"
    if not artifact_path.exists():
        raise FileNotFoundError(f"Inventory run not found: {artifact_path}")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    return artifact, run_version, artifact_path


def route_files(artifact: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (parse_worthy, passthrough, skipped) file records."""
    parse_worthy, passthrough, skipped = [], [], []
    for file_id, path in artifact["file_index"].items():
        meta = artifact["file_metadata"][file_id]
        record = {"file_id": file_id, "path": path, **meta}
        if meta.get("status") != "ok":
            skipped.append(record)
        elif meta.get("file_role") in PARSE_WORTHY_ROLES:
            parse_worthy.append(record)
        elif meta.get("file_role") in PASSTHROUGH_ROLES:
            passthrough.append(record)
        else:
            skipped.append(record)
    parse_worthy.sort(key=lambda r: r["file_id"])
    return parse_worthy, passthrough, skipped


# ---------------------------------------------------------------------------
# ANTLR parsing
# ---------------------------------------------------------------------------

class CollectingErrorListener(ErrorListener):
    def __init__(self):
        super().__init__()
        self.errors: list[dict] = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append({"line": line, "column": column, "message": msg})


def parse_source(abs_path: str):
    """Parse a whole file with the sql_script root rule. Returns (tree, errors, token_stream)."""
    input_stream = FileStream(abs_path, encoding="utf-8")
    lexer = PlSqlLexer(input_stream)
    lexer.removeErrorListeners()
    err = CollectingErrorListener()
    lexer.addErrorListener(err)
    stream = CommonTokenStream(lexer)
    parser = PlSqlParser(stream)
    parser.removeErrorListeners()
    parser.addErrorListener(err)
    tree = parser.sql_script()
    return tree, err.errors, stream


def child_types(ctx) -> list[str]:
    n = ctx.getChildCount() if hasattr(ctx, "getChildCount") else 0
    return [type(ctx.getChild(i)).__name__ for i in range(n)]


def find_child(ctx, type_name: str):
    n = ctx.getChildCount() if hasattr(ctx, "getChildCount") else 0
    for i in range(n):
        c = ctx.getChild(i)
        if type(c).__name__ == type_name:
            return c
    return None


def find_all_direct_children(ctx, type_names: set[str]) -> list:
    n = ctx.getChildCount() if hasattr(ctx, "getChildCount") else 0
    return [ctx.getChild(i) for i in range(n) if type(ctx.getChild(i)).__name__ in type_names]


def find_recursive(ctx, type_name: str):
    """Depth-first search for the first descendant of the given context type,
    at any depth — unlike find_child, which only checks direct children.
    Needed for e.g. Into_clauseContext, which sits several levels below a
    Select_statementContext (inside query_block), not directly under it."""
    if type(ctx).__name__ == type_name:
        return ctx
    n = ctx.getChildCount() if hasattr(ctx, "getChildCount") else 0
    for i in range(n):
        found = find_recursive(ctx.getChild(i), type_name)
        if found is not None:
            return found
    return None


def text_of(ctx) -> str:
    return ctx.getText() if ctx is not None else ""


# ---------------------------------------------------------------------------
# Object id assignment (mirrors the file-catalog skill's taxonomy)
# ---------------------------------------------------------------------------

TYPE_TAXONOMY = {
    "Create_procedure_bodyContext": ("PROC", "PROCEDURE"),
    "Create_function_bodyContext": ("FUNC", "FUNCTION"),
    "Create_packageContext": ("PKGS", "PACKAGE_SPEC"),
    "Create_package_bodyContext": ("PKGB", "PACKAGE_BODY"),
    "Create_triggerContext": ("TRG", "TRIGGER"),
}


def qualified_name(ctx, name_type: str) -> tuple[str, str]:
    """Extract (owner, name) from a create_X context's schema_object_name + xxx_name children."""
    schema_obj = find_child(ctx, "Schema_object_nameContext")
    name_ctx = find_child(ctx, name_type)
    name_text = text_of(name_ctx).upper()
    if schema_obj is not None:
        return text_of(schema_obj).upper(), name_text
    # xxx_name rules themselves allow identifier ('.' id_expression)? — an inline owner.name
    if "." in name_text:
        owner, _, bare = name_text.rpartition(".")
        return owner, bare
    return "", name_text


NAME_CTX_FOR = {
    "Create_procedure_bodyContext": "Procedure_nameContext",
    "Create_function_bodyContext": "Function_nameContext",
    "Create_packageContext": "Package_nameContext",
    "Create_package_bodyContext": "Package_nameContext",
    "Create_triggerContext": "Trigger_nameContext",
}


def make_object_id(prefix: str, owner: str, name: str, parent_object_id: str | None = None) -> str:
    if parent_object_id:
        return f"{parent_object_id}::{name}"
    return f"{prefix}-{owner}.{name}"


# ---------------------------------------------------------------------------
# Wrapped (obfuscated) object detection — per the file-catalog skill's own
# documented convention: never feed WRAPPED bodies to a real parser, they
# are deliberately garbled and will only ever produce syntax noise. Record
# just the header and move on.
# ---------------------------------------------------------------------------

_WRAPPED_HEADER_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(PACKAGE\s+BODY|PACKAGE|PROCEDURE|FUNCTION|TRIGGER)\s+"
    r"(?:([A-Za-z0-9_$#]+)\.)?([A-Za-z0-9_$#]+)\s+WRAPPED\b",
    re.IGNORECASE,
)

_WRAPPED_TYPE_PREFIX = {
    "PACKAGE": "PKGS", "PACKAGE BODY": "PKGB", "PROCEDURE": "PROC",
    "FUNCTION": "FUNC", "TRIGGER": "TRG",
}


def try_discover_wrapped_object(raw_text: str, file_id: str) -> dict | None:
    m = _WRAPPED_HEADER_RE.search(raw_text)
    if not m:
        return None
    grammar_type, owner, name = m.group(1).upper(), (m.group(2) or "").upper(), m.group(3).upper()
    prefix = _WRAPPED_TYPE_PREFIX[grammar_type]
    obj_type = {"PACKAGE": "PACKAGE_SPEC", "PACKAGE BODY": "PACKAGE_BODY",
                "PROCEDURE": "PROCEDURE", "FUNCTION": "FUNCTION", "TRIGGER": "TRIGGER"}[grammar_type]
    return {
        "object_id": make_object_id(prefix, owner, name), "type": obj_type,
        "owner": owner, "name": name, "parent_object_id": None, "file_id": file_id,
        "wrapped": True,
    }


# ---------------------------------------------------------------------------
# Phase 1 — object discovery (walks the already-parsed sql_script tree)
# ---------------------------------------------------------------------------

def discover_objects(tree, file_id: str) -> list[dict]:
    """
    Finds every top-level unit_statement that is one of our five object
    types, plus every package member nested inside a package body.
    Returns a flat list of {object_id, type, ctx, parent_object_id}.
    """
    objects = []
    n = tree.getChildCount()
    for i in range(n):
        unit = tree.getChild(i)
        if type(unit).__name__ != "Unit_statementContext":
            continue
        inner = unit.getChild(0)
        cls_name = type(inner).__name__
        if cls_name not in TYPE_TAXONOMY:
            continue
        prefix, obj_type = TYPE_TAXONOMY[cls_name]
        owner, name = qualified_name(inner, NAME_CTX_FOR[cls_name])
        object_id = make_object_id(prefix, owner, name)
        objects.append({
            "object_id": object_id, "type": obj_type, "ctx": inner,
            "owner": owner, "name": name, "parent_object_id": None,
            "file_id": file_id,
        })

        if cls_name == "Create_package_bodyContext":
            for member in find_all_direct_children(inner, {"Package_obj_bodyContext"}):
                body_ctx = find_child(member, "Procedure_bodyContext") or find_child(member, "Function_bodyContext")
                if body_ctx is None:
                    continue
                is_func = type(body_ctx).__name__ == "Function_bodyContext"
                member_name = text_of(find_child(body_ctx, "IdentifierContext")).upper()
                member_id = make_object_id("", "", member_name, parent_object_id=object_id)
                objects.append({
                    "object_id": member_id,
                    "type": "FUNCTION_MEMBER" if is_func else "PROCEDURE_MEMBER",
                    "ctx": body_ctx, "owner": owner, "name": member_name,
                    "parent_object_id": object_id, "file_id": file_id,
                })
    return objects


# ---------------------------------------------------------------------------
# Phase 4 — statement extraction visitor
# ---------------------------------------------------------------------------

# Wrapper contexts whose single meaningful child we should unwrap to find
# the real statement type.
_UNWRAP = {
    "StatementContext", "Sql_statementContext",
    "Data_manipulation_language_statementsContext",
    "Transaction_control_statementsContext",
    "Cursor_manipulation_statementsContext",
}

_LEAF_TYPE_NAMES = {
    "Select_statementContext": "SELECT",
    "Update_statementContext": "UPDATE",
    "Insert_statementContext": "INSERT",
    "Delete_statementContext": "DELETE",
    "Merge_statementContext": "MERGE",
    "Explain_statementContext": "EXPLAIN",
    "Lock_table_statementContext": "LOCK_TABLE",
    "Commit_statementContext": "COMMIT",
    "Rollback_statementContext": "ROLLBACK",
    "Savepoint_statementContext": "SAVEPOINT",
    "Set_transaction_commandContext": "SET_TRANSACTION",
    "Set_constraint_commandContext": "SET_CONSTRAINT",
    "Execute_immediateContext": "DYNAMIC_SQL",
    "Assignment_statementContext": "ASSIGNMENT",
    "Exit_statementContext": "EXIT",
    "Continue_statementContext": "CONTINUE",
    "Goto_statementContext": "GOTO",
    "Raise_statementContext": "RAISE",
    "Return_statementContext": "RETURN",
    "Null_statementContext": "NULL",
    "Call_statementContext": "CALL",
    "Pipe_row_statementContext": "PIPE_ROW",
    "Grant_statementContext": "GRANT",
    "Forall_statementContext": "FORALL",
    "Collection_method_callContext": "COLLECTION_METHOD_CALL",
}

DML_TYPES = {"SELECT", "SELECT_INTO", "UPDATE", "INSERT", "DELETE", "MERGE"}
DYNAMIC_SQL_TYPES = {"DYNAMIC_SQL", "FORALL"}


def classify_statement(ctx):
    """Unwraps a StatementContext down to its real leaf type. Returns (type_str, leaf_ctx)."""
    node = ctx
    seen_select_into = False
    for _ in range(8):
        cls = type(node).__name__
        if cls in _LEAF_TYPE_NAMES:
            stype = _LEAF_TYPE_NAMES[cls]
            if stype == "SELECT" and find_recursive(node, "Into_clauseContext"):
                stype = "SELECT_INTO"
            return stype, node
        _BLOCK_TYPES = {
            "If_statementContext": "IF", "Loop_statementContext": "LOOP",
            "Case_statementContext": "CASE", "BodyContext": "BODY", "BlockContext": "BLOCK",
        }
        if cls in _BLOCK_TYPES:
            return _BLOCK_TYPES[cls], node
        if cls in _UNWRAP and node.getChildCount() >= 1:
            node = node.getChild(0)
            continue
        return cls.replace("Context", "").upper(), node
    return "UNKNOWN", node


def extract_sqlglot_text(leaf, stype: str) -> str:
    """
    Slice the raw source text for a DML statement, ready to hand to sqlglot.

    Oracle's `SELECT ... INTO host_var_list FROM ...` is a PL/SQL-specific
    extension sqlglot doesn't understand — it isn't standard SQL, and
    sqlglot silently mis-parses it (observed: INTO target variables leaking
    into the "reads" column list, and in some cases the INTO target being
    mistaken for a CREATE-TABLE-AS-SELECT target). Strip the INTO clause's
    token span entirely before handing text to sqlglot, since sqlglot only
    needs to see the SELECT list / FROM / WHERE to do its job correctly.
    """
    stream = leaf.parser.getTokenStream()
    if stype == "SELECT_INTO":
        into_ctx = find_recursive(leaf, "Into_clauseContext")
        if into_ctx is not None:
            before = stream.getText(leaf.start, into_ctx.start.tokenIndex - 1)
            after = stream.getText(into_ctx.stop.tokenIndex + 1, leaf.stop)
            return f"{before} {after}"
    return stream.getText(leaf.start, leaf.stop)


class StatementIdAllocator:
    def __init__(self):
        self._seq = 0

    def next(self) -> int:
        self._seq += 1
        return self._seq


def extract_statements(body_or_seq_ctx, file_id: str, object_id: str,
                        statements: list, alloc: StatementIdAllocator,
                        parent_id: str | None, scope_path: list[str], depth: int):
    """
    Recursively walks a Seq_of_statementsContext (or a BodyContext, which
    contains one), producing flat statement records with parent/scope
    breadcrumbs. Appends to `statements` in place.
    """
    cls = type(body_or_seq_ctx).__name__
    if cls == "BodyContext":
        seq = find_child(body_or_seq_ctx, "Seq_of_statementsContext")
        if seq is not None:
            extract_statements(seq, file_id, object_id, statements, alloc, parent_id, scope_path, depth)
        for handler in find_all_direct_children(body_or_seq_ctx, {"Exception_handlerContext"}):
            handler_names = [text_of(n).upper() for n in find_all_direct_children(handler, {"Exception_nameContext"})]
            seq_no = alloc.next()
            handler_id = f"{file_id}__{object_id}__STMT_{seq_no:04d}"
            statements.append({
                "statement_id": handler_id, "parent_id": None,
                "statement_type": "EXCEPTION_HANDLER", "handler_for": handler_names,
                "start_line": handler.start.line, "end_line": handler.stop.line,
                "scope_path": scope_path + ["EXCEPTION"], "nesting_depth": depth,
            })
            handler_seq = find_child(handler, "Seq_of_statementsContext")
            if handler_seq is not None:
                extract_statements(handler_seq, file_id, object_id, statements, alloc,
                                    handler_id, scope_path + ["EXCEPTION", f"WHEN({'+'.join(handler_names)})"], depth + 1)
        return

    if cls != "Seq_of_statementsContext":
        return

    for stmt_ctx in find_all_direct_children(body_or_seq_ctx, {"StatementContext"}):
        stype, leaf = classify_statement(stmt_ctx)
        seq_no = alloc.next()
        stmt_id = f"{file_id}__{object_id}__STMT_{seq_no:04d}"
        record = {
            "statement_id": stmt_id, "parent_id": parent_id,
            "statement_type": stype,
            "start_line": stmt_ctx.start.line, "end_line": stmt_ctx.stop.line,
            "scope_path": list(scope_path), "nesting_depth": depth,
        }
        if stype in DML_TYPES:
            record["raw_text"] = extract_sqlglot_text(leaf, stype)
        if stype in DYNAMIC_SQL_TYPES:
            record["requires_manual_review"] = True
        if stype == "CALL":
            record["call_target"] = text_of(leaf).split("(")[0].upper()
        statements.append(record)

        if stype == "IF":
            then_seq = find_child(leaf, "Seq_of_statementsContext")
            if then_seq is not None:
                extract_statements(then_seq, file_id, object_id, statements, alloc,
                                    stmt_id, scope_path + [f"IF#{seq_no}.THEN"], depth + 1)
            for i, elsif in enumerate(find_all_direct_children(leaf, {"Elsif_partContext"}), start=1):
                elsif_seq = find_child(elsif, "Seq_of_statementsContext")
                if elsif_seq is not None:
                    extract_statements(elsif_seq, file_id, object_id, statements, alloc,
                                        stmt_id, scope_path + [f"IF#{seq_no}.ELSIF{i}"], depth + 1)
            else_part = find_child(leaf, "Else_partContext")
            if else_part is not None:
                else_seq = find_child(else_part, "Seq_of_statementsContext")
                if else_seq is not None:
                    extract_statements(else_seq, file_id, object_id, statements, alloc,
                                        stmt_id, scope_path + [f"IF#{seq_no}.ELSE"], depth + 1)
        elif stype == "LOOP":
            loop_seq = find_child(leaf, "Seq_of_statementsContext")
            if loop_seq is not None:
                extract_statements(loop_seq, file_id, object_id, statements, alloc,
                                    stmt_id, scope_path + [f"LOOP#{seq_no}"], depth + 1)
        elif stype in ("BODY", "BLOCK"):
            extract_statements(leaf, file_id, object_id, statements, alloc,
                                stmt_id, scope_path + [f"NESTED_BLOCK#{seq_no}"], depth + 1)
        elif stype == "CASE":
            for i, when in enumerate(find_all_direct_children(leaf, {"Case_when_part_stmtContext", "Case_when_partContext"}), start=1):
                when_seq = find_child(when, "Seq_of_statementsContext")
                if when_seq is not None:
                    extract_statements(when_seq, file_id, object_id, statements, alloc,
                                        stmt_id, scope_path + [f"CASE#{seq_no}.WHEN{i}"], depth + 1)


# ---------------------------------------------------------------------------
# Phase 5 — sqlglot enrichment (DML statements only)
# ---------------------------------------------------------------------------

def _col_names(node) -> list[str]:
    if node is None:
        return []
    return sorted({c.name.lower() for c in node.find_all(sqlglot.exp.Column) if c.name})


def enrich_with_sqlglot(record: dict, parse_issues: list, object_id: str) -> None:
    raw = record.get("raw_text")
    if not raw:
        return
    try:
        ast = sqlglot.parse_one(raw, dialect="oracle")
        tables = sorted({t.name.lower() for t in ast.find_all(sqlglot.exp.Table) if t.name})
        record["tables"] = tables
        stype = record["statement_type"]

        if stype in ("SELECT_INTO", "SELECT"):
            # Nothing is written in a SELECT — every column touched is a read.
            record["reads"] = _col_names(ast)

        elif stype == "UPDATE":
            # SET targets are writes; WHERE-clause columns are read-only predicates.
            set_exprs = ast.args.get("expressions", [])
            record["writes"] = sorted({e.this.name.lower() for e in set_exprs
                                        if isinstance(e, sqlglot.exp.EQ) and e.this.name})
            record["predicate_reads"] = _col_names(ast.args.get("where"))

        elif stype == "DELETE":
            # A DELETE doesn't write columns — it removes rows matched by WHERE.
            record["predicate_reads"] = _col_names(ast.args.get("where"))

        elif stype == "INSERT":
            this = ast.this
            target_cols = []
            if isinstance(this, sqlglot.exp.Schema):
                target_cols = [c.name.lower() for c in this.expressions if hasattr(c, "name") and c.name]
            record["writes"] = sorted(set(target_cols)) if target_cols else _col_names(ast.expression)

        elif stype == "MERGE":
            # MERGE has independent matched/not-matched branches — summarize
            # rather than claim precision, and flag for a closer look.
            record["writes"] = _col_names(ast)
            record["requires_manual_review"] = True

    except Exception as e:  # noqa: BLE001 - sqlglot raises assorted error types
        record["sql_breakdown_error"] = str(e)
        parse_issues.append({
            "severity": "info", "type": "sqlglot_parse_failed",
            "object_id": object_id, "statement_id": record["statement_id"],
            "message": f"sqlglot could not parse statement text: {e}",
        })
    finally:
        record.pop("raw_text", None)


# ---------------------------------------------------------------------------
# Phase 6 — control-flow graph
# ---------------------------------------------------------------------------

def _branch_entry_label(scope_path_tail: str) -> str:
    if scope_path_tail.endswith(".THEN"):
        return "true"
    if ".ELSIF" in scope_path_tail:
        return "elsif"
    if scope_path_tail.endswith(".ELSE"):
        return "false"
    if scope_path_tail.startswith("LOOP#"):
        return "loop body"
    if scope_path_tail.startswith("CASE#"):
        return "when"
    return scope_path_tail


def build_cfg(statements: list[dict]) -> dict:
    nodes = [s["statement_id"] for s in statements]
    edges = []
    by_parent: dict[str | None, list[dict]] = {}
    for s in statements:
        by_parent.setdefault(s["parent_id"], []).append(s)

    for parent_id, siblings in by_parent.items():
        for a, b in zip(siblings, siblings[1:]):
            edges.append({"from": a["statement_id"], "to": b["statement_id"], "type": "SEQUENCE"})

    # A parent (IF/LOOP/CASE/EXCEPTION_HANDLER) can have several distinct
    # branch groups as children (THEN/ELSIF1/ELSE, or a loop body). Without
    # an explicit edge from the parent into the FIRST statement of each
    # group, a CFG consumer only sees sibling-to-sibling edges within each
    # branch — the decision node itself never connects to any branch at
    # all, which is actively misleading in a rendered diagram (the decision
    # appears to skip straight to whatever follows the whole IF/LOOP).
    for parent_id, children in by_parent.items():
        if parent_id is None or not children:
            continue
        groups: dict[str, list[dict]] = {}
        for c in children:
            label = c.get("scope_path", ["body"])[-1] if c.get("scope_path") else "body"
            groups.setdefault(label, []).append(c)
        for label, group_children in groups.items():
            edges.append({"from": parent_id, "to": group_children[0]["statement_id"],
                          "type": "BRANCH_ENTRY", "branch": _branch_entry_label(label)})

    for s in statements:
        if s["statement_type"] == "EXCEPTION_HANDLER":
            edges.append({
                "from": "*", "to": s["statement_id"], "type": "EXCEPTION_EDGE",
                "on": "+".join(s.get("handler_for", [])) or "OTHERS",
            })
        if s["statement_type"] == "LOOP":
            children = by_parent.get(s["statement_id"], [])
            if children:
                edges.append({"from": children[-1]["statement_id"], "to": s["statement_id"], "type": "LOOP_BACK_EDGE"})

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Call resolution (mirrors the reference-graph skill's CALLS resolution rules)
# ---------------------------------------------------------------------------

def build_call_registry(all_objects: list[dict]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """
    known_callables: bare/qualified NAME -> object_id, for standalone procs/funcs
                      and PACKAGE_NAME.MEMBER for package members.
    sibling_registry: package_object_id -> {MEMBER_NAME: object_id}, so an
                       unqualified call from one member to another in the
                       SAME package can resolve without qualification.
    """
    known: dict[str, str] = {}
    siblings: dict[str, dict[str, str]] = {}
    for obj in all_objects:
        if obj["parent_object_id"] is None:
            known[obj["name"]] = obj["object_id"]
            if obj["owner"]:
                known[f"{obj['owner']}.{obj['name']}"] = obj["object_id"]
        else:
            pkg = obj["parent_object_id"]
            pkg_name = pkg.split(".")[-1]
            known[f"{pkg_name}.{obj['name']}"] = obj["object_id"]
            siblings.setdefault(pkg, {})[obj["name"]] = obj["object_id"]
    return known, siblings


# Bare (unqualified) built-ins provided by Oracle itself — not part of any
# local package, so they'd otherwise be indistinguishable from a genuinely
# unresolved/typo'd call. Extend as more built-ins turn up in real code.
_ORACLE_BUILTIN_PROCEDURES = {"RAISE_APPLICATION_ERROR"}


def resolve_calls(result: dict, obj_parent_id: str | None,
                   known: dict[str, str], siblings: dict[str, dict[str, str]],
                   parse_issues: list) -> None:
    for stmt in result["statements"].values():
        if stmt["statement_type"] != "CALL":
            continue
        target = stmt["call_target"].upper()
        if re.match(r"^(DBMS_|UTL_)\w+\.", target):
            stmt["resolved"] = True
            stmt["origin"] = "EXTERNAL"
            continue
        if target in _ORACLE_BUILTIN_PROCEDURES:
            stmt["resolved"] = True
            stmt["origin"] = "ORACLE_BUILTIN"
            continue
        if target in known:
            stmt["resolved"] = True
            stmt["call_target_object_id"] = known[target]
            continue
        bare = target.split(".")[-1]
        if obj_parent_id and bare in siblings.get(obj_parent_id, {}):
            stmt["resolved"] = True
            stmt["call_target_object_id"] = siblings[obj_parent_id][bare]
            continue
        stmt["resolved"] = False
        if "." in target:
            parse_issues.append({
                "severity": "warning", "type": "unresolved_reference",
                "object_id": result["object_id"], "statement_id": stmt["statement_id"],
                "message": f"CALL target '{stmt['call_target']}' not found among parsed objects.",
            })
        # bare, unqualified, no local match: left unresolved without an issue —
        # too many bare identifiers are ordinary expressions, not calls (same
        # rationale as the reference-graph skill's bare-call restriction).


# ---------------------------------------------------------------------------
# Per-object orchestration
# ---------------------------------------------------------------------------

def parse_object(obj: dict, file_id: str) -> dict:
    parse_issues: list[dict] = []
    statements: list[dict] = []
    alloc = StatementIdAllocator()

    ctx = obj["ctx"]
    cls_name = type(ctx).__name__
    body_ctx = find_child(ctx, "BodyContext")
    result = {
        "object_id": obj["object_id"], "type": obj["type"], "file_id": file_id,
        "owner": obj["owner"], "name": obj["name"],
        "parent_object_id": obj["parent_object_id"],
        "start_line": ctx.start.line, "end_line": ctx.stop.line,
        "parse_status": "success",
        "parameters": [
            {
                "name": text_of(find_child(p, "Parameter_nameContext")),
                "mode": next((t for t in child_types(p) if t == "TerminalNodeImpl" and text_of(p) and False), None),
                "type": text_of(find_child(p, "Type_specContext")),
            }
            for p in find_all_direct_children(ctx, {"ParameterContext"})
        ],
        "parse_issues": parse_issues,
    }
    # parameter mode (IN/OUT/INOUT/NOCOPY) requires scanning terminal tokens directly
    for i, p in enumerate(find_all_direct_children(ctx, {"ParameterContext"})):
        modes = [text_of(p.getChild(j)) for j in range(p.getChildCount())
                 if type(p.getChild(j)).__name__ == "TerminalNodeImpl"
                 and text_of(p.getChild(j)).upper() in ("IN", "OUT", "INOUT", "NOCOPY")]
        result["parameters"][i]["mode"] = "".join(modes) or "IN"

    declare_specs = find_child(ctx, "Seq_of_declare_specsContext")
    declarations = []
    cursors = []
    if declare_specs is not None:
        for spec in find_all_direct_children(declare_specs, {"Declare_specContext"}):
            inner = spec.getChild(0)
            inner_cls = type(inner).__name__
            if inner_cls == "Variable_declarationContext":
                declarations.append({
                    "name": text_of(find_child(inner, "IdentifierContext")),
                    "type": text_of(find_child(inner, "Type_specContext")),
                    "line": inner.start.line,
                })
            elif inner_cls == "Cursor_declarationContext":
                cursors.append({
                    "name": text_of(find_child(inner, "IdentifierContext")),
                    "line": inner.start.line,
                })
    result["declarations"] = declarations
    result["cursors"] = cursors

    if body_ctx is not None:
        extract_statements(body_ctx, file_id, obj["object_id"], statements, alloc, None, [], 1)

    for record in statements:
        if record["statement_type"] in DML_TYPES:
            enrich_with_sqlglot(record, parse_issues, obj["object_id"])

    result["statements"] = {s["statement_id"]: s for s in statements}
    result["control_flow_graph"] = build_cfg(statements)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 2: Deterministic PL/SQL structural parser")
    ap.add_argument("--inventory-root", default="output/inventory")
    ap.add_argument("--inventory-run", default="latest")
    ap.add_argument("--output-root", default="output/parser")
    ap.add_argument("--output", default=None, help="Exact output dir override (disables versioning; for tests)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    artifact, inv_run_version, inv_path = load_inventory(args.inventory_root, args.inventory_run)
    parse_worthy, passthrough, skipped = route_files(artifact)

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    raw_dir = run_dir / "raw_structure"
    raw_dir.mkdir(parents=True, exist_ok=True)

    objects_index: dict[str, str] = {}
    stats = {"objects_parsed": 0, "package_members": 0, "statements_extracted": 0,
             "dynamic_sql_blocks": 0, "parse_errors": 0, "unresolved_calls": 0}
    all_issues: list[dict] = []

    # Pass A — parse every file once, discover all objects across the whole
    # run before extracting any statement bodies, so cross-object (and
    # cross-package-member) call resolution has the complete picture.
    all_objects: list[dict] = []
    for file_rec in parse_worthy:
        file_id = file_rec["file_id"]
        if args.verbose:
            print(f"  [discovering] {file_rec['path']}", file=sys.stderr)

        raw_text = Path(file_rec["abs_path"]).read_text(encoding=file_rec.get("encoding_used", "utf-8"))
        wrapped_obj = try_discover_wrapped_object(raw_text, file_id)
        if wrapped_obj is not None:
            all_objects.append(wrapped_obj)
            all_issues.append({
                "severity": "info", "type": "wrapped_object_skipped",
                "file": file_rec["path"], "object_id": wrapped_obj["object_id"],
                "message": "Object body is WRAPPED (obfuscated) — header recorded, body not parsed.",
            })
            continue

        tree, syntax_errors, _ = parse_source(file_rec["abs_path"])
        if syntax_errors:
            stats["parse_errors"] += len(syntax_errors)
            for e in syntax_errors:
                all_issues.append({"severity": "error", "type": "syntax_error", "file": file_rec["path"], **e})
        all_objects.extend(discover_objects(tree, file_id))

    known, siblings = build_call_registry(all_objects)

    # Pass B — extract statement structure per object and resolve calls
    # against the now-complete registry.
    for obj in all_objects:
        file_id = obj["file_id"]
        if args.verbose:
            print(f"  [parsing] {obj['object_id']}", file=sys.stderr)
        try:
            if obj.get("wrapped"):
                result = {
                    "object_id": obj["object_id"], "type": obj["type"], "file_id": file_id,
                    "owner": obj["owner"], "name": obj["name"], "parent_object_id": None,
                    "wrapped": True, "parse_status": "skipped_wrapped",
                    "statements": {}, "control_flow_graph": {"nodes": [], "edges": []},
                    "parse_issues": [],
                }
            else:
                result = parse_object(obj, file_id)
                resolve_calls(result, obj["parent_object_id"], known, siblings, result["parse_issues"])
        except Exception as e:  # noqa: BLE001
            result = {
                "object_id": obj["object_id"], "type": obj["type"], "file_id": file_id,
                "parse_status": "failed", "error": str(e), "parse_issues": [],
                "statements": {},
            }
        out_name = result["object_id"].replace("::", "__").replace("/", "_") + ".json"
        (raw_dir / out_name).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        objects_index[result["object_id"]] = f"raw_structure/{out_name}"

        stats["objects_parsed"] += 1
        if obj["parent_object_id"]:
            stats["package_members"] += 1
        stmts = result.get("statements", {})
        stats["statements_extracted"] += len(stmts)
        stats["dynamic_sql_blocks"] += sum(1 for s in stmts.values() if s.get("requires_manual_review"))
        all_issues.extend(result.get("parse_issues", []))

    stats["unresolved_calls"] = sum(1 for i in all_issues if i.get("type") == "unresolved_reference")

    manifest = {
        "pipeline_stage": "2_parser", "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {"inventory_run_version": inv_run_version},
        "files_parsed": len(parse_worthy), "files_passthrough": len(passthrough), "files_skipped": len(skipped),
        "stats": stats,
        "object_index": objects_index,
        "issues": all_issues,
    }
    (run_dir / "parser_artifact.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        run_meta = {
            "stage": "2_parser", "run_version": run_version, "status": "success",
            "generated_at": manifest["generated_at"],
            "upstream": {"inventory_run_version": inv_run_version},
            "stats_summary": stats,
        }
        (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2, ensure_ascii=False), encoding="utf-8")
        latest_pointer = {"run_version": run_version, "path": f"{run_version}/parser_artifact.json",
                           "updated_at": manifest["generated_at"]}
        (Path(args.output_root) / "latest.json").write_text(json.dumps(latest_pointer, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== PL/SQL Parser Agent Complete ===")
    print(f"Objects parsed        : {stats['objects_parsed']}")
    print(f"  Package members      : {stats['package_members']}")
    print(f"Statements extracted   : {stats['statements_extracted']}")
    print(f"Dynamic SQL blocks     : {stats['dynamic_sql_blocks']}   (flagged for review)")
    print(f"Unresolved calls       : {stats['unresolved_calls']}")
    print(f"Parse errors           : {stats['parse_errors']}")
    print(f"Output                 : {run_dir / 'parser_artifact.json'}")
    print("=====================================")


if __name__ == "__main__":
    main()
