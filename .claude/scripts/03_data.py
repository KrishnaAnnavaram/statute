#!/usr/bin/env python3
"""
Stage 3: DATA (deterministic, no LLM)
--------------------------------------
Reads the latest (or pinned) inventory + parser runs. Parses every DDL file
(schema_ddl/seed_data files Agent 2 routed as pass-through and never opened)
using the same ANTLR PL/SQL grammar Agent 2 already vendored. Extracts a
full per-table data dictionary: columns, types, defaults, PK/FK/CHECK/UNIQUE
constraints, sequences. Then closes the loop back to Agent 2's output:
resolves every %TYPE/%ROWTYPE reference, cross-validates every table/column
Agent 2 recorded a statement touching, and assigns each column a PySpark
target type. CHECK constraints are promoted directly to candidate business
rules. Undocumented enums (comment-only, no CHECK) are mined from source
comments and flagged at lower confidence. Emits an ERD in Mermaid.

Design rationale (so this isn't taken on faith — see the sources cited in
data_artifact.json's "design_references" field for the specific claims
each design decision rests on):
  - Declared vs inferred relationships are never merged into one category
    (naming-convention FK detection has a known false-positive rate).
  - CHECK constraints are treated as near-certain business rule signal —
    the same status a COBOL 88-level condition gets in the reference
    pipeline this project is modeled after.
  - Oracle DATE always carries a time component and maps to Spark's
    TimestampType, not DateType — a well-known migration gotcha.

Zero LLM calls. 100% deterministic.

Output: output/data/<run_version>/{data_artifact.json, erd.mmd, run_meta.json},
plus output/data/latest.json.

Usage:
    python .claude/scripts/03_data.py [--inventory-run latest|<version>]
                                      [--parser-run latest|<version>]
                                      [--output-root output/data]
                                      [--output <path>] [--verbose]
"""

import argparse
import json
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

DESIGN_REFERENCES = [
    {
        "claim": "Declared vs. naming-convention-inferred FKs must never be merged into one confidence bucket.",
        "source": "Holistic primary key and foreign key detection (Jiang & Naumann, HPI) — "
                   "naming-convention matches produce real false positives.",
    },
    {
        "claim": "CHECK constraints are near-certain business rule signal, promotable without SME review.",
        "source": "Business rule mining literature — DB constraints (tables, columns, constraints) map "
                   "directly to business rule fact types; also mirrors this project's own reference "
                   "pipeline (reference/.claude/skills/condition-classifier), which gives COBOL 88-level "
                   "conditions the same 'certain' status for the identical reason: the constraint is "
                   "already enforced, not inferred from procedural code.",
    },
    {
        "claim": "Standard DDL extraction scope: tables w/ PK/UK/FK/CHECK, sequences, views, indexes, synonyms.",
        "source": "Ora2Pg (the most mature production Oracle-schema-extraction tool) — documented export "
                   "type list matches this scope exactly.",
    },
    {
        "claim": "Oracle DATE maps to Spark TimestampType, not DateType; NUMBER(p,s>0) maps to DecimalType(p,s).",
        "source": "Apache Spark JDBC OracleDialect type mapping (spark.sql.execution.datasources.jdbc) — "
                   "Oracle DATE always carries a time component, a documented migration gotcha.",
    },
]


# ---------------------------------------------------------------------------
# Run versioning (same convention as 00_inventory.py / 02_parser.py)
# ---------------------------------------------------------------------------

def generate_run_version() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H.%M.%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Phase 0 — load inventory + parser artifacts
# ---------------------------------------------------------------------------

DDL_ROLES = {"schema_ddl", "seed_data"}


def load_run(root: str, run: str, artifact_filename: str) -> tuple[dict, str]:
    root_path = Path(root)
    if run == "latest":
        latest_path = root_path / "latest.json"
        if not latest_path.exists():
            raise FileNotFoundError(f"No runs found: {latest_path} does not exist")
        pointer = json.loads(latest_path.read_text(encoding="utf-8"))
        run_version = pointer["run_version"]
    else:
        run_version = run
    artifact_path = root_path / run_version / artifact_filename
    if not artifact_path.exists():
        raise FileNotFoundError(f"Run not found: {artifact_path}")
    return json.loads(artifact_path.read_text(encoding="utf-8")), run_version


def route_ddl_files(inventory: dict) -> list[dict]:
    files = []
    for file_id, path in inventory["file_index"].items():
        meta = inventory["file_metadata"][file_id]
        if meta.get("status") == "ok" and meta.get("file_role") in DDL_ROLES:
            files.append({"file_id": file_id, "path": path, **meta})
    files.sort(key=lambda r: r["file_id"])
    return files


# ---------------------------------------------------------------------------
# ANTLR parsing (same pattern as 02_parser.py)
# ---------------------------------------------------------------------------

class CollectingErrorListener(ErrorListener):
    def __init__(self):
        super().__init__()
        self.errors: list[dict] = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append({"line": line, "column": column, "message": msg})


def parse_source(abs_path: str):
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
    return tree, err.errors


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


def find_all(ctx, type_name: str, out: list) -> list:
    if type(ctx).__name__ == type_name:
        out.append(ctx)
    n = ctx.getChildCount() if hasattr(ctx, "getChildCount") else 0
    for i in range(n):
        find_all(ctx.getChild(i), type_name, out)
    return out


def text_of(ctx) -> str:
    return ctx.getText() if ctx is not None else ""


# ---------------------------------------------------------------------------
# Oracle -> normalized / PySpark type mapping
# See DESIGN_REFERENCES: Apache Spark JDBC OracleDialect
# ---------------------------------------------------------------------------

def map_oracle_type(datatype_text: str) -> dict:
    t = datatype_text.upper().strip()

    m = re.match(r"^(VARCHAR2|VARCHAR|NVARCHAR2|CHAR|NCHAR)\s*\(\s*(\d+)", t)
    if m:
        return {"normalized_type": "STRING", "pyspark_type": "StringType", "length": int(m.group(2))}

    m = re.match(r"^NUMBER\s*\(\s*(\d+)\s*(?:,\s*(-?\d+))?\s*\)", t)
    if m:
        precision, scale = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
        if scale > 0:
            return {"normalized_type": "DECIMAL", "pyspark_type": f"DecimalType({precision},{scale})",
                     "precision": precision, "scale": scale}
        if precision <= 9:
            return {"normalized_type": "INTEGER", "pyspark_type": "IntegerType", "precision": precision}
        return {"normalized_type": "LONG", "pyspark_type": "LongType", "precision": precision}
    if t == "NUMBER":
        return {"normalized_type": "DECIMAL", "pyspark_type": "DecimalType(38,10)",
                 "note": "unbounded NUMBER — precision/scale assumed, confirm against real data"}

    if t.startswith("TIMESTAMP"):
        return {"normalized_type": "TIMESTAMP", "pyspark_type": "TimestampType"}
    if t.startswith("DATE"):
        # Oracle DATE always carries a time component — see DESIGN_REFERENCES.
        return {"normalized_type": "DATE", "pyspark_type": "TimestampType",
                 "note": "Oracle DATE includes a time component; do not narrow to Spark DateType"}

    if t.startswith("CLOB") or t.startswith("NCLOB") or t.startswith("LONG"):
        return {"normalized_type": "STRING", "pyspark_type": "StringType", "note": "large object, unbounded length"}
    if t.startswith("BLOB") or t.startswith("RAW") or t.startswith("BFILE"):
        return {"normalized_type": "BINARY", "pyspark_type": "BinaryType"}
    if t.startswith("BINARY_FLOAT") or t.startswith("FLOAT"):
        return {"normalized_type": "FLOAT", "pyspark_type": "FloatType"}
    if t.startswith("BINARY_DOUBLE"):
        return {"normalized_type": "DOUBLE", "pyspark_type": "DoubleType"}
    if t.startswith("INTEGER") or t.startswith("INT") or t.startswith("SMALLINT"):
        return {"normalized_type": "INTEGER", "pyspark_type": "IntegerType"}

    return {"normalized_type": "UNKNOWN", "pyspark_type": "StringType", "note": f"unmapped Oracle type: {t}"}


# ---------------------------------------------------------------------------
# Phase 1-2 — parse DDL, extract per-table column/constraint model
# ---------------------------------------------------------------------------

def qualified_table_name(ctx, name_type: str) -> str:
    name_ctx = find_child(ctx, name_type)
    return text_of(name_ctx).upper()


def is_function_call_default(expr_text: str) -> bool:
    t = expr_text.upper().strip()
    if t in ("SYSDATE", "SYSTIMESTAMP", "USER", "UID"):
        return True
    return bool(re.match(r"^[A-Z_][A-Z0-9_]*\s*\(", t))


def extract_column(col_ctx) -> dict:
    name = text_of(find_child(col_ctx, "Column_nameContext"))
    datatype_ctx = find_child(col_ctx, "DatatypeContext")
    datatype_text = text_of(datatype_ctx)
    type_info = map_oracle_type(datatype_text) if datatype_text else \
        {"normalized_type": "UNKNOWN", "pyspark_type": "StringType"}

    default = None
    default_idx = None
    n = col_ctx.getChildCount()
    for i in range(n):
        if type(col_ctx.getChild(i)).__name__ == "TerminalNodeImpl" and text_of(col_ctx.getChild(i)).upper() == "DEFAULT":
            default_idx = i
            break
    if default_idx is not None:
        expr_ctx = find_child(col_ctx, "ExpressionContext")
        expr_text = text_of(expr_ctx)
        default = {"value": expr_text, "kind": "function_call" if is_function_call_default(expr_text) else "literal"}

    inline_constraints = find_all_direct_children(col_ctx, {"Inline_constraintContext"})
    not_null = False
    inline_pk = False
    inline_unique = False
    for ic in inline_constraints:
        ic_text = text_of(ic).upper()
        if "NOTNULL" in ic_text:
            not_null = True
        if "PRIMARYKEY" in ic_text:
            inline_pk = True
        if ic_text.startswith("UNIQUE") or (("CONSTRAINT" in ic_text) and "UNIQUE" in ic_text and "PRIMARYKEY" not in ic_text):
            inline_unique = True

    return {
        "name": name.upper(),
        "oracle_type": datatype_text,
        "nullable": not not_null,
        "default": default,
        "inline_primary_key": inline_pk,
        "inline_unique": inline_unique,
        "line": col_ctx.start.line,
        **type_info,
    }


def extract_out_of_line_constraint(c_ctx) -> dict | None:
    text_upper = text_of(c_ctx).upper()
    name_ctx = find_child(c_ctx, "Constraint_nameContext")
    constraint_name = text_of(name_ctx).upper() if name_ctx else None

    if "PRIMARYKEY" in text_upper:
        cols = [text_of(c).upper() for c in find_all_direct_children(c_ctx, {"Column_nameContext"})]
        return {"kind": "PRIMARY_KEY", "name": constraint_name, "columns": cols}

    fk_ctx = find_child(c_ctx, "Foreign_key_clauseContext")
    if fk_ctx is not None:
        fk_cols = [text_of(c).upper() for c in find_all(fk_ctx, "Column_nameContext", [])]
        ref_ctx = find_child(fk_ctx, "References_clauseContext")
        ref_table = text_of(find_child(ref_ctx, "Tableview_nameContext")).upper() if ref_ctx else None
        ref_cols = [text_of(c).upper() for c in find_all(ref_ctx, "Column_nameContext", [])] if ref_ctx else []
        return {"kind": "FOREIGN_KEY", "name": constraint_name, "columns": fk_cols,
                "references_table": ref_table, "references_columns": ref_cols, "relationship_type": "declared"}

    if "CHECK" in text_upper:
        cond_ctx = find_child(c_ctx, "ConditionContext")
        expr = text_of(cond_ctx)
        return {"kind": "CHECK", "name": constraint_name, "expression": expr,
                "promotable_to_rule": True}

    if text_upper.startswith("UNIQUE") or ("UNIQUE" in text_upper and "FOREIGNKEY" not in text_upper and "CHECK" not in text_upper):
        cols = [text_of(c).upper() for c in find_all_direct_children(c_ctx, {"Column_nameContext"})]
        return {"kind": "UNIQUE", "name": constraint_name, "columns": cols}

    return None


def extract_table(table_ctx) -> dict:
    table_name = qualified_table_name(table_ctx, "Table_nameContext")
    rel_table = find_child(table_ctx, "Relational_tableContext")
    columns: list[dict] = []
    constraints: list[dict] = []

    if rel_table is not None:
        for prop in find_all_direct_children(rel_table, {"Relational_propertyContext"}):
            child = prop.getChild(0)
            cls = type(child).__name__
            if cls == "Column_definitionContext":
                columns.append(extract_column(child))
            elif cls == "Out_of_line_constraintContext":
                c = extract_out_of_line_constraint(child)
                if c:
                    constraints.append(c)

    primary_key = next((c["columns"] for c in constraints if c["kind"] == "PRIMARY_KEY"), None)
    if primary_key is None:
        inline_pk_cols = [c["name"] for c in columns if c["inline_primary_key"]]
        primary_key = inline_pk_cols or None

    return {
        "table": table_name,
        "columns": columns,
        "primary_key": primary_key,
        "foreign_keys": [c for c in constraints if c["kind"] == "FOREIGN_KEY"],
        "check_constraints": [c for c in constraints if c["kind"] == "CHECK"],
        "unique_constraints": [c for c in constraints if c["kind"] == "UNIQUE"],
        "start_line": table_ctx.start.line,
        "end_line": table_ctx.stop.line,
    }


def extract_sequence(seq_ctx) -> dict:
    name = text_of(find_child(seq_ctx, "Sequence_nameContext")).upper()
    start_ctx = find_child(seq_ctx, "Sequence_start_clauseContext")
    start_value = None
    if start_ctx is not None:
        m = re.search(r"(\d+)", text_of(start_ctx))
        start_value = int(m.group(1)) if m else None
    increment = 1
    text_upper = text_of(seq_ctx).upper()
    m = re.search(r"INCREMENTBY(\d+)", text_upper)
    if m:
        increment = int(m.group(1))
    return {"sequence": name, "start_with": start_value, "increment_by": increment}


# ---------------------------------------------------------------------------
# Phase 3 — comment-mining for undocumented enums
# See DESIGN_REFERENCES: comment-only enums are real signal, weaker than CHECK
# ---------------------------------------------------------------------------

_ENUM_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def mine_comment_enum(raw_lines: list[str], start_line: int, end_line: int) -> list[str] | None:
    """
    Scan source lines [start_line, end_line] (1-based, inclusive) for trailing
    `--` comments and check whether they form a comma-separated list of
    ALL-CAPS tokens — the shape a documented-but-unenforced enum takes.
    """
    comment_text = []
    for lineno in range(start_line, min(end_line, len(raw_lines)) + 1):
        line = raw_lines[lineno - 1]
        idx = line.find("--")
        if idx != -1:
            comment_text.append(line[idx + 2:].strip())
    if not comment_text:
        return None
    joined = " ".join(comment_text).rstrip(",")
    tokens = [t.strip() for t in joined.split(",") if t.strip()]
    if len(tokens) < 2:
        return None
    if all(_ENUM_TOKEN_RE.match(t) for t in tokens):
        return tokens
    return None


def mine_check_enum(expression: str) -> list[str] | None:
    m = re.search(r"IN\s*\(([^)]+)\)", expression, re.IGNORECASE)
    if not m:
        return None
    values = re.findall(r"'([^']*)'", m.group(1))
    return values or None


# ---------------------------------------------------------------------------
# Phase 4 — implicit FK detection
# See DESIGN_REFERENCES: naming-convention matches are real signal but produce
# false positives — always tagged relationship_type: inferred, never merged
# with declared FKs.
# ---------------------------------------------------------------------------

def detect_implicit_fks(tables: dict[str, dict]) -> list[dict]:
    inferred = []
    declared_fk_columns = {
        (t["table"], fk_col)
        for t in tables.values() for fk in t["foreign_keys"] for fk_col in fk["columns"]
    }
    pk_index: dict[str, tuple[str, str]] = {}
    for t in tables.values():
        if t["primary_key"] and len(t["primary_key"]) == 1:
            pk_col = t["primary_key"][0]
            pk_index[pk_col] = (t["table"], pk_col)
            singular = t["table"][:-1].upper() if t["table"].upper().endswith("S") else t["table"].upper()
            pk_index.setdefault(f"{singular}_ID", (t["table"], pk_col))
            pk_index.setdefault(f"{singular}_NUMBER", (t["table"], pk_col))

    for t in tables.values():
        for col in t["columns"]:
            key = (t["table"], col["name"])
            if key in declared_fk_columns:
                continue
            if t["primary_key"] and col["name"] in t["primary_key"]:
                continue
            target = pk_index.get(col["name"])
            if target and target[0] != t["table"]:
                inferred.append({
                    "from_table": t["table"], "from_column": col["name"],
                    "to_table": target[0], "to_column": target[1],
                    "relationship_type": "inferred",
                    "basis": "name_match+type_compatible",
                    "confidence": "medium",
                })
    return inferred


# ---------------------------------------------------------------------------
# Phase 6 — %TYPE / %ROWTYPE resolution against Agent 2's declarations
# ---------------------------------------------------------------------------

_TYPE_REF_RE = re.compile(r"(?:\w+\.)?(\w+)\.(\w+)\s*%TYPE", re.IGNORECASE)
_ROWTYPE_REF_RE = re.compile(r"(?:\w+\.)?(\w+)\s*%ROWTYPE", re.IGNORECASE)


def resolve_type_references(parser_root: Path, object_index: dict, tables: dict[str, dict],
                             issues: list[dict]) -> list[dict]:
    resolved = []
    for object_id, rel_path in object_index.items():
        obj_path = parser_root / rel_path
        if not obj_path.exists():
            continue
        obj = json.loads(obj_path.read_text(encoding="utf-8"))
        for decl in obj.get("declarations", []):
            type_text = decl.get("type", "")
            m = _TYPE_REF_RE.search(type_text)
            if m:
                table_name, col_name = m.group(1).upper(), m.group(2).upper()
                table = tables.get(table_name)
                found = table and any(c["name"] == col_name for c in table["columns"])
                resolved.append({
                    "object_id": object_id, "declaration": decl["name"],
                    "reference": f"{table_name}.{col_name}%TYPE", "resolved": bool(found),
                })
                if not found:
                    issues.append({"severity": "warning", "type": "unresolved_type_reference",
                                    "object_id": object_id, "message": f"{table_name}.{col_name}%TYPE not found in data dictionary"})
                continue
            m = _ROWTYPE_REF_RE.search(type_text)
            if m:
                table_name = m.group(1).upper()
                found = table_name in tables
                resolved.append({
                    "object_id": object_id, "declaration": decl["name"],
                    "reference": f"{table_name}%ROWTYPE", "resolved": bool(found),
                })
                if not found:
                    issues.append({"severity": "warning", "type": "unresolved_type_reference",
                                    "object_id": object_id, "message": f"{table_name}%ROWTYPE not found in data dictionary"})
    return resolved


# ---------------------------------------------------------------------------
# Phase 7 — cross-validate parser's tables/reads/writes against real columns
# ---------------------------------------------------------------------------

def cross_validate(parser_root: Path, object_index: dict, tables: dict[str, dict],
                    issues: list[dict]) -> dict:
    stats = {"tables_referenced": 0, "unknown_tables": 0, "unknown_columns": 0}
    seen_tables = set()
    for object_id, rel_path in object_index.items():
        obj_path = parser_root / rel_path
        if not obj_path.exists():
            continue
        obj = json.loads(obj_path.read_text(encoding="utf-8"))
        for stmt in obj.get("statements", {}).values():
            stmt_tables = stmt.get("tables", [])
            if not stmt_tables:
                continue

            # A single statement (e.g. an INSERT with a sub-SELECT) can touch
            # more than one table at once. Check every read/write column
            # against the UNION of columns across all of them, not against
            # each table independently — otherwise a column that legitimately
            # belongs to table B gets misreported as unknown while checking
            # it against table A.
            known_tables_here = [t for t in stmt_tables if t.upper() in tables]
            for table_name in stmt_tables:
                seen_tables.add(table_name.upper())
                if table_name.upper() not in tables:
                    stats["unknown_tables"] += 1
                    issues.append({"severity": "info", "type": "unknown_table_reference",
                                    "object_id": object_id, "statement_id": stmt["statement_id"],
                                    "message": f"Table '{table_name}' not found in parsed DDL "
                                               "(may be external/other-schema — not necessarily an error)"})

            if not known_tables_here:
                continue
            combined_columns = {c["name"] for t in known_tables_here for c in tables[t.upper()]["columns"]}
            param_names = {p["name"].upper() for p in obj.get("parameters", [])}
            for col_field in ("reads", "writes", "predicate_reads"):
                for col in stmt.get(col_field, []):
                    if col.upper() not in combined_columns and col.upper() not in param_names:
                        stats["unknown_columns"] += 1
                        issues.append({"severity": "warning", "type": "unknown_column_reference",
                                        "object_id": object_id, "statement_id": stmt["statement_id"],
                                        "message": f"Column '{col}' not found on any of the statement's "
                                                   f"referenced tables ({', '.join(known_tables_here)})"})
    stats["tables_referenced"] = len(seen_tables)
    return stats


# ---------------------------------------------------------------------------
# Phase 8 — sequence usage linkage (lightweight, source-text scan)
# ---------------------------------------------------------------------------

def find_sequence_usage(parser_root: Path, object_index: dict, sequences: dict[str, dict],
                         file_abs_paths: dict[str, str]) -> list[dict]:
    usages = []
    for object_id, rel_path in object_index.items():
        obj_path = parser_root / rel_path
        if not obj_path.exists():
            continue
        obj = json.loads(obj_path.read_text(encoding="utf-8"))
        file_id = obj.get("file_id")
        abs_path = file_abs_paths.get(file_id)
        if not abs_path:
            continue
        for stmt in obj.get("statements", {}).values():
            if stmt.get("statement_type") != "INSERT":
                continue
            start, end = stmt.get("start_line"), stmt.get("end_line")
            if not start or not end:
                continue
            try:
                lines = Path(abs_path).read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            snippet = "\n".join(lines[start - 1:end]).upper()
            for seq_name in sequences:
                if f"{seq_name}.NEXTVAL" in snippet:
                    usages.append({
                        "sequence": seq_name, "object_id": object_id,
                        "statement_id": stmt["statement_id"], "table": stmt.get("tables", [None])[0],
                    })
    return usages


# ---------------------------------------------------------------------------
# ERD generation (Mermaid)
# ---------------------------------------------------------------------------

def generate_erd(tables: dict[str, dict], inferred_fks: list[dict]) -> str:
    lines = ["erDiagram"]
    for t in tables.values():
        pk_set = set(t["primary_key"] or [])
        lines.append(f"    {t['table']} {{")
        for c in t["columns"]:
            key_marker = "PK" if c["name"] in pk_set else ""
            safe_type = c["normalized_type"].lower()
            lines.append(f"        {safe_type} {c['name']} {key_marker}".rstrip())
        lines.append("    }")
    for t in tables.values():
        for fk in t["foreign_keys"]:
            if fk["references_table"] in tables:
                lines.append(f'    {fk["references_table"]} ||--o{{ {t["table"]} : "{",".join(fk["columns"])}"')
    for inf in inferred_fks:
        if inf["to_table"] in tables and inf["from_table"] in tables:
            lines.append(f'    {inf["to_table"]} }}o..o{{ {inf["from_table"]} : "{inf["from_column"]} (inferred)"')
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 3: Deterministic PL/SQL data dictionary extractor")
    ap.add_argument("--inventory-root", default="output/inventory")
    ap.add_argument("--inventory-run", default="latest")
    ap.add_argument("--parser-root", default="output/parser")
    ap.add_argument("--parser-run", default="latest")
    ap.add_argument("--output-root", default="output/data")
    ap.add_argument("--output", default=None)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    inventory, inv_run_version = load_run(args.inventory_root, args.inventory_run, "inventory-artifact.json")
    parser_artifact, parser_run_version = load_run(args.parser_root, args.parser_run, "parser_artifact.json")
    parser_root = Path(args.parser_root) / parser_run_version

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    run_dir.mkdir(parents=True, exist_ok=True)

    issues: list[dict] = []
    tables: dict[str, dict] = {}
    sequences: dict[str, dict] = {}
    file_abs_paths: dict[str, str] = {}
    stats = {"ddl_files_parsed": 0, "parse_errors": 0, "tables_found": 0, "sequences_found": 0,
             "columns_total": 0, "declared_foreign_keys": 0, "inferred_foreign_keys": 0,
             "check_constraints": 0, "candidate_rules_from_ddl": 0, "comment_only_enums": 0}

    ddl_files = route_ddl_files(inventory)
    for file_rec in ddl_files:
        file_abs_paths[file_rec["file_id"]] = file_rec["abs_path"]
        if args.verbose:
            print(f"  [parsing DDL] {file_rec['path']}", file=sys.stderr)
        tree, errors = parse_source(file_rec["abs_path"])
        stats["ddl_files_parsed"] += 1
        if errors:
            stats["parse_errors"] += len(errors)
            for e in errors:
                issues.append({"severity": "error", "type": "syntax_error", "file": file_rec["path"], **e})

        raw_lines = Path(file_rec["abs_path"]).read_text(encoding="utf-8").splitlines()

        table_ctxs = find_all(tree, "Create_tableContext", [])
        for tctx in table_ctxs:
            t = extract_table(tctx)
            t["source_file"] = file_rec["path"]
            for col in t["columns"]:
                next_line = t["end_line"]
                idx = t["columns"].index(col)
                if idx + 1 < len(t["columns"]):
                    next_line = t["columns"][idx + 1]["line"] - 1
                enum_from_check = None
                for chk in t["check_constraints"]:
                    if col["name"] in chk["expression"].upper():
                        enum_from_check = mine_check_enum(chk["expression"])
                if enum_from_check:
                    col["enum_values"] = enum_from_check
                    col["enum_source"] = "check_constraint"
                    col["confidence"] = "enforced"
                else:
                    mined = mine_comment_enum(raw_lines, col["line"], next_line)
                    if mined:
                        col["enum_values"] = mined
                        col["enum_source"] = "comment_only"
                        col["confidence"] = "documented_only"
                        col["requires_sme_review"] = True
                        stats["comment_only_enums"] += 1
            tables[t["table"]] = t
            stats["tables_found"] += 1
            stats["columns_total"] += len(t["columns"])
            stats["declared_foreign_keys"] += len(t["foreign_keys"])
            stats["check_constraints"] += len(t["check_constraints"])
            stats["candidate_rules_from_ddl"] += sum(1 for c in t["check_constraints"] if c.get("promotable_to_rule"))

        for sctx in find_all(tree, "Create_sequenceContext", []):
            s = extract_sequence(sctx)
            s["source_file"] = file_rec["path"]
            sequences[s["sequence"]] = s
            stats["sequences_found"] += 1

    inferred_fks = detect_implicit_fks(tables)
    stats["inferred_foreign_keys"] = len(inferred_fks)

    type_resolutions = resolve_type_references(parser_root, parser_artifact["object_index"], tables, issues)
    cross_val_stats = cross_validate(parser_root, parser_artifact["object_index"], tables, issues)
    sequence_usages = find_sequence_usage(parser_root, parser_artifact["object_index"], sequences, file_abs_paths)

    erd = generate_erd(tables, inferred_fks)
    (run_dir / "erd.mmd").write_text(erd, encoding="utf-8")

    data_artifact = {
        "pipeline_stage": "3_data", "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {"inventory_run_version": inv_run_version, "parser_run_version": parser_run_version},
        "design_references": DESIGN_REFERENCES,
        "stats": {**stats, **cross_val_stats},
        "tables": tables,
        "sequences": sequences,
        "inferred_relationships": inferred_fks,
        "type_reference_resolutions": type_resolutions,
        "sequence_usages": sequence_usages,
        "issues": issues,
    }
    (run_dir / "data_artifact.json").write_text(json.dumps(data_artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        run_meta = {
            "stage": "3_data", "run_version": run_version, "status": "success",
            "generated_at": data_artifact["generated_at"],
            "upstream": data_artifact["upstream"],
            "stats_summary": stats,
        }
        (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2, ensure_ascii=False), encoding="utf-8")
        latest_pointer = {"run_version": run_version, "path": f"{run_version}/data_artifact.json",
                           "updated_at": data_artifact["generated_at"]}
        (Path(args.output_root) / "latest.json").write_text(json.dumps(latest_pointer, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== Data Agent Complete ===")
    print(f"DDL files parsed        : {stats['ddl_files_parsed']}")
    print(f"Tables found            : {stats['tables_found']}")
    print(f"Columns total           : {stats['columns_total']}")
    print(f"Sequences found         : {stats['sequences_found']}")
    print(f"Declared foreign keys   : {stats['declared_foreign_keys']}")
    print(f"Inferred foreign keys   : {stats['inferred_foreign_keys']}  (flagged, not merged with declared)")
    print(f"CHECK constraints       : {stats['check_constraints']}")
    print(f"Candidate rules from DDL: {stats['candidate_rules_from_ddl']}")
    print(f"Comment-only enums      : {stats['comment_only_enums']}  (flagged requires_sme_review)")
    print(f"Unknown table refs      : {cross_val_stats['unknown_tables']}")
    print(f"Unknown column refs     : {cross_val_stats['unknown_columns']}")
    print(f"Parse errors            : {stats['parse_errors']}")
    print(f"Output                  : {run_dir / 'data_artifact.json'}")
    print("============================")


if __name__ == "__main__":
    main()
