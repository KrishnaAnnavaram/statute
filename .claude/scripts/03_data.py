#!/usr/bin/env python3
"""
Stage 3: DATA (deterministic, no LLM)
--------------------------------------
Reads the latest (or pinned) inventory + parser runs. Parses every DDL file
(schema_ddl/seed_data files Agent 2 routed as pass-through and never opened)
using the same ANTLR PL/SQL grammar Agent 2 already vendored, and builds the
complete physical data dictionary: tables, columns, constraints (with their
real Oracle enforcement state), views, indexes, sequences, synonyms,
partitioning, and schema comments.

Then closes the loop back to Agent 2's output: resolves every %TYPE/%ROWTYPE
reference, cross-validates every table/column Agent 2 recorded a statement
touching (resolving synonyms and views on the way), tracks which objects use
which column, and assigns each column a PySpark target type.

Business-rule candidates are harvested from FOUR distinct DDL sources, each
with an honest confidence level:
  - CHECK constraints        (only ENABLED+VALIDATED ones are 'enforced')
  - virtual column formulas  (a computed column IS a business calculation)
  - UNIQUE indexes/constraints (a de facto uniqueness rule)
  - view WHERE clauses       (a filter that defines a business subset)

Design rationale (never taken on faith — see design_references in the output
artifact for the specific source each decision rests on):
  - Oracle constraints carry an independent STATUS (ENABLED/DISABLED) and
    VALIDATED state. A DISABLED constraint is NOT being enforced and must
    never be presented as an active business rule.
  - Declared vs. naming-convention-inferred relationships are never merged.
  - Oracle DATE always carries a time component -> Spark TimestampType.
  - Schema comments (COMMENT ON) are free, human-authored business
    documentation and are core scope for any schema-documentation tool.

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

try:
    import sqlglot  # noqa: E402
    _HAVE_SQLGLOT = True
except ImportError:  # pragma: no cover - sqlglot is a hard dep of Agent 2
    _HAVE_SQLGLOT = False


DESIGN_REFERENCES = [
    {
        "claim": "Oracle constraints have an independent STATUS (ENABLED/DISABLED) and VALIDATED state; "
                 "a DISABLED constraint is not enforced and must never be reported as an active rule.",
        "source": "Oracle Database — Managing Integrity Constraints (ALL_CONSTRAINTS.STATUS / .VALIDATED). "
                  "ENABLE NOVALIDATE checks new rows only; DISABLE VALIDATE forbids modification but "
                  "does not enforce the predicate on write. Legacy schemas routinely leave constraints "
                  "DISABLEd after bulk loads.",
    },
    {
        "claim": "Declared vs. naming-convention-inferred FKs must never be merged into one confidence bucket.",
        "source": "Holistic primary key and foreign key detection (Jiang & Naumann, HPI) — "
                  "naming-convention matches produce real false positives.",
    },
    {
        "claim": "CHECK constraints are near-certain business rule signal when enforced.",
        "source": "Business rule mining literature — DB constraints map directly to business rule fact "
                  "types; mirrors this project's reference pipeline (condition-classifier), which gives "
                  "COBOL 88-level conditions the same status for the identical reason: the constraint is "
                  "already enforced by the platform, not inferred from procedural code.",
    },
    {
        "claim": "Schema comments (COMMENT ON TABLE/COLUMN) are core extraction scope, not an optional extra.",
        "source": "SchemaSpy — the standard open-source database-documentation tool treats table/column "
                  "comment extraction as baseline functionality, because it is human-authored business "
                  "documentation already present in the schema.",
    },
    {
        "claim": "DDL extraction scope: tables w/ PK/UK/FK/CHECK, sequences, views, indexes, synonyms.",
        "source": "Ora2Pg (the most mature production Oracle-schema-extraction tool) — documented export "
                  "type list defines the accepted scope for full schema extraction.",
    },
    {
        "claim": "Physical schema extraction is phase one of database reverse engineering; recovering "
                 "implicit/undeclared structure is a separate, explicitly lower-confidence activity.",
        "source": "Jean-Luc Hainaut, 'Introduction to Database Reverse Engineering' / 'Data Structure "
                  "Extraction in DBRE' — DBRE = data structure extraction followed by conceptualization.",
    },
    {
        "claim": "Oracle DATE maps to Spark TimestampType, not DateType; NUMBER(p,s>0) -> DecimalType(p,s).",
        "source": "Apache Spark JDBC OracleDialect type mapping — Oracle DATE always carries a time "
                  "component, a documented migration gotcha.",
    },
    {
        "claim": "Partitioning metadata is first-class input for a Spark/Parquet migration.",
        "source": "Apache Spark Parquet documentation — partition discovery and partition-key alignment "
                  "are explicit performance-critical migration decisions.",
    },
]


# ---------------------------------------------------------------------------
# Run versioning (same convention as 01_inventory.py / 02_parser.py)
# ---------------------------------------------------------------------------

def generate_run_version() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H.%M.%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Phase 0 — load inventory + parser artifacts, route DDL files
# ---------------------------------------------------------------------------

DDL_ROLES = {"schema_ddl", "seed_data"}

# Content hints that mean "this file contains DDL worth extracting", regardless
# of the coarse file_role Agent 1 assigned.
#
# Routing on file_role alone is not safe: a schema file containing a
# CREATE VIEW necessarily contains a SELECT, which makes Agent 1 classify the
# whole file as "mixed" rather than "schema_ddl" — and "mixed" is routed to
# Agent 2. Every table in that file would then be invisible to this agent.
# Agent 2 (procedural objects) and this agent (DDL objects) extract disjoint
# constructs, so both may legitimately read the same file.
DDL_CONTENT_HINTS = {
    "has_create_table", "has_create_view", "has_create_index",
    "has_create_sequence", "has_alter_table",
}


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
    """Select every readable file that either carries a DDL-ish role or shows
    a DDL content hint — see DDL_CONTENT_HINTS for why role alone is unsafe."""
    files = []
    for file_id, path in inventory["file_index"].items():
        meta = inventory["file_metadata"][file_id]
        if meta.get("status") != "ok":
            continue
        hints = set(meta.get("content_hints", {}))
        if meta.get("file_role") in DDL_ROLES or (hints & DDL_CONTENT_HINTS):
            files.append({"file_id": file_id, "path": path, **meta})
    files.sort(key=lambda r: r["file_id"])
    return files


# ---------------------------------------------------------------------------
# ANTLR parsing + tree helpers (same pattern as 02_parser.py)
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


def terminal_texts(ctx) -> list[str]:
    n = ctx.getChildCount() if hasattr(ctx, "getChildCount") else 0
    return [ctx.getChild(i).getText().upper() for i in range(n)
            if type(ctx.getChild(i)).__name__ == "TerminalNodeImpl"]


def text_of(ctx) -> str:
    return ctx.getText() if ctx is not None else ""


def original_text_of(ctx) -> str:
    """
    Source text WITH original whitespace preserved.

    ANTLR's getText() concatenates token text with no separators, producing
    e.g. "SELECTid,statusFROMprobe_t" — unparseable by sqlglot and unreadable
    by a human. Slicing the token stream between the context's start/stop
    tokens keeps the original spacing (whitespace is on the hidden channel,
    not discarded). Same technique 02_parser.py uses for DML statements.
    """
    if ctx is None:
        return ""
    try:
        return ctx.parser.getTokenStream().getText(ctx.start, ctx.stop)
    except Exception:  # noqa: BLE001 — fall back to the squashed form
        return ctx.getText()


_SOURCE_LINE_CACHE: dict[str, list[str]] = {}


def source_lines(abs_path: str) -> list[str]:
    """Cached per-file line reader — avoids re-reading a file from disk once
    per statement (the previous implementation re-read on every INSERT)."""
    if abs_path not in _SOURCE_LINE_CACHE:
        try:
            _SOURCE_LINE_CACHE[abs_path] = Path(abs_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            _SOURCE_LINE_CACHE[abs_path] = []
    return _SOURCE_LINE_CACHE[abs_path]


def bare_name(qualified: str) -> str:
    """ACCOUNTS / APP.ACCOUNTS / "APP"."ACCOUNTS" -> ACCOUNTS."""
    return qualified.replace('"', "").split(".")[-1].upper()


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
    if t.startswith("INTERVAL"):
        return {"normalized_type": "INTERVAL", "pyspark_type": "StringType",
                "note": "Spark has no direct Oracle INTERVAL equivalent; carried as string"}
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
    if t.startswith("ROWID") or t.startswith("UROWID"):
        return {"normalized_type": "STRING", "pyspark_type": "StringType", "note": "Oracle physical row address"}
    if t.startswith("XMLTYPE"):
        return {"normalized_type": "STRING", "pyspark_type": "StringType", "note": "XMLType carried as string"}

    return {"normalized_type": "UNKNOWN", "pyspark_type": "StringType", "note": f"unmapped Oracle type: {t}"}


# ---------------------------------------------------------------------------
# Phase 1 — constraint enforcement state
#
# This is the single most important correctness feature in this agent. Oracle
# tracks STATUS (ENABLED/DISABLED) and VALIDATED independently. A constraint
# that exists in the DDL is NOT necessarily being enforced. See
# DESIGN_REFERENCES for the Oracle documentation this models.
# ---------------------------------------------------------------------------

def parse_constraint_state(c_ctx) -> dict:
    """
    Read the optional constraint_state clause. Oracle's defaults when the
    clause is absent are ENABLE VALIDATE — i.e. fully enforced — so absence
    is meaningful and must not be reported as 'unknown'.
    """
    state = {
        "status": "ENABLED",          # Oracle default
        "validated": "VALIDATED",     # Oracle default
        "deferrable": False,
        "rely": False,
        "explicitly_stated": False,
    }
    st_ctx = find_child(c_ctx, "Constraint_stateContext")
    if st_ctx is None:
        return state

    txt = text_of(st_ctx).upper()
    state["explicitly_stated"] = True
    if "DISABLE" in txt:
        state["status"] = "DISABLED"
    if "NOVALIDATE" in txt:
        state["validated"] = "NOT_VALIDATED"
    elif "VALIDATE" in txt:
        state["validated"] = "VALIDATED"
    if "NOTDEFERRABLE" in txt:
        state["deferrable"] = False
    elif "DEFERRABLE" in txt:
        state["deferrable"] = True
    if "NORELY" in txt:
        state["rely"] = False
    elif "RELY" in txt:
        state["rely"] = True
    return state


def enforcement_summary(state: dict) -> tuple[bool, str, str]:
    """
    Returns (is_enforced, confidence, human_explanation).

    Only ENABLED + VALIDATED means "this predicate is true of all data, and
    will stay true". Anything else is a materially weaker claim and the BRD
    must say so rather than presenting it as an active rule.
    """
    if state["status"] == "DISABLED":
        return (False, "not_enforced",
                "Constraint is DISABLED — Oracle is not enforcing it. It documents intent only; "
                "existing and new data may violate it.")
    if state["validated"] == "NOT_VALIDATED":
        return (True, "enforced_new_data_only",
                "Constraint is ENABLED NOVALIDATE — enforced for new and modified rows, but "
                "pre-existing data was never checked and may violate it.")
    return (True, "enforced",
            "Constraint is ENABLED and VALIDATED — enforced by the database for all data.")


# ---------------------------------------------------------------------------
# Phase 2 — column extraction (incl. IDENTITY and virtual/computed columns)
# ---------------------------------------------------------------------------

def is_function_call_default(expr_text: str) -> bool:
    t = expr_text.upper().strip()
    if t in ("SYSDATE", "SYSTIMESTAMP", "USER", "UID", "CURRENT_DATE", "CURRENT_TIMESTAMP"):
        return True
    return bool(re.match(r"^[A-Z_][A-Z0-9_]*\s*\(", t))


def parse_identity_clause(id_ctx) -> dict:
    """GENERATED [ALWAYS|BY DEFAULT [ON NULL]] AS IDENTITY [(options)]."""
    txt = text_of(id_ctx).upper()
    generation = "ALWAYS" if "ALWAYS" in txt else ("BY_DEFAULT" if "BYDEFAULT" in txt else "ALWAYS")
    info = {"is_identity": True, "identity_generation": generation}
    m = re.search(r"STARTWITH(\d+)", txt)
    if m:
        info["identity_start_with"] = int(m.group(1))
    m = re.search(r"INCREMENTBY(\d+)", txt)
    if m:
        info["identity_increment_by"] = int(m.group(1))
    return info


def extract_column(col_ctx) -> dict:
    name = text_of(find_child(col_ctx, "Column_nameContext"))
    datatype_ctx = find_child(col_ctx, "DatatypeContext")
    datatype_text = text_of(datatype_ctx)
    type_info = map_oracle_type(datatype_text) if datatype_text else \
        {"normalized_type": "UNKNOWN", "pyspark_type": "StringType"}

    # DEFAULT <expr> and IDENTITY are mutually exclusive alternatives in the
    # grammar's column_definition rule — check for both, not just DEFAULT.
    default = None
    has_default_kw = any(
        type(col_ctx.getChild(i)).__name__ == "TerminalNodeImpl"
        and text_of(col_ctx.getChild(i)).upper() == "DEFAULT"
        for i in range(col_ctx.getChildCount())
    )
    if has_default_kw:
        expr_text = text_of(find_child(col_ctx, "ExpressionContext"))
        default = {"value": expr_text,
                   "kind": "function_call" if is_function_call_default(expr_text) else "literal"}

    identity_info: dict = {"is_identity": False}
    id_ctx = find_child(col_ctx, "Identity_clauseContext")
    if id_ctx is not None:
        identity_info = parse_identity_clause(id_ctx)

    inline_constraints = find_all_direct_children(col_ctx, {"Inline_constraintContext"})
    not_null = False
    inline_pk = False
    inline_unique = False
    inline_check = None
    for ic in inline_constraints:
        ic_text = text_of(ic).upper()
        if "NOTNULL" in ic_text:
            not_null = True
        if "PRIMARYKEY" in ic_text:
            inline_pk = True
            not_null = True  # an Oracle PK column is implicitly NOT NULL
        if "UNIQUE" in ic_text and "PRIMARYKEY" not in ic_text:
            inline_unique = True
        if "CHECK" in ic_text:
            cond = find_child(ic, "Check_constraintContext") or ic
            inline_check = text_of(find_child(cond, "ConditionContext")) or ic_text

    return {
        "name": name.upper(),
        "oracle_type": datatype_text,
        "nullable": not not_null,
        "default": default,
        "inline_primary_key": inline_pk,
        "inline_unique": inline_unique,
        "inline_check": inline_check,
        "is_virtual": False,
        "line": col_ctx.start.line,
        **identity_info,
        **type_info,
    }


def extract_virtual_column(vc_ctx) -> dict:
    """
    A virtual (computed) column. Previously these were silently dropped —
    they matched neither the column nor the constraint branch. A computed
    column is definitionally a business calculation and is harvested as a
    rule candidate.
    """
    name = text_of(find_child(vc_ctx, "Column_nameContext"))
    datatype_text = text_of(find_child(vc_ctx, "DatatypeContext"))
    type_info = map_oracle_type(datatype_text) if datatype_text else \
        {"normalized_type": "UNKNOWN", "pyspark_type": "StringType"}

    expr_ctx = find_child(vc_ctx, "Virtual_column_expressionContext")
    raw_expr = text_of(expr_ctx)
    # Strip the leading GENERATED [ALWAYS] AS wrapper to leave the formula.
    formula = re.sub(r"^GENERATED(ALWAYS)?AS", "", raw_expr, flags=re.IGNORECASE).strip()
    if formula.startswith("(") and formula.endswith(")"):
        formula = formula[1:-1]

    return {
        "name": name.upper(),
        "oracle_type": datatype_text,
        "nullable": True,
        "default": None,
        "inline_primary_key": False,
        "inline_unique": False,
        "inline_check": None,
        "is_virtual": True,
        "generation_expression": formula,
        "is_identity": False,
        "line": vc_ctx.start.line,
        **type_info,
    }


# ---------------------------------------------------------------------------
# Phase 3 — constraint extraction (incl. enforcement state and ON DELETE)
# ---------------------------------------------------------------------------

_ON_DELETE_RE = re.compile(r"ONDELETE(CASCADE|SETNULL)", re.IGNORECASE)


def extract_on_delete(fk_ctx) -> str:
    """
    The grammar allows ON DELETE in two places: absorbed into
    references_clause, or as a trailing on_delete_clause. Check the whole FK
    subtree text so either shape is caught.
    """
    m = _ON_DELETE_RE.search(text_of(fk_ctx))
    if not m:
        return "NO_ACTION"
    return "CASCADE" if m.group(1).upper() == "CASCADE" else "SET_NULL"


def extract_out_of_line_constraint(c_ctx) -> dict | None:
    text_upper = text_of(c_ctx).upper()
    name_ctx = find_child(c_ctx, "Constraint_nameContext")
    constraint_name = text_of(name_ctx).upper() if name_ctx else None
    state = parse_constraint_state(c_ctx)
    is_enforced, confidence, explanation = enforcement_summary(state)
    base = {
        "name": constraint_name,
        "enforcement": {**state, "is_enforced": is_enforced,
                        "confidence": confidence, "explanation": explanation},
    }

    if "PRIMARYKEY" in text_upper:
        cols = [text_of(c).upper() for c in find_all_direct_children(c_ctx, {"Column_nameContext"})]
        return {**base, "kind": "PRIMARY_KEY", "columns": cols}

    fk_ctx = find_child(c_ctx, "Foreign_key_clauseContext")
    if fk_ctx is not None:
        fk_cols = [text_of(c).upper() for c in find_all(find_child(fk_ctx, "Paren_column_listContext") or fk_ctx,
                                                        "Column_nameContext", [])]
        ref_ctx = find_child(fk_ctx, "References_clauseContext")
        ref_table = bare_name(text_of(find_child(ref_ctx, "Tableview_nameContext"))) if ref_ctx else None
        ref_cols = [text_of(c).upper() for c in find_all(ref_ctx, "Column_nameContext", [])] if ref_ctx else []
        return {**base, "kind": "FOREIGN_KEY", "columns": fk_cols,
                "references_table": ref_table, "references_columns": ref_cols,
                "on_delete": extract_on_delete(fk_ctx),
                "relationship_type": "declared"}

    if "CHECK" in text_upper:
        cond_ctx = find_child(c_ctx, "ConditionContext")
        expr = text_of(cond_ctx)
        return {**base, "kind": "CHECK", "expression": expr,
                # Only an actually-enforced constraint may be promoted to a
                # confirmed business rule. A DISABLED one still appears in the
                # artifact (and surfaces as a gap), but must not be presented
                # downstream as something the system guarantees.
                "promotable_to_rule": is_enforced}

    if "UNIQUE" in text_upper and "FOREIGNKEY" not in text_upper and "CHECK" not in text_upper:
        cols = [text_of(c).upper() for c in find_all_direct_children(c_ctx, {"Column_nameContext"})]
        return {**base, "kind": "UNIQUE", "columns": cols}

    return None


# ---------------------------------------------------------------------------
# Phase 4 — table extraction (incl. GTT, partitioning, virtual columns)
# ---------------------------------------------------------------------------

_PARTITION_STRATEGY = {
    "Range_partitionsContext": "RANGE",
    "List_partitionsContext": "LIST",
    "Hash_partitionsContext": "HASH",
    "Composite_range_partitionsContext": "COMPOSITE_RANGE",
    "Composite_list_partitionsContext": "COMPOSITE_LIST",
    "Composite_hash_partitionsContext": "COMPOSITE_HASH",
    "Reference_partitioningContext": "REFERENCE",
    "System_partitioningContext": "SYSTEM",
}


def extract_partitioning(table_ctx) -> dict | None:
    """
    Partition strategy + key columns. First-class input for a Spark/Parquet
    migration (partition-key alignment is a documented performance decision).
    """
    parts = find_all(table_ctx, "Table_partitioning_clausesContext", [])
    if not parts:
        return None
    inner = parts[0].getChild(0)
    strategy = _PARTITION_STRATEGY.get(type(inner).__name__, "UNKNOWN")
    key_columns = [text_of(c).upper() for c in find_all_direct_children(inner, {"Column_nameContext"})]
    partition_names = [text_of(p).upper() for p in find_all(inner, "Partition_nameContext", [])]
    return {
        "strategy": strategy,
        "key_columns": key_columns,
        "partition_count": len(partition_names),
        "partition_names": partition_names,
    }


def extract_table(table_ctx) -> dict:
    table_name = bare_name(text_of(find_child(table_ctx, "Table_nameContext")))
    rel_table = find_child(table_ctx, "Relational_tableContext")
    columns: list[dict] = []
    constraints: list[dict] = []

    if rel_table is not None:
        for prop in find_all_direct_children(rel_table, {"Relational_propertyContext"}):
            child = prop.getChild(0)
            cls = type(child).__name__
            if cls == "Column_definitionContext":
                columns.append(extract_column(child))
            elif cls == "Virtual_column_definitionContext":
                columns.append(extract_virtual_column(child))
            elif cls == "Out_of_line_constraintContext":
                c = extract_out_of_line_constraint(child)
                if c:
                    constraints.append(c)
            # Any other relational_property (period_definition,
            # supplemental_logging_props, out_of_line_ref_constraint) is
            # structural/physical only and carries no business semantics.

    primary_key = next((c["columns"] for c in constraints if c["kind"] == "PRIMARY_KEY"), None)
    if primary_key is None:
        inline_pk_cols = [c["name"] for c in columns if c["inline_primary_key"]]
        primary_key = inline_pk_cols or None

    header_terminals = terminal_texts(table_ctx)
    is_temporary = "TEMPORARY" in header_terminals
    full_text = text_of(table_ctx).upper()
    on_commit = None
    if is_temporary:
        on_commit = "DELETE_ROWS" if "ONCOMMITDELETEROWS" in full_text else (
            "PRESERVE_ROWS" if "ONCOMMITPRESERVEROWS" in full_text else None)

    return {
        "table": table_name,
        "columns": columns,
        "primary_key": primary_key,
        "foreign_keys": [c for c in constraints if c["kind"] == "FOREIGN_KEY"],
        "check_constraints": [c for c in constraints if c["kind"] == "CHECK"],
        "unique_constraints": [c for c in constraints if c["kind"] == "UNIQUE"],
        "temporary": is_temporary,
        "temporary_scope": on_commit,
        "partitioning": extract_partitioning(table_ctx),
        "comment": None,          # filled in by the COMMENT ON pass
        "start_line": table_ctx.start.line,
        "end_line": table_ctx.stop.line,
    }


# ---------------------------------------------------------------------------
# Phase 5 — views, indexes, synonyms, sequences, comments
# ---------------------------------------------------------------------------

def extract_view(view_ctx) -> dict:
    name_ctx = find_child(view_ctx, "Id_expressionContext")
    schema_ctx = find_child(view_ctx, "Schema_nameContext")
    select_ctx = find_child(view_ctx, "Select_only_statementContext")
    # Must preserve original whitespace — sqlglot cannot parse ANTLR's
    # squashed getText() output.
    select_text = original_text_of(select_ctx)

    referenced_tables: list[str] = []
    where_clause = None
    if _HAVE_SQLGLOT and select_text:
        try:
            ast = sqlglot.parse_one(select_text, dialect="oracle")
            referenced_tables = sorted({t.name.upper() for t in ast.find_all(sqlglot.exp.Table) if t.name})
            where_node = ast.args.get("where")
            if where_node is not None:
                where_clause = where_node.sql(dialect="oracle")
        except Exception:  # noqa: BLE001 — a view we can't analyse is still recorded
            referenced_tables = sorted({bare_name(text_of(t))
                                        for t in find_all(select_ctx, "Tableview_nameContext", [])})
    else:
        referenced_tables = sorted({bare_name(text_of(t))
                                    for t in find_all(select_ctx, "Tableview_nameContext", [])})

    return {
        "view": text_of(name_ctx).upper().replace('"', ""),
        "owner": text_of(schema_ctx).upper().replace('"', "") if schema_ctx else "",
        "references_tables": referenced_tables,
        # A view's WHERE clause frequently IS the business rule (e.g.
        # active_accounts = status='ACTIVE' AND balance>0), not a mere alias.
        "filter_predicate": where_clause,
        "select_text": select_text,
        "comment": None,
        "start_line": view_ctx.start.line,
        "end_line": view_ctx.stop.line,
    }


def extract_index(idx_ctx) -> dict:
    terminals = terminal_texts(idx_ctx)
    name = text_of(find_child(idx_ctx, "Index_nameContext")).upper().replace('"', "")
    tic = find_child(idx_ctx, "Table_index_clauseContext")
    table = bare_name(text_of(find_child(tic, "Tableview_nameContext"))) if tic else None
    columns, expressions = [], []
    if tic is not None:
        for ie in find_all(tic, "Index_exprContext", []):
            col = find_child(ie, "Column_nameContext")
            if col is not None:
                columns.append(text_of(col).upper())
            else:
                expressions.append(text_of(ie))
    return {
        "index": name,
        "table": table,
        "unique": "UNIQUE" in terminals,
        "bitmap": "BITMAP" in terminals,
        "columns": columns,
        "expressions": expressions,
        "start_line": idx_ctx.start.line,
    }


def extract_synonym(syn_ctx) -> dict:
    terminals = terminal_texts(syn_ctx)
    name = text_of(find_child(syn_ctx, "Synonym_nameContext")).upper().replace('"', "")
    target = text_of(find_child(syn_ctx, "Schema_object_nameContext")).upper().replace('"', "")
    schema_ctxs = find_all_direct_children(syn_ctx, {"Schema_nameContext"})
    target_owner = text_of(schema_ctxs[-1]).upper().replace('"', "") if schema_ctxs else ""
    link = find_child(syn_ctx, "Link_nameContext")
    return {
        "synonym": name,
        "target_object": target,
        "target_owner": target_owner,
        "public": "PUBLIC" in terminals,
        "db_link": text_of(link).upper() if link else None,
        "start_line": syn_ctx.start.line,
    }


def extract_sequence(seq_ctx) -> dict:
    name = bare_name(text_of(find_child(seq_ctx, "Sequence_nameContext")))
    seq: dict = {"sequence": name, "start_with": None, "increment_by": 1,
                 "max_value": None, "min_value": None, "cycle": False,
                 "cache": None, "order": False}
    for spec in find_all(seq_ctx, "Sequence_specContext", []):
        t = text_of(spec).upper()
        if m := re.match(r"^STARTWITH(\d+)", t):
            seq["start_with"] = int(m.group(1))
        elif m := re.match(r"^INCREMENTBY(-?\d+)", t):
            seq["increment_by"] = int(m.group(1))
        elif m := re.match(r"^MAXVALUE(\d+)", t):
            seq["max_value"] = int(m.group(1))
        elif m := re.match(r"^MINVALUE(\d+)", t):
            seq["min_value"] = int(m.group(1))
        elif m := re.match(r"^CACHE(\d+)", t):
            seq["cache"] = int(m.group(1))
        elif t == "NOCACHE":
            seq["cache"] = 0
        elif t == "CYCLE":
            seq["cycle"] = True
        elif t == "ORDER":
            seq["order"] = True
    return seq


def extract_comments(tree) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """
    COMMENT ON TABLE / COMMENT ON COLUMN — free, human-authored business
    documentation already present in the schema. See DESIGN_REFERENCES
    (SchemaSpy treats this as baseline documentation scope).
    """
    table_comments: dict[str, str] = {}
    column_comments: dict[tuple[str, str], str] = {}

    def unquote(s: str) -> str:
        s = s.strip()
        if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
            s = s[1:-1]
        return s.replace("''", "'")

    for c in find_all(tree, "Comment_on_tableContext", []):
        tbl = bare_name(text_of(find_child(c, "Tableview_nameContext")))
        table_comments[tbl] = unquote(text_of(find_child(c, "Quoted_stringContext")))

    for c in find_all(tree, "Comment_on_columnContext", []):
        qualified = text_of(find_child(c, "Column_nameContext")).replace('"', "").upper()
        parts = qualified.split(".")
        if len(parts) >= 2:
            tbl, col = parts[-2], parts[-1]
            column_comments[(tbl, col)] = unquote(text_of(find_child(c, "Quoted_stringContext")))
    return table_comments, column_comments


# ---------------------------------------------------------------------------
# Phase 6 — enum mining (CHECK-enforced, or comment-documented only)
# ---------------------------------------------------------------------------

_ENUM_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def mine_comment_enum(raw_lines: list[str], start_line: int, end_line: int) -> list[str] | None:
    """
    Scan source lines [start_line, end_line] for trailing `--` comments and
    check whether they form a comma-separated list of ALL-CAPS tokens — the
    shape a documented-but-unenforced enum takes.
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


def attach_enums(table: dict, raw_lines: list[str], stats: dict) -> None:
    """Attach enum_values to each column from the strongest available source."""
    for idx, col in enumerate(table["columns"]):
        next_line = table["end_line"]
        if idx + 1 < len(table["columns"]):
            next_line = table["columns"][idx + 1]["line"] - 1

        enum_from_check = None
        source_constraint = None
        for chk in table["check_constraints"]:
            if col["name"] in chk["expression"].upper():
                mined = mine_check_enum(chk["expression"])
                if mined:
                    enum_from_check, source_constraint = mined, chk
                    break
        if col.get("inline_check") and not enum_from_check:
            mined = mine_check_enum(col["inline_check"])
            if mined:
                enum_from_check = mined

        if enum_from_check:
            col["enum_values"] = enum_from_check
            col["enum_source"] = "check_constraint"
            # An enum is only 'enforced' if its constraint actually is.
            if source_constraint and not source_constraint["enforcement"]["is_enforced"]:
                col["confidence"] = "documented_only"
                col["requires_sme_review"] = True
                col["enum_note"] = "Value list comes from a CHECK constraint that is DISABLED — not enforced."
            else:
                col["confidence"] = "enforced"
            continue

        mined = mine_comment_enum(raw_lines, col["line"], next_line)
        if mined:
            col["enum_values"] = mined
            col["enum_source"] = "comment_only"
            col["confidence"] = "documented_only"
            col["requires_sme_review"] = True
            stats["comment_only_enums"] += 1


# ---------------------------------------------------------------------------
# Phase 7 — implicit FK detection
# See DESIGN_REFERENCES: naming-convention matches are real signal but produce
# false positives — always tagged relationship_type: inferred.
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
            pk_index.setdefault(pk_col, (t["table"], pk_col))
            singular = t["table"][:-1] if t["table"].endswith("S") else t["table"]
            pk_index.setdefault(f"{singular}_ID", (t["table"], pk_col))
            pk_index.setdefault(f"{singular}_NUMBER", (t["table"], pk_col))

    for t in tables.values():
        pk_cols = set(t["primary_key"] or [])
        for col in t["columns"]:
            if (t["table"], col["name"]) in declared_fk_columns or col["name"] in pk_cols:
                continue
            target = pk_index.get(col["name"])
            if target and target[0] != t["table"]:
                # Type compatibility guard: only claim a relationship if the
                # normalized types actually match, not just the names.
                target_tbl = tables[target[0]]
                target_col = next((c for c in target_tbl["columns"] if c["name"] == target[1]), None)
                type_match = target_col is not None and \
                    target_col["normalized_type"] == col["normalized_type"]
                inferred.append({
                    "from_table": t["table"], "from_column": col["name"],
                    "to_table": target[0], "to_column": target[1],
                    "relationship_type": "inferred",
                    "basis": "name_match+type_compatible" if type_match else "name_match_only",
                    "confidence": "medium" if type_match else "low",
                })
    return inferred


# ---------------------------------------------------------------------------
# Phase 8 — %TYPE / %ROWTYPE resolution against Agent 2's declarations
# ---------------------------------------------------------------------------

_TYPE_REF_RE = re.compile(r"(?:\w+\.)?(\w+)\.(\w+)\s*%TYPE", re.IGNORECASE)
_ROWTYPE_REF_RE = re.compile(r"(?:\w+\.)?(\w+)\s*%ROWTYPE", re.IGNORECASE)


def resolve_type_references(parser_objects: dict[str, dict], tables: dict[str, dict],
                            views: dict[str, dict], issues: list[dict]) -> list[dict]:
    resolved = []
    for object_id, obj in parser_objects.items():
        for decl in obj.get("declarations", []):
            type_text = decl.get("type", "")
            m = _TYPE_REF_RE.search(type_text)
            if m:
                table_name, col_name = m.group(1).upper(), m.group(2).upper()
                table = tables.get(table_name)
                found = bool(table) and any(c["name"] == col_name for c in table["columns"])
                resolved.append({"object_id": object_id, "declaration": decl["name"],
                                 "reference": f"{table_name}.{col_name}%TYPE", "resolved": found})
                if not found:
                    issues.append({"severity": "warning", "type": "unresolved_type_reference",
                                   "object_id": object_id,
                                   "message": f"{table_name}.{col_name}%TYPE not found in data dictionary"})
                continue
            m = _ROWTYPE_REF_RE.search(type_text)
            if m:
                table_name = m.group(1).upper()
                found = table_name in tables or table_name in views
                resolved.append({"object_id": object_id, "declaration": decl["name"],
                                 "reference": f"{table_name}%ROWTYPE", "resolved": found})
                if not found:
                    issues.append({"severity": "warning", "type": "unresolved_type_reference",
                                   "object_id": object_id,
                                   "message": f"{table_name}%ROWTYPE not found in data dictionary"})
    return resolved


# ---------------------------------------------------------------------------
# Phase 9 — cross-validate parser output; build flat column catalogue
# ---------------------------------------------------------------------------

def cross_validate(parser_objects: dict[str, dict], tables: dict[str, dict],
                   views: dict[str, dict], synonyms: dict[str, dict],
                   issues: list[dict]) -> tuple[dict, dict[tuple[str, str], set]]:
    """
    Validate every table/column Agent 2 recorded against the real dictionary,
    resolving synonyms and tolerating views. Also accumulates column usage
    (which objects touch which column) for the flat column catalogue —
    mirrors the reference pipeline's field_catalogue.used_by_programs.
    """
    stats = {"tables_referenced": 0, "unknown_tables": 0, "unknown_columns": 0,
             "synonyms_resolved": 0, "view_references": 0}
    seen_tables: set[str] = set()
    column_usage: dict[tuple[str, str], set] = {}

    def resolve_name(name: str) -> tuple[str | None, str]:
        """-> (real_table_name_or_None, kind)"""
        u = bare_name(name)
        if u in tables:
            return u, "table"
        if u in views:
            return u, "view"
        syn = synonyms.get(u)
        if syn:
            target = syn["target_object"]
            if target in tables:
                stats["synonyms_resolved"] += 1
                return target, "synonym->table"
            if target in views:
                stats["synonyms_resolved"] += 1
                return target, "synonym->view"
        return None, "unknown"

    for object_id, obj in parser_objects.items():
        param_names = {p["name"].upper() for p in obj.get("parameters", [])}
        local_names = {d["name"].upper() for d in obj.get("declarations", [])}
        for stmt in obj.get("statements", {}).values():
            stmt_tables = stmt.get("tables", [])
            if not stmt_tables:
                continue

            resolved_tables: list[str] = []
            for table_name in stmt_tables:
                seen_tables.add(bare_name(table_name))
                real, kind = resolve_name(table_name)
                if real is None:
                    stats["unknown_tables"] += 1
                    issues.append({"severity": "info", "type": "unknown_table_reference",
                                   "object_id": object_id, "statement_id": stmt["statement_id"],
                                   "message": f"Table '{table_name}' not found in parsed DDL "
                                              "(may be external/other-schema — not necessarily an error)"})
                    continue
                if kind.endswith("view"):
                    stats["view_references"] += 1
                    # A view's own columns aren't in the table dictionary;
                    # fall through to its backing tables for column checking.
                    resolved_tables.extend(views[real]["references_tables"])
                else:
                    resolved_tables.append(real)

            known_here = [t for t in resolved_tables if t in tables]
            if not known_here:
                continue

            # Check columns against the UNION across every table the statement
            # touches — a single statement (e.g. INSERT ... SELECT) can span
            # several tables, and a column belonging to table B must not be
            # reported unknown merely because it isn't on table A.
            combined = {c["name"] for t in known_here for c in tables[t]["columns"]}
            for col_field in ("reads", "writes", "predicate_reads"):
                for col in stmt.get(col_field, []):
                    cu = col.upper()
                    if cu in combined:
                        for t in known_here:
                            if any(c["name"] == cu for c in tables[t]["columns"]):
                                column_usage.setdefault((t, cu), set()).add(object_id)
                    elif cu not in param_names and cu not in local_names:
                        stats["unknown_columns"] += 1
                        issues.append({"severity": "warning", "type": "unknown_column_reference",
                                       "object_id": object_id, "statement_id": stmt["statement_id"],
                                       "message": f"Column '{col}' not found on any of the statement's "
                                                  f"referenced tables ({', '.join(known_here)})"})
    stats["tables_referenced"] = len(seen_tables)
    return stats, column_usage


def build_column_catalogue(tables: dict[str, dict],
                           column_usage: dict[tuple[str, str], set]) -> list[dict]:
    """Flat, sorted catalogue of every column — mirrors the reference
    pipeline's field_catalogue, and is what the BRD data appendix consumes."""
    catalogue = []
    for tname in sorted(tables):
        t = tables[tname]
        pk = set(t["primary_key"] or [])
        for c in t["columns"]:
            used_by = sorted(column_usage.get((tname, c["name"]), set()))
            catalogue.append({
                "column_id": f"{tname}.{c['name']}",
                "table": tname,
                "column": c["name"],
                "oracle_type": c["oracle_type"],
                "normalized_type": c["normalized_type"],
                "pyspark_type": c["pyspark_type"],
                "nullable": c["nullable"],
                "is_primary_key": c["name"] in pk,
                "is_identity": c.get("is_identity", False),
                "is_virtual": c.get("is_virtual", False),
                "enum_values": c.get("enum_values"),
                "enum_source": c.get("enum_source"),
                "description": c.get("comment"),
                "used_by_objects": used_by,
                "usage_count": len(used_by),
            })
    return catalogue


# ---------------------------------------------------------------------------
# Phase 10 — sequence usage linkage
# ---------------------------------------------------------------------------

def find_sequence_usage(parser_objects: dict[str, dict], sequences: dict[str, dict],
                        file_abs_paths: dict[str, str]) -> list[dict]:
    usages = []
    for object_id, obj in parser_objects.items():
        abs_path = file_abs_paths.get(obj.get("file_id"))
        if not abs_path:
            continue
        lines = source_lines(abs_path)
        if not lines:
            continue
        for stmt in obj.get("statements", {}).values():
            if stmt.get("statement_type") not in ("INSERT", "UPDATE", "ASSIGNMENT", "SELECT_INTO"):
                continue
            start, end = stmt.get("start_line"), stmt.get("end_line")
            if not start or not end:
                continue
            snippet = " ".join(lines[start - 1:end]).upper().replace(" ", "")
            for seq_name in sequences:
                if f"{seq_name}.NEXTVAL" in snippet or f"{seq_name}.CURRVAL" in snippet:
                    usages.append({"sequence": seq_name, "object_id": object_id,
                                   "statement_id": stmt["statement_id"],
                                   "table": (stmt.get("tables") or [None])[0]})
    return usages


# ---------------------------------------------------------------------------
# Phase 11 — DDL-derived business rule candidates (four sources)
# ---------------------------------------------------------------------------

def harvest_ddl_rule_candidates(tables: dict[str, dict], views: dict[str, dict],
                                indexes: list[dict]) -> list[dict]:
    """
    Unified feed for Agent 5. Each candidate states its enforcement honestly
    so a disabled constraint can never be presented as an active guarantee.
    """
    candidates = []

    for tname in sorted(tables):
        t = tables[tname]
        for chk in t["check_constraints"]:
            enf = chk["enforcement"]
            candidates.append({
                "source_kind": "check_constraint", "table": tname,
                "constraint_name": chk["name"], "expression": chk["expression"],
                "is_enforced": enf["is_enforced"], "confidence": enf["confidence"],
                "explanation": enf["explanation"],
            })
        for col in t["columns"]:
            if col.get("is_virtual") and col.get("generation_expression"):
                candidates.append({
                    "source_kind": "virtual_column", "table": tname, "column": col["name"],
                    "expression": col["generation_expression"],
                    "is_enforced": True, "confidence": "enforced",
                    "explanation": "Computed column — the database always derives this value from "
                                   "the given formula; it is a business calculation by definition.",
                })
        for uq in t["unique_constraints"]:
            enf = uq["enforcement"]
            candidates.append({
                "source_kind": "unique_constraint", "table": tname,
                "constraint_name": uq["name"], "columns": uq["columns"],
                "is_enforced": enf["is_enforced"], "confidence": enf["confidence"],
                "explanation": enf["explanation"],
            })

    for idx in indexes:
        if idx["unique"] and idx["table"]:
            candidates.append({
                "source_kind": "unique_index", "table": idx["table"],
                "index_name": idx["index"], "columns": idx["columns"],
                "is_enforced": True, "confidence": "enforced",
                "explanation": "A UNIQUE index enforces uniqueness at the database level even without "
                               "a declared UNIQUE constraint — a de facto business rule.",
            })

    for vname in sorted(views):
        v = views[vname]
        if v.get("filter_predicate"):
            candidates.append({
                "source_kind": "view_filter", "view": vname,
                "expression": v["filter_predicate"],
                "references_tables": v["references_tables"],
                "is_enforced": True, "confidence": "enforced",
                "explanation": "This view's WHERE clause defines a named business subset of its "
                               "backing tables; the filter is the rule.",
            })
    return candidates


# ---------------------------------------------------------------------------
# ERD generation (Mermaid)
# ---------------------------------------------------------------------------

def generate_erd(tables: dict[str, dict], inferred_fks: list[dict]) -> str:
    lines = ["erDiagram"]
    for tname in sorted(tables):
        t = tables[tname]
        pk_set = set(t["primary_key"] or [])
        lines.append(f"    {t['table']} {{")
        for c in t["columns"]:
            marker = "PK" if c["name"] in pk_set else ""
            lines.append(f"        {c['normalized_type'].lower()} {c['name']} {marker}".rstrip())
        lines.append("    }")
    for tname in sorted(tables):
        t = tables[tname]
        for fk in t["foreign_keys"]:
            if fk["references_table"] in tables:
                label = ",".join(fk["columns"])
                if fk.get("on_delete") and fk["on_delete"] != "NO_ACTION":
                    label += f" [{fk['on_delete']}]"
                lines.append(f'    {fk["references_table"]} ||--o{{ {t["table"]} : "{label}"')
    for inf in inferred_fks:
        if inf["to_table"] in tables and inf["from_table"] in tables:
            lines.append(f'    {inf["to_table"]} }}o..o{{ {inf["from_table"]} '
                         f': "{inf["from_column"]} (inferred)"')
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_parser_objects(parser_root: Path, object_index: dict) -> dict[str, dict]:
    """Read every raw_structure file once, up front, instead of re-reading
    the same files in each downstream pass."""
    objects: dict[str, dict] = {}
    for object_id, rel_path in object_index.items():
        p = parser_root / rel_path
        if p.exists():
            objects[object_id] = json.loads(p.read_text(encoding="utf-8"))
    return objects


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
    parser_objects = load_parser_objects(parser_root, parser_artifact["object_index"])

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    run_dir.mkdir(parents=True, exist_ok=True)

    issues: list[dict] = []
    tables: dict[str, dict] = {}
    views: dict[str, dict] = {}
    synonyms: dict[str, dict] = {}
    sequences: dict[str, dict] = {}
    indexes: list[dict] = []
    # Every file in the inventory, not just the DDL ones — sequence usage
    # (seq.NEXTVAL) lives in PROCEDURAL files, which this agent never parses
    # but must still be able to read source lines from.
    file_abs_paths: dict[str, str] = {
        fid: meta["abs_path"] for fid, meta in inventory["file_metadata"].items()
        if meta.get("abs_path")
    }
    stats = {"ddl_files_parsed": 0, "parse_errors": 0, "tables_found": 0, "temporary_tables": 0,
             "partitioned_tables": 0, "views_found": 0, "indexes_found": 0, "unique_indexes": 0,
             "synonyms_found": 0, "sequences_found": 0, "columns_total": 0, "virtual_columns": 0,
             "identity_columns": 0, "declared_foreign_keys": 0, "inferred_foreign_keys": 0,
             "cascade_deletes": 0, "check_constraints": 0, "disabled_constraints": 0,
             "unvalidated_constraints": 0, "candidate_rules_from_ddl": 0,
             "comment_only_enums": 0, "table_comments": 0, "column_comments": 0}

    # ---- Parse every DDL file ----
    for file_rec in route_ddl_files(inventory):
        if args.verbose:
            print(f"  [parsing DDL] {file_rec['path']}", file=sys.stderr)
        tree, errors = parse_source(file_rec["abs_path"])
        stats["ddl_files_parsed"] += 1
        if errors:
            stats["parse_errors"] += len(errors)
            for e in errors:
                issues.append({"severity": "error", "type": "syntax_error", "file": file_rec["path"], **e})

        raw_lines = source_lines(file_rec["abs_path"])
        table_comments, column_comments = extract_comments(tree)
        stats["table_comments"] += len(table_comments)
        stats["column_comments"] += len(column_comments)

        for tctx in find_all(tree, "Create_tableContext", []):
            t = extract_table(tctx)
            t["source_file"] = file_rec["path"]
            attach_enums(t, raw_lines, stats)
            tables[t["table"]] = t

        for vctx in find_all(tree, "Create_viewContext", []):
            v = extract_view(vctx)
            v["source_file"] = file_rec["path"]
            views[v["view"]] = v

        for ictx in find_all(tree, "Create_indexContext", []):
            i = extract_index(ictx)
            i["source_file"] = file_rec["path"]
            indexes.append(i)

        for sctx in find_all(tree, "Create_synonymContext", []):
            s = extract_synonym(sctx)
            s["source_file"] = file_rec["path"]
            synonyms[s["synonym"]] = s

        for qctx in find_all(tree, "Create_sequenceContext", []):
            s = extract_sequence(qctx)
            s["source_file"] = file_rec["path"]
            sequences[s["sequence"]] = s

        # Attach comments after objects exist (a COMMENT ON may precede or
        # follow its target within the same file).
        for tbl_name, comment in table_comments.items():
            if tbl_name in tables:
                tables[tbl_name]["comment"] = comment
            elif tbl_name in views:
                views[tbl_name]["comment"] = comment
        for (tbl_name, col_name), comment in column_comments.items():
            tbl = tables.get(tbl_name)
            if tbl:
                for c in tbl["columns"]:
                    if c["name"] == col_name:
                        c["comment"] = comment

    # ---- Roll up structural stats ----
    for t in tables.values():
        stats["tables_found"] += 1
        stats["columns_total"] += len(t["columns"])
        stats["virtual_columns"] += sum(1 for c in t["columns"] if c.get("is_virtual"))
        stats["identity_columns"] += sum(1 for c in t["columns"] if c.get("is_identity"))
        stats["declared_foreign_keys"] += len(t["foreign_keys"])
        stats["cascade_deletes"] += sum(1 for fk in t["foreign_keys"] if fk.get("on_delete") == "CASCADE")
        stats["check_constraints"] += len(t["check_constraints"])
        if t["temporary"]:
            stats["temporary_tables"] += 1
        if t["partitioning"]:
            stats["partitioned_tables"] += 1
        for c in t["check_constraints"] + t["unique_constraints"] + t["foreign_keys"]:
            enf = c["enforcement"]
            if enf["status"] == "DISABLED":
                stats["disabled_constraints"] += 1
                issues.append({
                    "severity": "warning", "type": "constraint_not_enforced",
                    "table": t["table"], "constraint": c["name"],
                    "message": f"{c['kind']} constraint '{c['name']}' on {t['table']} is DISABLED — "
                               "it documents intent but the database is not enforcing it. "
                               "Data may violate it.",
                })
            elif enf["validated"] == "NOT_VALIDATED":
                stats["unvalidated_constraints"] += 1
                issues.append({
                    "severity": "info", "type": "constraint_not_validated",
                    "table": t["table"], "constraint": c["name"],
                    "message": f"{c['kind']} constraint '{c['name']}' on {t['table']} is ENABLE "
                               "NOVALIDATE — new rows are checked, pre-existing data was not.",
                })

    stats["views_found"] = len(views)
    stats["indexes_found"] = len(indexes)
    stats["unique_indexes"] = sum(1 for i in indexes if i["unique"])
    stats["synonyms_found"] = len(synonyms)
    stats["sequences_found"] = len(sequences)

    # ---- Derived analyses ----
    inferred_fks = detect_implicit_fks(tables)
    stats["inferred_foreign_keys"] = len(inferred_fks)

    type_resolutions = resolve_type_references(parser_objects, tables, views, issues)
    cross_val_stats, column_usage = cross_validate(parser_objects, tables, views, synonyms, issues)
    sequence_usages = find_sequence_usage(parser_objects, sequences, file_abs_paths)
    column_catalogue = build_column_catalogue(tables, column_usage)
    rule_candidates = harvest_ddl_rule_candidates(tables, views, indexes)
    stats["candidate_rules_from_ddl"] = len(rule_candidates)

    (run_dir / "erd.mmd").write_text(generate_erd(tables, inferred_fks), encoding="utf-8")

    data_artifact = {
        "pipeline_stage": "3_data", "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {"inventory_run_version": inv_run_version, "parser_run_version": parser_run_version},
        "design_references": DESIGN_REFERENCES,
        "stats": {**stats, **cross_val_stats},
        "tables": tables,
        "views": views,
        "indexes": indexes,
        "synonyms": synonyms,
        "sequences": sequences,
        "column_catalogue": column_catalogue,
        "inferred_relationships": inferred_fks,
        "ddl_rule_candidates": rule_candidates,
        "type_reference_resolutions": type_resolutions,
        "sequence_usages": sequence_usages,
        "issues": issues,
    }
    (run_dir / "data_artifact.json").write_text(
        json.dumps(data_artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        (run_dir / "run_meta.json").write_text(json.dumps({
            "stage": "3_data", "run_version": run_version, "status": "success",
            "generated_at": data_artifact["generated_at"], "upstream": data_artifact["upstream"],
            "stats_summary": stats}, indent=2, ensure_ascii=False), encoding="utf-8")
        (Path(args.output_root) / "latest.json").write_text(json.dumps({
            "run_version": run_version, "path": f"{run_version}/data_artifact.json",
            "updated_at": data_artifact["generated_at"]}, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== Data Agent Complete ===")
    print(f"DDL files parsed        : {stats['ddl_files_parsed']}")
    print(f"Tables                  : {stats['tables_found']} "
          f"({stats['temporary_tables']} temporary, {stats['partitioned_tables']} partitioned)")
    print(f"Columns                 : {stats['columns_total']} "
          f"({stats['virtual_columns']} virtual, {stats['identity_columns']} identity)")
    print(f"Views                   : {stats['views_found']}")
    print(f"Indexes                 : {stats['indexes_found']} ({stats['unique_indexes']} unique)")
    print(f"Synonyms                : {stats['synonyms_found']}")
    print(f"Sequences               : {stats['sequences_found']}")
    print(f"Schema comments         : {stats['table_comments']} table, {stats['column_comments']} column")
    print(f"Foreign keys            : {stats['declared_foreign_keys']} declared "
          f"({stats['cascade_deletes']} ON DELETE CASCADE), {stats['inferred_foreign_keys']} inferred")
    print(f"CHECK constraints       : {stats['check_constraints']}")
    print(f"  [!] DISABLED          : {stats['disabled_constraints']}  (documented, NOT enforced)")
    print(f"  [!] ENABLE NOVALIDATE : {stats['unvalidated_constraints']}  (new rows only)")
    print(f"DDL rule candidates     : {stats['candidate_rules_from_ddl']}")
    print(f"Comment-only enums      : {stats['comment_only_enums']}  (flagged requires_sme_review)")
    print(f"Unknown table refs      : {cross_val_stats['unknown_tables']}")
    print(f"Unknown column refs     : {cross_val_stats['unknown_columns']}")
    print(f"Synonyms resolved       : {cross_val_stats['synonyms_resolved']}")
    print(f"Parse errors            : {stats['parse_errors']}")
    print(f"Output                  : {run_dir / 'data_artifact.json'}")
    print("============================")


if __name__ == "__main__":
    main()
