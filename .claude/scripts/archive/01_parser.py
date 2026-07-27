#!/usr/bin/env python3
"""
Stage 1: PARSER  →  parse-artifact.json
----------------------------------------
Consumes the inventory manifest produced by Stage 0 (inventory-artifact.json)
and performs deep structural parsing on every .sql file listed in it.

For each file the agent:
  1. Re-reads the file from abs_path (using encoding_used from the manifest)
  2. Runs the SQL state machine to split the file into top-level statements,
     recording exact start/end line ranges for each
  3. Assigns a globally unique statement_id:  <file_id>_S<n>  (e.g. FILE_0003_S02)
  4. Runs sqlglot (Oracle dialect) on each statement to build an ANTLR-style
     AST, serialised as a nested JSON dict
  5. Extracts semantic fields from the AST: reads, writes, dml_ops, signature,
     calls, flags
  6. Runs a second pass on PL/SQL block bodies to extract child statements,
     each with their own statement_id and partial AST
  7. Emits parse-artifact.json — the input consumed by Stage 2 (02_enrich.py)

Zero LLM calls. One external dependency: sqlglot (pip install sqlglot).

Usage:
    python 01_parser.py <inventory_json> [options]

    Options:
      --output   -o   Output path (default: checkpoints/parse-artifact.json)
      --sql-dir       Override source directory for file reads (optional)
      --encoding      Fallback encoding if not recorded in manifest
      --skip-ast      Omit AST trees (smaller output, faster; Stage 2 still works)
      --verbose  -v   Per-file + per-statement progress to stderr

Input contract (from Stage 0):
    inventory-artifact.json must contain:
      .files[].file_id        globally unique file identifier
      .files[].abs_path       absolute path to the .sql file
      .files[].encoding_used  encoding to use when reading
      .files[].status         only "ok" files are parsed
      .files[].file_role      carried through unchanged
      .files[].complexity     carried through unchanged
      .files[].content_hints  carried through unchanged

Output schema (parse-artifact.json):
    {
      "pipeline_stage": "01_parser",
      "schema_version": "1.0",
      "generated_at":   "<iso8601>",
      "source_manifest": "<path to inventory json>",
      "summary": { ... },
      "files": [
        {
          "file_id":        "FILE_0001",
          "file":           "schema/tables.sql",
          "file_role":      "schema_ddl",
          "complexity":     "low",
          "content_hints":  { ... },
          "statement_count": 5,
          "parse_error":    null,
          "statements": [
            {
              "statement_id":  "FILE_0001_S01",
              "file_id":       "FILE_0001",
              "sequence":      1,
              "type":          "DDL",
              "subtype":       "CREATE_TABLE",
              "object_name":   "CUSTOMER",
              "lines":         { "start": 2, "end": 9 },
              "char_offsets":  { "start": 45, "end": 312 },
              "source_text":   "CREATE TABLE CUSTOMER ...",
              "signature":     { "params": [], "returns": null },
              "reads":         [],
              "writes":        [],
              "dml_ops":       [],
              "flags":         {},
              "calls":         [],
              "ast": {
                "parser":      "sqlglot-oracle",
                "status":      "ok",
                "root": { "node_type": "Create", "args": { ... } }
              },
              "children":      []
            },
            ...
          ]
        }
      ]
    }

Child statement schema (inside statements[].children[]):
    Same as statement schema above, with:
      statement_id   "<parent_statement_id>_C<n>"  e.g. FILE_0001_S03_C02
      parent_id      "<parent_statement_id>"
    Children do NOT have further nested children (max 2 levels).
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import sqlglot
    import sqlglot.expressions as exp
    import logging
    logging.getLogger("sqlglot").setLevel(logging.CRITICAL)
    SQLGLOT_AVAILABLE = True
except ImportError:
    SQLGLOT_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — COMPILED PATTERNS
# All regex compiled once at module load.  Names prefixed _ are internal.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Comment strippers ─────────────────────────────────────────────────────────
_STRIP_SINGLE_CMT = re.compile(r"--[^\n]*")
_STRIP_MULTI_CMT  = re.compile(r"/\*.*?\*/", re.S)
_STRIP_STRINGS    = re.compile(r"'(?:[^']|'')*'")   # removes string literals

# ── State machine: DDL / PL/SQL top-level triggers ────────────────────────────
# Ordered longest-match first.  Each entry: (pattern, block_type, subtype)
DDL_TRIGGERS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+PACKAGE\s+BODY\s+(\w+)", re.I), "PLSQL_BLOCK", "PACKAGE_BODY"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+PACKAGE\s+(\w+)",        re.I), "PLSQL_BLOCK", "PACKAGE"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+(\w+)",      re.I), "PLSQL_BLOCK", "PROCEDURE"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(\w+)",       re.I), "PLSQL_BLOCK", "FUNCTION"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+TRIGGER\s+(\w+)",        re.I), "PLSQL_BLOCK", "TRIGGER"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+TYPE\s+BODY\s+(\w+)",    re.I), "PLSQL_BLOCK", "TYPE_BODY"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+TYPE\s+(\w+)",           re.I), "PLSQL_BLOCK", "TYPE"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+VIEW\s+(\w+)",           re.I), "DDL",         "CREATE_VIEW"),
    (re.compile(r"CREATE\s+UNIQUE\s+INDEX\s+(\w+)",                re.I), "DDL",         "CREATE_INDEX"),
    (re.compile(r"CREATE\s+INDEX\s+(\w+)",                         re.I), "DDL",         "CREATE_INDEX"),
    (re.compile(r"CREATE\s+TABLE\s+(\w+)",                         re.I), "DDL",         "CREATE_TABLE"),
    (re.compile(r"CREATE\s+SEQUENCE\s+(\w+)",                      re.I), "DDL",         "CREATE_SEQUENCE"),
    (re.compile(r"ALTER\s+TABLE\s+(\w+)",                          re.I), "DDL",         "ALTER_TABLE"),
    (re.compile(r"DROP\s+\w+\s+(\w+)",                             re.I), "DDL",         "DROP"),
    (re.compile(r"GRANT\s+\S.*?\s+ON\s+(\w+)",                    re.I), "DCL",         "GRANT"),
    (re.compile(r"REVOKE\s+\S.*?\s+ON\s+(\w+)",                   re.I), "DCL",         "REVOKE"),
    (re.compile(r"COMMENT\s+ON\s+(?:TABLE|COLUMN)\s+(\w+)",        re.I), "DDL",         "COMMENT"),
    (re.compile(r"TRUNCATE\s+TABLE\s+(\w+)",                       re.I), "DDL",         "TRUNCATE"),
]

# ── Standalone DML (outside PL/SQL) ───────────────────────────────────────────
STANDALONE_DML: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^INSERT\s+INTO\s+(\w+)", re.I), "DML", "INSERT"),
    (re.compile(r"^UPDATE\s+(\w+)",        re.I), "DML", "UPDATE"),
    (re.compile(r"^DELETE\s+FROM\s+(\w+)", re.I), "DML", "DELETE"),
    (re.compile(r"^SELECT\b",              re.I), "DML", "SELECT"),
    (re.compile(r"^MERGE\s+INTO\s+(\w+)", re.I), "DML", "MERGE"),
    (re.compile(r"^COMMIT\b",             re.I), "TCL", "COMMIT"),
    (re.compile(r"^ROLLBACK\b",           re.I), "TCL", "ROLLBACK"),
    (re.compile(r"^SAVEPOINT\b",          re.I), "TCL", "SAVEPOINT"),
]

# ── State machine: BEGIN/END depth tracking ───────────────────────────────────
_BEGIN_RE   = re.compile(r"\bBEGIN\b",               re.I)
_CASE_RE    = re.compile(r"\bCASE\b",                re.I)
_END_RE     = re.compile(r"\bEND\b\s*(?:\w+\s*)?;", re.I)
_ENDCASE_RE = re.compile(r"\bEND\s+CASE\b",          re.I)
_ENDIF_RE   = re.compile(r"\bEND\s+(?:IF|LOOP)\b",  re.I)
_SLASH_RE   = re.compile(r"^\s*/\s*$")
_ML_START   = re.compile(r"/\*")
_ML_END     = re.compile(r"\*/")

# ── Table reference extractors ────────────────────────────────────────────────
_FROM_TABLES  = re.compile(r"\bFROM\s+(\w+)",          re.I)
_JOIN_TABLES  = re.compile(r"\bJOIN\s+(\w+)",          re.I)
_INSERT_TABLE = re.compile(r"\bINSERT\s+INTO\s+(\w+)", re.I)
_UPDATE_TABLE = re.compile(r"\bUPDATE\s+(\w+)\s+SET\b",re.I)
_DELETE_TABLE = re.compile(r"\bDELETE\s+FROM\s+(\w+)", re.I)
_MERGE_TABLE  = re.compile(r"\bMERGE\s+INTO\s+(\w+)",  re.I)

# ── Signature extractors ──────────────────────────────────────────────────────
_PARAM_BLOCK  = re.compile(r"(?:PROCEDURE|FUNCTION)\s+\w+\s*\(([^)]*)\)", re.I | re.S)
_RETURN_TYPE  = re.compile(r"\bRETURN\s+(\w+(?:\s*\(\s*\d+\s*(?:,\s*\d+\s*)?\))?)", re.I)
_SINGLE_PARAM = re.compile(
    r"(\w+)\s+(IN\s+OUT|IN|OUT)\s+(\w+(?:\s*\(\s*\d+\s*(?:,\s*\d+\s*)?\))?)"
    r"(?:\s+DEFAULT\s+[^,)]+)?",
    re.I,
)

# ── Call detection (heuristic) ────────────────────────────────────────────────
_SQL_KEYWORDS = frozenset([
    "IF","ELSIF","WHILE","FOR","LOOP","CASE","WHEN","BEGIN","END",
    "SELECT","INSERT","UPDATE","DELETE","FROM","WHERE","INTO","JOIN",
    "AND","OR","NOT","IN","IS","NULL","LIKE","BETWEEN","EXISTS",
    "NVL","NVL2","DECODE","COALESCE","TO_DATE","TO_CHAR","TO_NUMBER",
    "SUBSTR","TRIM","UPPER","LOWER","LENGTH","INSTR","REPLACE",
    "ROUND","TRUNC","MOD","ABS","SIGN","FLOOR","CEIL","SUM","COUNT",
    "MAX","MIN","AVG","SYSDATE","SYSTIMESTAMP","NEXTVAL","CURRVAL",
    "ROWNUM","ROWID","NUMBER","VARCHAR2","DATE","CHAR","BOOLEAN",
    "INTEGER","PLS_INTEGER","BINARY_INTEGER","CLOB","BLOB","NVARCHAR2",
    "VALUES","SET","MERGE","USING","MATCHED","ON","PRIOR","CONNECT",
    "COMMIT","ROLLBACK","SAVEPOINT","EXECUTE","IMMEDIATE","BULK",
    "COLLECT","FORALL","RAISE","RETURN","PRAGMA",
])
_PROC_CALL_RE = re.compile(r"\b([A-Z][A-Z0-9_]*)\s*\(", re.I)

# ── Block-level flags ─────────────────────────────────────────────────────────
FLAG_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("has_cursor",             re.compile(r"\bCURSOR\b",                    re.I)),
    ("has_commit",             re.compile(r"\bCOMMIT\b",                    re.I)),
    ("has_rollback",           re.compile(r"\bROLLBACK\b",                  re.I)),
    ("has_exception_handling", re.compile(r"\bEXCEPTION\b",                 re.I)),
    ("has_dynamic_sql",        re.compile(r"\bEXECUTE\s+IMMEDIATE\b",       re.I)),
    ("has_bulk_collect",       re.compile(r"\bBULK\s+COLLECT\b",            re.I)),
    ("has_forall",             re.compile(r"\bFORALL\b",                    re.I)),
    ("has_autonomous_txn",     re.compile(r"PRAGMA\s+AUTONOMOUS_TRANSACTION",re.I)),
    ("has_dbms_calls",         re.compile(r"\bDBMS_\w+\.",                  re.I)),
    ("has_loop",               re.compile(r"\bLOOP\b",                      re.I)),
    ("has_if_block",           re.compile(r"\bIF\b",                        re.I)),
    ("has_savepoint",          re.compile(r"\bSAVEPOINT\b",                 re.I)),
    ("has_return",             re.compile(r"\bRETURN\b",                    re.I)),
]

# ── Inner-child patterns (second pass on PL/SQL body) ────────────────────────
# Each entry: (pattern, block_type, subtype)
INNER_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bSELECT\b.*?\bINTO\b",   re.I | re.S), "DML",     "SELECT_INTO"),
    (re.compile(r"\bINSERT\s+INTO\s+\w+",   re.I),        "DML",     "INSERT"),
    (re.compile(r"\bUPDATE\s+\w+\s+SET\b",  re.I),        "DML",     "UPDATE"),
    (re.compile(r"\bDELETE\s+FROM\s+\w+",   re.I),        "DML",     "DELETE"),
    (re.compile(r"\bMERGE\s+INTO\s+\w+",    re.I),        "DML",     "MERGE"),
    (re.compile(r"\bEXECUTE\s+IMMEDIATE\b", re.I),        "DML",     "DYNAMIC_SQL"),
    (re.compile(r"\bIF\b.+?\bTHEN\b",       re.I | re.S), "CONTROL", "IF_BLOCK"),
    (re.compile(r"\bFOR\s+\w+\s+IN\b",      re.I),        "CONTROL", "FOR_LOOP"),
    (re.compile(r"\bWHILE\b.+?\bLOOP\b",    re.I | re.S), "CONTROL", "WHILE_LOOP"),
    (re.compile(r"\bCURSOR\s+\w+\s+IS\b",   re.I),        "DECL",    "CURSOR_DECL"),
    (re.compile(r"\bEXCEPTION\b",           re.I),        "CONTROL", "EXCEPTION_HANDLER"),
    (re.compile(r"\bDBMS_\w+\.\w+\s*\(",    re.I),        "BUILTIN", "DBMS_CALL"),
    (re.compile(r"\bCOMMIT\b",              re.I),        "TCL",     "COMMIT"),
    (re.compile(r"\bROLLBACK\b",            re.I),        "TCL",     "ROLLBACK"),
    (re.compile(r"\bSAVEPOINT\b",           re.I),        "TCL",     "SAVEPOINT"),
]

# Non-table identifiers to filter from table extraction results
_NON_TABLE_NAMES = frozenset([
    "SELECT","INTO","FROM","WHERE","JOIN","LEFT","RIGHT","INNER","OUTER","FULL",
    "CROSS","ON","AND","OR","NOT","IN","IS","NULL","LIKE","BETWEEN","EXISTS",
    "GROUP","ORDER","BY","HAVING","UNION","ALL","DISTINCT","AS","WITH",
    "CASE","WHEN","THEN","ELSE","END","SET","VALUES","RETURNING","DUAL",
])


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — AST BUILDER  (sqlglot → serialisable dict)
# ═══════════════════════════════════════════════════════════════════════════════

def _ast_node_to_dict(node: "exp.Expression", depth: int = 0) -> dict:
    """
    Recursively serialise a sqlglot expression node into a plain dict.

    Structure mirrors ANTLR's ParseTree:
      node_type   — the expression class name  (e.g. "Select", "Update", "Where")
      name        — scalar identifier value where available
      alias       — alias string where available
      args        — dict of child nodes / scalar args (omits None and False)

    Max depth is capped at 10 to prevent runaway recursion on very complex SQL.
    Depth cap produces a truncated leaf: { "node_type": "...", "_truncated": true }
    """
    if node is None:
        return {}
    if isinstance(node, (str, int, float, bool)):
        return {"node_type": "Literal", "value": node}

    node_type = type(node).__name__
    result: dict = {"node_type": node_type}

    if depth >= 10:
        result["_truncated"] = True
        return result

    # Scalar identity fields
    for attr in ("name", "alias"):
        val = getattr(node, attr, None)
        if isinstance(val, str) and val:
            result[attr] = val

    # Recursively walk args
    child_args: dict = {}
    for key, val in node.args.items():
        if val is None or val is False:
            continue
        if isinstance(val, list):
            items = [
                _ast_node_to_dict(v, depth + 1)
                for v in val
                if isinstance(v, exp.Expression)
            ]
            if items:
                child_args[key] = items
        elif isinstance(val, exp.Expression):
            child_args[key] = _ast_node_to_dict(val, depth + 1)
        elif isinstance(val, (str, int, float, bool)):
            child_args[key] = val

    if child_args:
        result["args"] = child_args

    return result


def build_ast(source_text: str, subtype: str) -> dict:
    """
    Parse source_text with sqlglot (Oracle dialect) and return a serialisable
    AST dict.

    Returns:
      { "parser": "sqlglot-oracle", "status": "ok",      "root": { ... } }
      { "parser": "sqlglot-oracle", "status": "partial",  "root": { ... }, "warnings": [...] }
      { "parser": "sqlglot-oracle", "status": "failed",   "root": null,    "error": "..." }
      { "parser": "none",           "status": "skipped" }
    """
    if not SQLGLOT_AVAILABLE:
        return {"parser": "none", "status": "skipped",
                "note": "sqlglot not installed; run: pip install sqlglot"}
    
    import io, contextlib

    # sqlglot can handle most DDL and DML natively.
    # Full PL/SQL blocks (PACKAGE BODY with nested procs) sometimes produce a
    # "Command" fallback node — we record that as "partial" rather than failing.
    # Capture any remaining warnings sqlglot writes directly to stderr
    stderr_capture = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr_capture):
            tree = sqlglot.parse_one(
                source_text,
                dialect="oracle",
                error_level=sqlglot.ErrorLevel.IGNORE,
            )

        root = _ast_node_to_dict(tree)
        captured = stderr_capture.getvalue().strip()

        if root.get("node_type") == "Command":
            return {
                "parser":   "sqlglot-oracle",
                "status":   "partial",
                "root":     root,
                "warnings": [captured] if captured else [
                    "sqlglot fell back to Command node — PL/SQL body not fully parsed; "
                    "structural fields still extracted by state machine"
                ],
            }

        result = {"parser": "sqlglot-oracle", "status": "ok", "root": root}
        if captured:
            result["warnings"] = [captured]
        return result

    except Exception as e:
        return {
            "parser": "sqlglot-oracle",
            "status": "failed",
            "root":   None,
            "error":  str(e)[:300],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — SEMANTIC FIELD EXTRACTORS
# These operate on raw text (not AST) for resilience — they work even when
# sqlglot falls back to a Command node for complex PL/SQL.
# ═══════════════════════════════════════════════════════════════════════════════

def extract_tables(text: str) -> tuple[list[str], list[str]]:
    """Returns (reads, writes) — deduplicated, uppercased, non-keyword names."""
    def clean(names: list[str]) -> list[str]:
        return sorted({
            n.upper() for n in names
            if n.upper() not in _NON_TABLE_NAMES and len(n) > 1
        })
    reads  = _FROM_TABLES.findall(text) + _JOIN_TABLES.findall(text)
    writes = (_INSERT_TABLE.findall(text) + _UPDATE_TABLE.findall(text)
              + _DELETE_TABLE.findall(text) + _MERGE_TABLE.findall(text))
    return clean(reads), clean(writes)


def extract_dml_ops(text: str) -> list[str]:
    ops = []
    checks = [
        ("SELECT", r"\bSELECT\b"),
        ("INSERT", r"\bINSERT\b"),
        ("UPDATE", r"\bUPDATE\b"),
        ("DELETE", r"\bDELETE\b"),
        ("MERGE",  r"\bMERGE\b"),
    ]
    for name, pattern in checks:
        if re.search(pattern, text, re.I):
            ops.append(name)
    return ops


def extract_flags(text: str) -> dict[str, bool]:
    """Sparse dict — only True flags emitted."""
    return {k: True for k, p in FLAG_PATTERNS if p.search(text)}


def extract_calls(text: str) -> list[str]:
    """Heuristic: IDENTIFIER( patterns that aren't SQL keywords."""
    seen: set[str] = set()
    result: list[str] = []
    for name in _PROC_CALL_RE.findall(text):
        up = name.upper()
        if up not in _SQL_KEYWORDS and up not in seen:
            seen.add(up)
            result.append(up)
    return sorted(result)


def extract_signature(text: str, subtype: str) -> dict:
    """Extract parameter list and return type for PROCEDURE / FUNCTION."""
    sig: dict = {"params": [], "returns": None}
    if subtype not in ("PROCEDURE", "FUNCTION"):
        return sig
    m = _PARAM_BLOCK.search(text)
    if m:
        for pm in _SINGLE_PARAM.finditer(m.group(1)):
            sig["params"].append({
                "name":      pm.group(1),
                "direction": pm.group(2).upper().replace(" ", "_"),
                "datatype":  pm.group(3).upper(),
            })
    if subtype == "FUNCTION":
        rm = _RETURN_TYPE.search(text)
        if rm:
            sig["returns"] = rm.group(1).upper()
    return sig


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — CHILD STATEMENT EXTRACTOR
# Second pass on PL/SQL block bodies; produces child statement dicts.
# ═══════════════════════════════════════════════════════════════════════════════

def extract_children(
    body_text: str,
    body_start_line: int,       # 1-based absolute line of first body line
    parent_stmt_id: str,
    all_file_lines: list[str],  # full file line list for source extraction
    include_ast: bool,
) -> list[dict]:
    """
    Scan a PL/SQL body for inner DML and control statements.
    Assigns statement_ids of the form  <parent_stmt_id>_C<n>.
    """
    body_lines = body_text.splitlines()

    # Build char-offset → line-index mapping within body
    offset_to_line: list[int] = []
    for i, ln in enumerate(body_lines):
        offset_to_line.extend([i] * (len(ln) + 1))  # +1 for \n

    hits: list[tuple[int, str, str, str]] = []  # (abs_line, type, subtype, matched_text)

    for pattern, btype, subtype in INNER_PATTERNS:
        for m in pattern.finditer(body_text):
            offset = m.start()
            body_line_idx = offset_to_line[offset] if offset < len(offset_to_line) else len(body_lines) - 1
            abs_line = body_start_line + body_line_idx
            hits.append((abs_line, btype, subtype, m.group(0)))

    # Sort by line, deduplicate within a 2-line window
    hits.sort(key=lambda h: h[0])
    deduped: list[tuple[int, str, str, str]] = []
    last_line = -99
    for abs_line, btype, subtype, matched in hits:
        if abs_line - last_line > 2:
            deduped.append((abs_line, btype, subtype, matched))
            last_line = abs_line

    children: list[dict] = []
    for idx, (abs_line, btype, subtype, _) in enumerate(deduped, start=1):
        # Estimate end line
        if idx < len(deduped):
            end_line = deduped[idx][0] - 1
        else:
            end_line = min(abs_line + 4, body_start_line + len(body_lines) - 1)
        end_line = max(abs_line, end_line)

        # Extract source text for this child
        child_source = "\n".join(all_file_lines[abs_line - 1: end_line])

        reads, writes = extract_tables(child_source)
        child_stmt_id = f"{parent_stmt_id}_C{idx:02d}"

        # Build partial AST for child (shorter text, more reliable)
        ast_result = build_ast(child_source, subtype) if include_ast else {"parser": "none", "status": "skipped"}

        children.append({
            "statement_id": child_stmt_id,
            "parent_id":    parent_stmt_id,
            "sequence":     idx,
            "type":         btype,
            "subtype":      subtype,
            "object_name":  None,
            "lines": {
                "start": abs_line,
                "end":   end_line,
            },
            "char_offsets": None,   # not tracked for children
            "source_text":  child_source,
            "signature":    {"params": [], "returns": None},
            "reads":        reads,
            "writes":       writes,
            "dml_ops":      extract_dml_ops(child_source),
            "flags":        extract_flags(child_source),
            "calls":        [],     # not extracted at child level
            "ast":          ast_result,
        })

    return children


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — STATE MACHINE PARSER
# Splits a .sql file into top-level statement boundaries (line ranges +
# char offsets), classifies each statement, and returns raw statement structs.
# The AST and semantic field extraction happen after this in Section 6.
# ═══════════════════════════════════════════════════════════════════════════════

class StatementBoundary:
    """Value object: everything the state machine knows about one statement."""
    __slots__ = ("btype", "subtype", "obj_name", "start_line", "end_line",
                 "start_char", "end_char", "accum_lines")

    def __init__(self, btype, subtype, obj_name, start_line, start_char, accum_lines):
        self.btype       = btype
        self.subtype     = subtype
        self.obj_name    = obj_name
        self.start_line  = start_line     # 1-based
        self.end_line    = start_line     # updated as lines accumulate
        self.start_char  = start_char     # byte offset into file content
        self.end_char    = start_char     # updated at emit time
        self.accum_lines = accum_lines    # list of raw line strings


def split_statements(content: str) -> list[StatementBoundary]:
    """
    Run the state machine over file content.
    Returns a list of StatementBoundary objects in document order.

    States
    ──────
    IDLE        Scanning for a new statement.
    COLLECTING  Inside a simple DDL/DML (ends at ; or bare /).
    PLSQL       Inside CREATE OR REPLACE PROCEDURE/FUNCTION/etc.
                BEGIN depth tracked; ends when depth reaches 0 after END;
    ANONYMOUS   Inside a bare BEGIN...END block.

    BEGIN-depth semantics
    ─────────────────────
    Incremented by:  BEGIN  (excluding CASE...BEGIN which doesn't exist in Oracle)
    Decremented by:  END;  / END <name>;  — but NOT by END IF, END LOOP, END CASE
    CASE expressions get a separate case_depth counter so their END CASE doesn't
    incorrectly decrement begin_depth.
    """
    lines     = content.splitlines(keepends=True)   # keep \n for char offset math
    results:  list[StatementBoundary] = []

    state       = "IDLE"
    current: StatementBoundary | None = None
    begin_depth = 0
    case_depth  = 0
    in_ml_cmt   = False

    # Running char offset: position of the start of lines[i] in content
    char_pos = 0

    for i, raw_line in enumerate(lines):
        lineno   = i + 1                              # 1-based
        line_len = len(raw_line)

        # ── Multi-line comment passthrough ────────────────────────────────
        if in_ml_cmt:
            if current:
                current.accum_lines.append(raw_line.rstrip("\n"))
                current.end_line = lineno
                current.end_char = char_pos + line_len
            if _ML_END.search(raw_line):
                in_ml_cmt = False
            char_pos += line_len
            continue

        if _ML_START.search(raw_line) and not _ML_END.search(raw_line):
            in_ml_cmt = True
            if state == "IDLE":
                # Start accumulating even for a standalone comment block;
                # it won't emit because there's no SQL keyword — IDLE will
                # reset when we exit the comment without seeing a trigger.
                pass
            if current:
                current.accum_lines.append(raw_line.rstrip("\n"))
                current.end_line = lineno
                current.end_char = char_pos + line_len
            char_pos += line_len
            continue

        # ── Normalise for pattern matching ────────────────────────────────
        norm = _STRIP_STRINGS.sub("''", raw_line)
        norm = _STRIP_SINGLE_CMT.sub("", norm).strip()

        # ── IDLE ─────────────────────────────────────────────────────────
        if state == "IDLE":
            if not norm:
                char_pos += line_len
                continue

            # Look ahead up to 4 lines to catch multi-line CREATE headers
            lookahead_lines = lines[i: min(i + 4, len(lines))]
            lookahead = " ".join(
                _STRIP_SINGLE_CMT.sub("", _STRIP_STRINGS.sub("''", ln))
                for ln in lookahead_lines
            )

            matched = False

            # Check DDL / PL/SQL triggers
            for pattern, btype, subtype in DDL_TRIGGERS:
                m = pattern.search(lookahead)
                if m:
                    obj = m.group(1).upper() if m.lastindex else ""
                    current = StatementBoundary(
                        btype, subtype, obj, lineno, char_pos,
                        [raw_line.rstrip("\n")]
                    )
                    begin_depth = 0
                    case_depth  = 0
                    state = "PLSQL" if btype == "PLSQL_BLOCK" else "COLLECTING"
                    matched = True
                    break

            if not matched:
                # Standalone DML
                for pattern, btype, subtype in STANDALONE_DML:
                    if pattern.match(norm):
                        obj = ""
                        m2 = pattern.match(norm)
                        if m2 and m2.lastindex:
                            obj = m2.group(1).upper()
                        current = StatementBoundary(
                            btype, subtype, obj, lineno, char_pos,
                            [raw_line.rstrip("\n")]
                        )
                        state = "COLLECTING"
                        matched = True
                        break

            if not matched and re.match(r"^BEGIN\b", norm, re.I):
                # Anonymous block
                current = StatementBoundary(
                    "ANONYMOUS_BLOCK", "ANONYMOUS", "", lineno, char_pos,
                    [raw_line.rstrip("\n")]
                )
                begin_depth = 1
                case_depth  = 0
                state = "ANONYMOUS"

        # ── COLLECTING ────────────────────────────────────────────────────
        elif state == "COLLECTING":
            assert current is not None
            current.accum_lines.append(raw_line.rstrip("\n"))
            current.end_line = lineno
            current.end_char = char_pos + line_len
            if norm.endswith(";") or _SLASH_RE.match(raw_line):
                results.append(current)
                current = None
                state   = "IDLE"

        # ── PLSQL ─────────────────────────────────────────────────────────
        elif state == "PLSQL":
            assert current is not None
            current.accum_lines.append(raw_line.rstrip("\n"))
            current.end_line = lineno
            current.end_char = char_pos + line_len

            case_opens  = len(_CASE_RE.findall(norm))
            case_closes = len(_ENDCASE_RE.findall(norm))
            case_depth  = max(0, case_depth + case_opens - case_closes)

            begin_opens = max(0, len(_BEGIN_RE.findall(norm)) - case_opens)
            begin_depth = max(0, begin_depth + begin_opens)

            end_noop = len(_ENDIF_RE.findall(norm)) + len(_ENDCASE_RE.findall(norm))
            end_real = max(0, len(_END_RE.findall(norm)) - end_noop)
            begin_depth = max(0, begin_depth - end_real)

            if _SLASH_RE.match(raw_line) or (end_real > 0 and begin_depth == 0):
                results.append(current)
                current     = None
                state       = "IDLE"
                begin_depth = 0
                case_depth  = 0

        # ── ANONYMOUS ─────────────────────────────────────────────────────
        elif state == "ANONYMOUS":
            assert current is not None
            current.accum_lines.append(raw_line.rstrip("\n"))
            current.end_line = lineno
            current.end_char = char_pos + line_len

            case_opens  = len(_CASE_RE.findall(norm))
            case_closes = len(_ENDCASE_RE.findall(norm))
            case_depth  = max(0, case_depth + case_opens - case_closes)

            begin_opens = max(0, len(_BEGIN_RE.findall(norm)) - case_opens)
            begin_depth = max(0, begin_depth + begin_opens)

            end_noop = len(_ENDIF_RE.findall(norm)) + len(_ENDCASE_RE.findall(norm))
            end_real = max(0, len(_END_RE.findall(norm)) - end_noop)
            begin_depth = max(0, begin_depth - end_real)

            if _SLASH_RE.match(raw_line) or (end_real > 0 and begin_depth == 0):
                results.append(current)
                current     = None
                state       = "IDLE"
                begin_depth = 0
                case_depth  = 0

        char_pos += line_len

    # Flush unclosed block at EOF
    if current is not None:
        results.append(current)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — FILE PARSER  (orchestrates Sections 3-5 for one file)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_file(
    file_entry: dict,
    sql_dir_override: Path | None,
    default_encoding: str,
    include_ast: bool,
    verbose: bool,
) -> dict:
    """
    Parse one file entry from the inventory manifest.
    Returns a complete file result dict ready for the output artifact.
    """
    file_id      = file_entry["file_id"]
    rel_path     = file_entry["file"]
    abs_path_str = file_entry.get("abs_path", "")
    encoding     = file_entry.get("encoding_used", default_encoding) or default_encoding

    # Resolve file path
    if sql_dir_override:
        abs_path = sql_dir_override / rel_path
    elif abs_path_str:
        abs_path = Path(abs_path_str)
    else:
        abs_path = Path(rel_path)

    # Base result carried from inventory
    result: dict = {
        "file_id":       file_id,
        "file":          rel_path,
        "file_role":     file_entry.get("file_role", "unknown"),
        "complexity":    file_entry.get("complexity", "low"),
        "content_hints": file_entry.get("content_hints", {}),
        "statement_count": 0,
        "parse_error":   None,
        "statements":    [],
    }

    # Read file
    try:
        content = abs_path.read_text(encoding=encoding, errors="replace")
    except Exception as e:
        result["parse_error"] = f"read_error: {e}"
        return result

    if not content.strip():
        return result   # empty file — zero statements, no error

    all_lines = content.splitlines()  # for child source extraction (0-based)

    # Run state machine
    try:
        boundaries = split_statements(content)
    except Exception as e:
        result["parse_error"] = f"state_machine_error: {e}"
        return result

    # Build statement dicts
    statements: list[dict] = []
    for seq, boundary in enumerate(boundaries, start=1):
        stmt_id     = f"{file_id}_S{seq:02d}"
        source_text = "\n".join(boundary.accum_lines)

        reads, writes = extract_tables(source_text)
        sig           = extract_signature(source_text, boundary.subtype)
        flags         = extract_flags(source_text)
        dml_ops       = extract_dml_ops(source_text)
        calls         = extract_calls(source_text)

        # AST
        ast_result = (
            build_ast(source_text, boundary.subtype)
            if include_ast
            else {"parser": "none", "status": "skipped"}
        )

        # Children (PL/SQL and anonymous blocks only)
        children: list[dict] = []
        if boundary.btype in ("PLSQL_BLOCK", "ANONYMOUS_BLOCK"):
            body_lines_list = all_lines[boundary.start_line - 1: boundary.end_line]
            begin_local = next(
                (i for i, ln in enumerate(body_lines_list)
                 if re.search(r"\bBEGIN\b", ln, re.I)),
                0
            )
            body_start_abs = boundary.start_line + begin_local
            inner_text = "\n".join(body_lines_list[begin_local:])
            children = extract_children(
                inner_text, body_start_abs, stmt_id, all_lines, include_ast
            )

        stmt: dict = {
            "statement_id": stmt_id,
            "file_id":      file_id,
            "sequence":     seq,
            "type":         boundary.btype,
            "subtype":      boundary.subtype,
            "object_name":  boundary.obj_name or None,
            "lines": {
                "start": boundary.start_line,
                "end":   boundary.end_line,
            },
            "char_offsets": {
                "start": boundary.start_char,
                "end":   boundary.end_char,
            },
            "source_text": source_text,
            "signature":   sig,
            "reads":       reads,
            "writes":      writes,
            "dml_ops":     dml_ops,
            "flags":       flags,
            "calls":       calls,
            "ast":         ast_result,
            "children":    children,
        }
        statements.append(stmt)

        if verbose:
            child_count = len(children)
            ast_status  = ast_result.get("status", "?")
            print(
                f"    [{stmt_id}] {boundary.subtype:20} "
                f"lines={boundary.start_line}-{boundary.end_line:4}  "
                f"ast={ast_status:8}  children={child_count}",
                file=sys.stderr,
            )

    result["statement_count"] = len(statements)
    result["statements"]      = statements
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — SUMMARY BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_summary(file_results: list[dict]) -> dict:
    total_stmts     = 0
    total_children  = 0
    subtype_counts: dict[str, int] = {}
    ast_status_counts: dict[str, int] = {}
    parse_errors: list[str] = []

    for fr in file_results:
        if fr.get("parse_error"):
            parse_errors.append(fr["file"])
        for stmt in fr.get("statements", []):
            total_stmts += 1
            sub = stmt.get("subtype", "UNKNOWN")
            subtype_counts[sub] = subtype_counts.get(sub, 0) + 1

            ast_s = stmt.get("ast", {}).get("status", "skipped")
            ast_status_counts[ast_s] = ast_status_counts.get(ast_s, 0) + 1

            children = stmt.get("children", [])
            total_children += len(children)

    return {
        "total_files_parsed":     len(file_results),
        "total_files_with_errors": len(parse_errors),
        "total_statements":       total_stmts,
        "total_child_statements": total_children,
        "statements_by_subtype":  subtype_counts,
        "ast_parse_status":       ast_status_counts,
        "files_with_parse_errors": parse_errors,
        "stage2_enrich_hint": {
            "total_statements_to_enrich": total_stmts,
            "recommended_batch_size":     25,
            "estimated_batches":          max(1, total_stmts // 25),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Stage 1: Parse .sql files from inventory manifest → parse-artifact.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python 01_parser.py checkpoints/inventory-artifact.json
  python 01_parser.py checkpoints/inventory-artifact.json -o checkpoints/parse-artifact.json -v
  python 01_parser.py checkpoints/inventory-artifact.json --skip-ast
  python 01_parser.py checkpoints/inventory-artifact.json --sql-dir /alt/path/to/sql
        """,
    )
    ap.add_argument(
        "inventory_json",
        help="Path to inventory-artifact.json produced by Stage 0",
    )
    ap.add_argument(
        "--output", "-o",
        default="checkpoints/parse-artifact.json",
        help="Output path (default: checkpoints/parse-artifact.json)",
    )
    ap.add_argument(
        "--sql-dir",
        default=None,
        help="Override source directory for file reads (optional; uses abs_path from manifest by default)",
    )
    ap.add_argument(
        "--encoding",
        default="utf-8",
        help="Fallback encoding if not recorded per-file in manifest (default: utf-8)",
    )
    ap.add_argument(
        "--skip-ast",
        action="store_true",
        help="Omit AST trees from output (faster, smaller JSON; semantic fields still extracted)",
    )
    ap.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-file and per-statement progress to stderr",
    )
    args = ap.parse_args()

    # ── Load manifest ───────────────────────────────────────────────────────
    manifest_path = Path(args.inventory_json)
    if not manifest_path.exists():
        print(f"ERROR: inventory file not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: could not read manifest: {e}", file=sys.stderr)
        sys.exit(1)

    all_file_entries = manifest.get("files", [])
    # Only process files that Stage 0 marked as readable
    parseable = [f for f in all_file_entries if f.get("status") == "ok"]
    skipped   = len(all_file_entries) - len(parseable)

    sql_dir_override = Path(args.sql_dir).resolve() if args.sql_dir else None
    include_ast      = not args.skip_ast

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.now(timezone.utc).isoformat()

    if not SQLGLOT_AVAILABLE and include_ast:
        print(
            "WARNING: sqlglot not installed. AST will be omitted.\n"
            "         Install with: pip install sqlglot",
            file=sys.stderr,
        )

    if args.verbose:
        print(f"\n[Stage 1: PARSER]", file=sys.stderr)
        print(f"  Manifest   : {manifest_path}", file=sys.stderr)
        print(f"  Files      : {len(parseable)} to parse, {skipped} skipped (empty/unreadable)", file=sys.stderr)
        print(f"  AST        : {'enabled (sqlglot-oracle)' if include_ast and SQLGLOT_AVAILABLE else 'skipped'}", file=sys.stderr)
        print(f"  Output     : {out_path}\n", file=sys.stderr)

    # ── Parse each file ─────────────────────────────────────────────────────
    file_results: list[dict] = []

    for file_entry in parseable:
        fid  = file_entry.get("file_id", "?")
        rel  = file_entry.get("file", "?")

        if args.verbose:
            print(f"  [{fid}] {rel}", file=sys.stderr)

        result = parse_file(
            file_entry      = file_entry,
            sql_dir_override= sql_dir_override,
            default_encoding= args.encoding,
            include_ast     = include_ast,
            verbose         = args.verbose,
        )
        file_results.append(result)

        if not args.verbose and result.get("parse_error"):
            print(f"  WARN parse error in {rel}: {result['parse_error']}", file=sys.stderr)

    # ── Build and write artifact ─────────────────────────────────────────────
    summary = build_summary(file_results)

    artifact = {
        "pipeline_stage":  "01_parser",
        "schema_version":  "1.0",
        "generated_at":    run_ts,
        "source_manifest": str(manifest_path),
        "source_dir":      manifest.get("source_dir", ""),
        "cli_args": {
            "skip_ast":    args.skip_ast,
            "encoding":    args.encoding,
            "sql_dir":     args.sql_dir,
        },
        "summary": summary,
        "files":   file_results,
    }

    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))

    # ── Terminal report ──────────────────────────────────────────────────────
    s = summary
    print(f"[01_parser] Complete.")
    print(f"  Manifest   : {manifest_path}")
    print(f"  Output     : {out_path}")
    print(f"  Files      : {s['total_files_parsed']} parsed, "
          f"{s['total_files_with_errors']} with errors, "
          f"{skipped} skipped from manifest")
    print(f"  Statements : {s['total_statements']} top-level, "
          f"{s['total_child_statements']} child statements")
    print(f"  AST status : {s['ast_parse_status']}")
    print(f"  By subtype : {s['statements_by_subtype']}")
    if s["files_with_parse_errors"]:
        print(f"  ✗ Parse errors : {s['files_with_parse_errors']}")
    print(f"\n  Next step  : python 02_enrich.py {out_path}")


if __name__ == "__main__":
    main()
