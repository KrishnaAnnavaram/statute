#!/usr/bin/env python3
"""
Stage 0: DISCOVER + PARSE  →  inventory-parse-artifact.json
------------------------------------------------------------
Single-pass pipeline entry point. Walks a directory of .sql files, collects
file-level metadata (discover), and structurally parses every file into a
block tree (parse) — all in one read per file, zero LLM calls, zero external
dependencies.

Output: checkpoints/inventory-parse-artifact.json

Usage:
    python 00_discover_parse.py <sql_dir> [options]

    Options:
      --output   -o   Output path (default: checkpoints/inventory-parse-artifact.json)
      --exclude  -e   Additional glob patterns to exclude
      --encoding      File encoding (default: utf-8)
      --verbose  -v   Per-file status to stderr
      --no-default-excludes

What the output contains (per file):
  • file metadata     sha256, size, last_modified, encoding_used
  • line counts       total / code / comment / blank
  • file_role         package | procedure | function | trigger |
                      schema_ddl | migration | seed_data | mixed | unknown
  • complexity        low | medium | high
  • content_hints     sparse dict of boolean feature flags
  • blocks[]          structural block tree — see Block schema below

Block schema:
  block_id            "<filename>::<n>"  (top-level) or "<filename>::<n>.<m>" (child)
  type                DDL | PLSQL_BLOCK | ANONYMOUS_BLOCK | DML | DCL | TCL
  subtype             CREATE_TABLE | PROCEDURE | FUNCTION | PACKAGE | PACKAGE_BODY |
                      TRIGGER | TYPE | CREATE_VIEW | CREATE_INDEX | CREATE_SEQUENCE |
                      ALTER_TABLE | DROP | GRANT | COMMENT | INSERT | UPDATE | DELETE |
                      SELECT | MERGE | COMMIT | ROLLBACK | ANONYMOUS
  object_name         identifier extracted from CREATE … <name> (null for DML/anon)
  lines               [start_line, end_line]  (1-based, inclusive)
  signature           { params: [...], returns: str|null }  for PROCEDURE/FUNCTION
  reads               table/view names referenced in FROM / JOIN / USING
  writes              table/view names in INSERT INTO / UPDATE / DELETE FROM / MERGE INTO
  dml_ops             verbs present: SELECT | INSERT | UPDATE | DELETE | MERGE
  flags               sparse dict: has_cursor, has_commit, has_rollback,
                      has_exception_handling, has_dynamic_sql, has_bulk_collect,
                      has_forall, has_autonomous_txn, has_dbms_calls, has_loop,
                      has_if_block, has_savepoint, has_return
  calls               procedure/function names invoked within this block
  raw_preview         first 8 lines of the block's source (for Stage 2 LLM stubs)
  description         null — filled in by Stage 2 (02_enrich.py)
  children            list of child blocks (same schema, minus children)

Stage 2 note:
  Every block with type PLSQL_BLOCK or ANONYMOUS_BLOCK gets children[] populated
  with the inner DML and control statements. Stage 2 sends only (block_id, subtype,
  object_name, raw_preview) to the LLM — never the full raw SQL — keeping token
  cost proportional to the number of blocks, not file size.
"""

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONSTANTS AND COMPILED PATTERNS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Comment strippers (used for line-count pass only) ──────────────────────
_STRIP_SINGLE = re.compile(r"--[^\n]*")
_STRIP_MULTI  = re.compile(r"/\*.*?\*/", re.S)

# ── Content-hint patterns (file-level feature flags) ──────────────────────
# Sparse: only True values are emitted in JSON.
HINT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("has_plsql_blocks",       re.compile(r"\bBEGIN\b",                                    re.I | re.M)),
    ("has_package",            re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?PACKAGE\b",       re.I | re.M)),
    ("has_procedure",          re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?PROCEDURE\b",     re.I | re.M)),
    ("has_function",           re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?FUNCTION\b",      re.I | re.M)),
    ("has_trigger",            re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?TRIGGER\b",       re.I | re.M)),
    ("has_type",               re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?TYPE\b",          re.I | re.M)),
    ("has_create_table",       re.compile(r"\bCREATE\s+TABLE\b",                           re.I | re.M)),
    ("has_alter_table",        re.compile(r"\bALTER\s+TABLE\b",                            re.I | re.M)),
    ("has_drop",               re.compile(r"\bDROP\s+(TABLE|VIEW|INDEX|SEQUENCE|PROCEDURE|FUNCTION|PACKAGE|TRIGGER|TYPE)\b", re.I | re.M)),
    ("has_create_view",        re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?VIEW\b",          re.I | re.M)),
    ("has_create_index",       re.compile(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b",               re.I | re.M)),
    ("has_create_sequence",    re.compile(r"\bCREATE\s+SEQUENCE\b",                        re.I | re.M)),
    ("has_select",             re.compile(r"\bSELECT\b",                                   re.I | re.M)),
    ("has_insert",             re.compile(r"\bINSERT\s+INTO\b",                            re.I | re.M)),
    ("has_update",             re.compile(r"\bUPDATE\b",                                   re.I | re.M)),
    ("has_delete",             re.compile(r"\bDELETE\s+FROM\b",                            re.I | re.M)),
    ("has_merge",              re.compile(r"\bMERGE\s+INTO\b",                             re.I | re.M)),
    ("has_grants",             re.compile(r"\bGRANT\b",                                    re.I | re.M)),
    ("has_comments_on",        re.compile(r"\bCOMMENT\s+ON\b",                             re.I | re.M)),
    ("has_commit",             re.compile(r"\bCOMMIT\b",                                   re.I | re.M)),
    ("has_rollback",           re.compile(r"\bROLLBACK\b",                                 re.I | re.M)),
    ("has_dbms_calls",         re.compile(r"\bDBMS_\w+\.",                                 re.I | re.M)),
    ("has_utl_calls",          re.compile(r"\bUTL_\w+\.",                                  re.I | re.M)),
    ("has_dynamic_sql",        re.compile(r"\bEXECUTE\s+IMMEDIATE\b",                      re.I | re.M)),
    ("has_cursors",            re.compile(r"\bCURSOR\b",                                   re.I | re.M)),
    ("has_exception_handling", re.compile(r"\bEXCEPTION\b",                                re.I | re.M)),
    ("has_autonomous_txn",     re.compile(r"PRAGMA\s+AUTONOMOUS_TRANSACTION",              re.I | re.M)),
    ("has_bulk_collect",       re.compile(r"\bBULK\s+COLLECT\b",                           re.I | re.M)),
    ("has_forall",             re.compile(r"\bFORALL\b",                                   re.I | re.M)),
    ("has_migration_markers",  re.compile(r"(--\s*migration|--\s*changelog|--\s*changeset|flyway|liquibase)", re.I | re.M)),
]

# ── DDL top-level triggers ─────────────────────────────────────────────────
# Ordered: longest/most-specific patterns first to avoid prefix collisions.
# Each entry: (regex, block_type, subtype)
DDL_TRIGGERS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+PACKAGE\s+BODY\s+(\w+)", re.I),  "PLSQL_BLOCK", "PACKAGE_BODY"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+PACKAGE\s+(\w+)",        re.I),  "PLSQL_BLOCK", "PACKAGE"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+(\w+)",      re.I),  "PLSQL_BLOCK", "PROCEDURE"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(\w+)",       re.I),  "PLSQL_BLOCK", "FUNCTION"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+TRIGGER\s+(\w+)",        re.I),  "PLSQL_BLOCK", "TRIGGER"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+TYPE\s+BODY\s+(\w+)",    re.I),  "PLSQL_BLOCK", "TYPE_BODY"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+TYPE\s+(\w+)",           re.I),  "PLSQL_BLOCK", "TYPE"),
    (re.compile(r"CREATE\s+OR\s+REPLACE\s+VIEW\s+(\w+)",           re.I),  "DDL",         "CREATE_VIEW"),
    (re.compile(r"CREATE\s+UNIQUE\s+INDEX\s+(\w+)",                re.I),  "DDL",         "CREATE_INDEX"),
    (re.compile(r"CREATE\s+INDEX\s+(\w+)",                         re.I),  "DDL",         "CREATE_INDEX"),
    (re.compile(r"CREATE\s+TABLE\s+(\w+)",                         re.I),  "DDL",         "CREATE_TABLE"),
    (re.compile(r"CREATE\s+SEQUENCE\s+(\w+)",                      re.I),  "DDL",         "CREATE_SEQUENCE"),
    (re.compile(r"ALTER\s+TABLE\s+(\w+)",                          re.I),  "DDL",         "ALTER_TABLE"),
    (re.compile(r"DROP\s+\w+\s+(\w+)",                             re.I),  "DDL",         "DROP"),
    (re.compile(r"GRANT\s+\w.*?\s+ON\s+(\w+)",                    re.I),  "DCL",         "GRANT"),
    (re.compile(r"REVOKE\s+\w.*?\s+ON\s+(\w+)",                   re.I),  "DCL",         "REVOKE"),
    (re.compile(r"COMMENT\s+ON\s+(?:TABLE|COLUMN)\s+(\w+)",        re.I),  "DDL",         "COMMENT"),
]

# ── Standalone DML triggers (outside PL/SQL blocks) ───────────────────────
STANDALONE_DML: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^INSERT\s+INTO\s+(\w+)", re.I | re.M), "DML", "INSERT"),
    (re.compile(r"^UPDATE\s+(\w+)",        re.I | re.M), "DML", "UPDATE"),
    (re.compile(r"^DELETE\s+FROM\s+(\w+)", re.I | re.M), "DML", "DELETE"),
    (re.compile(r"^SELECT\b",              re.I | re.M), "DML", "SELECT"),
    (re.compile(r"^MERGE\s+INTO\s+(\w+)", re.I | re.M), "DML", "MERGE"),
    (re.compile(r"^COMMIT\b",             re.I | re.M), "TCL", "COMMIT"),
    (re.compile(r"^ROLLBACK\b",           re.I | re.M), "TCL", "ROLLBACK"),
    (re.compile(r"^TRUNCATE\s+TABLE\s+(\w+)", re.I | re.M), "DDL", "TRUNCATE"),
]

# ── Table-reference extractors (used inside block bodies) ─────────────────
_FROM_TABLES  = re.compile(r"\bFROM\s+(\w+)",              re.I)
_JOIN_TABLES  = re.compile(r"\bJOIN\s+(\w+)",              re.I)
_INSERT_TABLE = re.compile(r"\bINSERT\s+INTO\s+(\w+)",     re.I)
_UPDATE_TABLE = re.compile(r"\bUPDATE\s+(\w+)\s+SET\b",    re.I)
_DELETE_TABLE = re.compile(r"\bDELETE\s+FROM\s+(\w+)",     re.I)
_MERGE_TABLE  = re.compile(r"\bMERGE\s+INTO\s+(\w+)",      re.I)

# ── Procedure/function call detector ─────────────────────────────────────
# Matches IDENTIFIER( patterns that aren't SQL keywords or common builtins.
_SQL_KEYWORDS = frozenset([
    "IF", "ELSIF", "WHILE", "FOR", "LOOP", "CASE", "WHEN", "BEGIN", "END",
    "SELECT", "INSERT", "UPDATE", "DELETE", "FROM", "WHERE", "INTO", "JOIN",
    "AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE", "BETWEEN", "EXISTS",
    "NVL", "NVL2", "DECODE", "COALESCE", "TO_DATE", "TO_CHAR", "TO_NUMBER",
    "SUBSTR", "TRIM", "UPPER", "LOWER", "LENGTH", "INSTR", "REPLACE",
    "ROUND", "TRUNC", "MOD", "ABS", "SIGN", "FLOOR", "CEIL", "SUM", "COUNT",
    "MAX", "MIN", "AVG", "SYSDATE", "SYSTIMESTAMP", "NEXTVAL", "CURRVAL",
    "ROWNUM", "ROWID", "LEVEL", "PRIOR", "CONNECT",
])
_PROC_CALL = re.compile(r"\b([A-Z][A-Z0-9_]*)\s*\(", re.I)

# ── Parameter signature extractor ─────────────────────────────────────────
_PARAM_BLOCK  = re.compile(
    r"(?:PROCEDURE|FUNCTION)\s+\w+\s*\(([^)]*)\)",
    re.I | re.S,
)
_RETURN_TYPE  = re.compile(r"\bRETURN\s+(\w+(?:\s*\(\s*\d+\s*(?:,\s*\d+\s*)?\))?)", re.I)
_SINGLE_PARAM = re.compile(
    r"(\w+)\s+(IN\s+OUT|IN|OUT)\s+(\w+(?:\s*\(\s*\d+\s*(?:,\s*\d+\s*)?\))?)"
    r"(?:\s+DEFAULT\s+[^,)]+)?",
    re.I,
)

# ── Block-level flags ─────────────────────────────────────────────────────
FLAG_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("has_cursor",             re.compile(r"\bCURSOR\b",                   re.I)),
    ("has_commit",             re.compile(r"\bCOMMIT\b",                   re.I)),
    ("has_rollback",           re.compile(r"\bROLLBACK\b",                 re.I)),
    ("has_exception_handling", re.compile(r"\bEXCEPTION\b",               re.I)),
    ("has_dynamic_sql",        re.compile(r"\bEXECUTE\s+IMMEDIATE\b",      re.I)),
    ("has_bulk_collect",       re.compile(r"\bBULK\s+COLLECT\b",           re.I)),
    ("has_forall",             re.compile(r"\bFORALL\b",                   re.I)),
    ("has_autonomous_txn",     re.compile(r"PRAGMA\s+AUTONOMOUS_TRANSACTION", re.I)),
    ("has_dbms_calls",         re.compile(r"\bDBMS_\w+\.",                 re.I)),
    ("has_loop",               re.compile(r"\bLOOP\b",                     re.I)),
    ("has_if_block",           re.compile(r"\bIF\b",                       re.I)),
    ("has_savepoint",          re.compile(r"\bSAVEPOINT\b",               re.I)),
    ("has_return",             re.compile(r"\bRETURN\b",                   re.I)),
]

# ── Inner-child patterns (run on PL/SQL block body text) ─────────────────
# Each entry: (regex applied to stripped body, block_type, subtype, group_for_object)
INNER_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bSELECT\b.*?\bINTO\b",                  re.I | re.S), "DML", "SELECT_INTO"),
    (re.compile(r"\bINSERT\s+INTO\s+\w+",                  re.I),        "DML", "INSERT"),
    (re.compile(r"\bUPDATE\s+\w+\s+SET\b",                 re.I),        "DML", "UPDATE"),
    (re.compile(r"\bDELETE\s+FROM\s+\w+",                  re.I),        "DML", "DELETE"),
    (re.compile(r"\bMERGE\s+INTO\s+\w+",                   re.I),        "DML", "MERGE"),
    (re.compile(r"\bEXECUTE\s+IMMEDIATE\b",                re.I),        "DML", "DYNAMIC_SQL"),
    (re.compile(r"\bIF\b.+?\bTHEN\b",                      re.I | re.S), "CONTROL", "IF_BLOCK"),
    (re.compile(r"\bFOR\s+\w+\s+IN\b",                     re.I),        "CONTROL", "FOR_LOOP"),
    (re.compile(r"\bWHILE\b.+?\bLOOP\b",                   re.I | re.S), "CONTROL", "WHILE_LOOP"),
    (re.compile(r"\bCURSOR\s+\w+\s+IS\b",                  re.I),        "DECL",    "CURSOR_DECL"),
    (re.compile(r"\bEXCEPTION\b",                          re.I),        "CONTROL", "EXCEPTION_HANDLER"),
    (re.compile(r"\bDBMS_\w+\.\w+\s*\(",                   re.I),        "BUILTIN",  "DBMS_CALL"),
    (re.compile(r"\bCOMMIT\b",                             re.I),        "TCL",     "COMMIT"),
    (re.compile(r"\bROLLBACK\b",                           re.I),        "TCL",     "ROLLBACK"),
    (re.compile(r"\bSAVEPOINT\b",                          re.I),        "TCL",     "SAVEPOINT"),
]

# ── Exclusion defaults ────────────────────────────────────────────────────
DEFAULT_EXCLUDES: list[str] = [
    "*.bak", "*.tmp", "*_backup.*", "*_old.*",
    ".git/*", "node_modules/*", "__pycache__/*",
]

# Tokens that are never object names (false-positive guard for table extraction)
_NON_TABLE_NAMES = frozenset([
    "SELECT", "INTO", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER",
    "OUTER", "FULL", "CROSS", "ON", "AND", "OR", "NOT", "IN", "IS",
    "NULL", "LIKE", "BETWEEN", "EXISTS", "GROUP", "ORDER", "BY", "HAVING",
    "UNION", "ALL", "DISTINCT", "AS", "WITH", "CASE", "WHEN", "THEN",
    "ELSE", "END", "SET", "VALUES", "RETURNING", "THE", "A", "AN",
])


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — UTILITY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_safe(path: Path, encoding: str) -> tuple[str | None, str | None]:
    """Returns (content, warning_or_None). Falls back to latin-1."""
    try:
        return path.read_text(encoding=encoding), None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1"), \
                   f"encoding_fallback:latin-1 (primary {encoding!r} failed)"
        except Exception as e:
            return None, f"read_error:{e}"
    except Exception as e:
        return None, f"read_error:{e}"


def line_counts(content: str) -> dict[str, int]:
    raw   = content.splitlines()
    total = len(raw)
    stripped = _STRIP_SINGLE.sub("", _STRIP_MULTI.sub("", content)).splitlines()
    code  = sum(1 for ln in stripped if ln.strip())
    blank = sum(1 for ln in raw if not ln.strip())
    return {
        "total_lines":   total,
        "code_lines":    code,
        "comment_lines": max(0, total - code - blank),
        "blank_lines":   blank,
    }


def content_hints(content: str) -> dict[str, bool]:
    """Sparse dict — only True values kept to reduce JSON size."""
    return {k: True for k, p in HINT_PATTERNS if p.search(content)}


def file_role(hints: dict[str, bool], rel_path: str) -> str:
    name = Path(rel_path).name.lower()
    if re.match(r"v\d+__", name) or "changelog" in name or hints.get("has_migration_markers"):
        return "migration"
    if hints.get("has_package"):    return "package"
    if hints.get("has_procedure") and not hints.get("has_function"): return "procedure"
    if hints.get("has_function")  and not hints.get("has_procedure"): return "function"
    if hints.get("has_trigger"):    return "trigger"
    ddl = hints.get("has_create_table") or hints.get("has_alter_table") \
       or hints.get("has_create_view")  or hints.get("has_create_sequence") \
       or hints.get("has_create_index")
    dml = hints.get("has_insert") or hints.get("has_update") \
       or hints.get("has_delete") or hints.get("has_select")
    plsql = hints.get("has_plsql_blocks")
    if ddl and not dml and not plsql:  return "schema_ddl"
    if dml and not ddl and not plsql:  return "seed_data"
    if ddl or dml or plsql:            return "mixed"
    return "unknown"


def complexity(hints: dict[str, bool], lc: dict[str, int]) -> str:
    high = sum([
        bool(hints.get("has_dynamic_sql")),
        bool(hints.get("has_bulk_collect")),
        bool(hints.get("has_forall")),
        bool(hints.get("has_autonomous_txn")),
        bool(hints.get("has_dbms_calls")),
        lc["code_lines"] > 150,
    ])
    medium = any([
        hints.get("has_plsql_blocks"),
        hints.get("has_cursors"),
        hints.get("has_exception_handling"),
        lc["code_lines"] > 40,
    ])
    if high >= 2:   return "high"
    if medium:      return "medium"
    return "low"


def should_exclude(rel_path: str, patterns: list[str]) -> bool:
    name = Path(rel_path).name
    return any(fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(name, p) for p in patterns)


def extract_tables(text: str, writes_only: bool = False) -> tuple[list[str], list[str]]:
    """Returns (reads, writes) — deduplicated, uppercased, non-keyword names."""
    def clean(names):
        return sorted({n.upper() for n in names if n.upper() not in _NON_TABLE_NAMES and len(n) > 1})

    reads  = _FROM_TABLES.findall(text) + _JOIN_TABLES.findall(text)
    writes = (_INSERT_TABLE.findall(text) + _UPDATE_TABLE.findall(text)
              + _DELETE_TABLE.findall(text) + _MERGE_TABLE.findall(text))
    return clean(reads), clean(writes)


def extract_dml_ops(text: str) -> list[str]:
    ops = []
    if re.search(r"\bSELECT\b", text, re.I): ops.append("SELECT")
    if re.search(r"\bINSERT\b", text, re.I):  ops.append("INSERT")
    if re.search(r"\bUPDATE\b", text, re.I):  ops.append("UPDATE")
    if re.search(r"\bDELETE\b", text, re.I):  ops.append("DELETE")
    if re.search(r"\bMERGE\b",  text, re.I):  ops.append("MERGE")
    return ops


def extract_flags(text: str) -> dict[str, bool]:
    return {k: True for k, p in FLAG_PATTERNS if p.search(text)}


def extract_calls(text: str) -> list[str]:
    """
    Heuristic: find IDENTIFIER( patterns, exclude SQL keywords and
    single-word builtins. What remains is likely a procedure/function call.
    """
    candidates = _PROC_CALL.findall(text)
    seen = set()
    result = []
    for name in candidates:
        up = name.upper()
        if up not in _SQL_KEYWORDS and up not in seen:
            seen.add(up)
            result.append(up)
    return sorted(result)


def extract_signature(block_text: str, subtype: str) -> dict:
    sig: dict = {"params": [], "returns": None}
    if subtype not in ("PROCEDURE", "FUNCTION"):
        return sig

    m = _PARAM_BLOCK.search(block_text)
    if m:
        param_str = m.group(1)
        for pm in _SINGLE_PARAM.finditer(param_str):
            sig["params"].append({
                "name":      pm.group(1),
                "direction": pm.group(2).upper().replace(" ", "_"),
                "datatype":  pm.group(3).upper(),
            })

    if subtype == "FUNCTION":
        # RETURN clause is outside the param list, in the header
        rm = _RETURN_TYPE.search(block_text)
        if rm:
            sig["returns"] = rm.group(1).upper()

    return sig


def raw_preview(lines: list[str], start: int, end: int, n: int = 8) -> str:
    """First n non-blank lines of the block, for Stage 2 LLM stubs."""
    segment = lines[start:end + 1]
    non_blank = [ln for ln in segment if ln.strip()]
    return "\n".join(non_blank[:n])


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CHILD BLOCK EXTRACTOR
# Runs a second pass on the body text of a PLSQL_BLOCK or ANONYMOUS_BLOCK.
# Finds inner DML/control statements and records their approximate line ranges.
# ═══════════════════════════════════════════════════════════════════════════════

def extract_children(
    body_text: str,
    body_start_line: int,
    parent_block_id: str,
    file_lines: list[str],
) -> list[dict]:
    """
    Scan a PL/SQL body for inner DML and control statements.
    Returns a list of child block dicts.

    Strategy:
    - Run each INNER_PATTERN against the body text.
    - For each match, find which absolute line it falls on by counting
      newlines up to the match offset.
    - Deduplicate: if two patterns match within 2 lines of each other,
      keep the more specific one (longer subtype name wins).
    - Assign sequential child IDs: <parent_id>.<n>
    """
    body_lines = body_text.splitlines()
    # Map: character offset → line index within body
    offset_to_line: list[int] = []
    for i, ln in enumerate(body_lines):
        offset_to_line.extend([i] * (len(ln) + 1))  # +1 for \n

    hits: list[tuple[int, str, str]] = []  # (abs_line, type, subtype)

    for pattern, btype, subtype in INNER_PATTERNS:
        for m in pattern.finditer(body_text):
            char_offset = m.start()
            if char_offset < len(offset_to_line):
                body_line_idx = offset_to_line[char_offset]
            else:
                body_line_idx = len(body_lines) - 1
            abs_line = body_start_line + body_line_idx
            hits.append((abs_line, btype, subtype))

    # Sort by line, then dedup within a 2-line window (keep first hit per window)
    hits.sort(key=lambda h: h[0])
    deduped: list[tuple[int, str, str]] = []
    last_line = -99
    for abs_line, btype, subtype in hits:
        if abs_line - last_line > 2:
            deduped.append((abs_line, btype, subtype))
            last_line = abs_line

    # Build child dicts
    children = []
    for idx, (abs_line, btype, subtype) in enumerate(deduped, start=1):
        # Estimate end line: next hit's line - 1, or abs_line + 2 as fallback
        if idx < len(deduped):
            end_line = deduped[idx][0] - 1
        else:
            end_line = min(abs_line + 4, body_start_line + len(body_lines) - 1)
        end_line = max(abs_line, end_line)

        child_text = "\n".join(file_lines[abs_line - 1: end_line])
        reads, writes = extract_tables(child_text)

        children.append({
            "block_id":     f"{parent_block_id}.{idx}",
            "parent_block": parent_block_id,
            "type":         btype,
            "subtype":      subtype,
            "lines":        [abs_line, end_line],
            "reads":        reads,
            "writes":       writes,
            "dml_ops":      extract_dml_ops(child_text),
            "flags":        extract_flags(child_text),
            "raw_preview":  child_text[:300].strip(),
            "description":  None,
        })

    return children


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — MAIN STATE MACHINE PARSER
# ═══════════════════════════════════════════════════════════════════════════════

class SQLStateParser:
    """
    Line-by-line state machine that tokenises a .sql file into top-level blocks.

    States
    ──────
    IDLE          Looking for the start of a new statement.
    COLLECTING    Accumulating lines of a DDL/DML statement (ends at semicolon
                  or / on its own line, without PL/SQL nesting).
    PLSQL         Inside a PL/SQL block (CREATE OR REPLACE PROCEDURE/FUNCTION/
                  PACKAGE/TRIGGER/TYPE).  Nesting tracked by BEGIN depth.
    ANONYMOUS     Inside a bare BEGIN...END block (no CREATE wrapper).

    BEGIN depth tracking
    ────────────────────
    PL/SQL allows nested BEGIN...END pairs (exception handlers, nested blocks,
    inner cursors).  We track an integer depth:
      - Entering PLSQL state sets depth=0 (we haven't seen BEGIN yet).
      - Seeing BEGIN increments depth.
      - Seeing END [name]; or END; decrements depth.
      - When depth reaches 0 after a decrement, the block is complete.

    The tricky case is PACKAGE BODY, which contains multiple nested
    PROCEDURE/FUNCTION definitions each with their own BEGIN/END — those
    nested definitions are NOT split out as top-level blocks; the whole
    PACKAGE BODY is one top-level block, and its inner procedures become
    child blocks via extract_children().

    Comment handling
    ────────────────
    Single-line (--) comments are stripped from each line before pattern
    matching.  Multi-line (/* */) comments are tracked with a flag.
    String literals ('...') are stripped to prevent false matches on keywords
    inside strings.

    Slash terminator
    ────────────────
    Oracle SQL*Plus uses a bare / on its own line to terminate and execute a
    PL/SQL block.  We treat this as an end-of-block signal equivalent to the
    final END; when we're in PLSQL/ANONYMOUS state and depth==0.
    """

    # Words that increment BEGIN depth
    _BEGIN_RE  = re.compile(r"\bBEGIN\b", re.I)
    # Words that increment BEGIN depth from CASE expressions
    _CASE_RE   = re.compile(r"\bCASE\b",  re.I)
    # END with optional label and semicolon — decrements depth
    _END_RE    = re.compile(r"\bEND\b\s*(?:\w+\s*)?;", re.I)
    # END CASE specifically (CASE/END CASE pair must be balanced separately)
    _ENDCASE_RE = re.compile(r"\bEND\s+CASE\b", re.I)
    # END IF / END LOOP — these do NOT affect BEGIN depth
    _ENDIF_RE  = re.compile(r"\bEND\s+(?:IF|LOOP)\b", re.I)
    # Bare / on its own line (SQL*Plus block terminator)
    _SLASH_RE  = re.compile(r"^\s*/\s*$")
    # Strip string literals to avoid keyword false-positives inside strings
    _STR_STRIP = re.compile(r"'(?:[^']|'')*'")
    # Strip inline comments
    _CMT_STRIP = re.compile(r"--.*$", re.M)
    # Multi-line comment start/end
    _ML_START  = re.compile(r"/\*")
    _ML_END    = re.compile(r"\*/")

    def __init__(self, rel_path: str):
        self.rel_path   = rel_path
        self.file_stem  = Path(rel_path).name
        self._blocks: list[dict] = []
        self._counter   = 0       # top-level block index

    # ── Public entry point ──────────────────────────────────────────────────

    def parse(self, content: str) -> list[dict]:
        lines = content.splitlines()
        self._lines = lines          # kept for raw_preview
        self._blocks = []
        self._counter = 0

        # State
        state           = "IDLE"
        block_type      = ""
        block_subtype   = ""
        block_obj       = ""
        block_start     = 0         # 1-based
        accum: list[str] = []
        begin_depth     = 0
        case_depth      = 0         # track CASE/END CASE separately
        in_ml_comment   = False

        i = 0
        while i < len(lines):
            raw_line = lines[i]
            lineno   = i + 1        # 1-based

            # ── Multi-line comment tracking ────────────────────────────────
            if in_ml_comment:
                accum.append(raw_line)
                if self._ML_END.search(raw_line):
                    in_ml_comment = False
                i += 1
                continue

            if self._ML_START.search(raw_line) and not self._ML_END.search(raw_line):
                in_ml_comment = True
                accum.append(raw_line)
                if state == "IDLE":
                    block_start = lineno
                i += 1
                continue

            # ── Normalised line for pattern matching ──────────────────────
            # Strip string literals first, then comments.
            # Work on a copy — raw_line is preserved for output.
            norm = self._STR_STRIP.sub("''", raw_line)
            norm = self._CMT_STRIP.sub("",   norm).strip()

            # ── IDLE: look for a new statement ────────────────────────────
            if state == "IDLE":
                if not norm:
                    i += 1
                    continue

                # Check DDL/PL/SQL triggers on accumulated look-ahead.
                # We join up to 4 lines to handle multi-line CREATE headers.
                lookahead = " ".join(
                    self._CMT_STRIP.sub("", self._STR_STRIP.sub("''", lines[j]))
                    for j in range(i, min(i + 4, len(lines)))
                )

                matched = False
                for pattern, btype, subtype in DDL_TRIGGERS:
                    m = pattern.search(lookahead)
                    if m:
                        block_type    = btype
                        block_subtype = subtype
                        block_obj     = m.group(1).upper() if m.lastindex else ""
                        block_start   = lineno
                        accum         = [raw_line]
                        begin_depth   = 0
                        case_depth    = 0

                        if btype == "PLSQL_BLOCK":
                            state = "PLSQL"
                        else:
                            state = "COLLECTING"
                        matched = True
                        break

                if not matched:
                    # Check standalone DML
                    for pattern, btype, subtype in STANDALONE_DML:
                        if pattern.match(norm):
                            block_type    = btype
                            block_subtype = subtype
                            block_obj     = ""
                            block_start   = lineno
                            accum         = [raw_line]
                            state         = "COLLECTING"
                            matched       = True
                            break

                if not matched:
                    # Anonymous block: bare BEGIN
                    if re.match(r"^BEGIN\b", norm, re.I):
                        block_type    = "ANONYMOUS_BLOCK"
                        block_subtype = "ANONYMOUS"
                        block_obj     = ""
                        block_start   = lineno
                        accum         = [raw_line]
                        begin_depth   = 1
                        case_depth    = 0
                        state         = "ANONYMOUS"

            # ── COLLECTING: simple statement, ends at ; or / ───────────────
            elif state == "COLLECTING":
                accum.append(raw_line)
                if norm.endswith(";") or self._SLASH_RE.match(raw_line):
                    self._emit(block_type, block_subtype, block_obj,
                               block_start, lineno, accum)
                    state = "IDLE"
                    accum = []

            # ── PLSQL: PL/SQL named block, depth-tracked ───────────────────
            elif state == "PLSQL":
                accum.append(raw_line)

                # Count CASE/END CASE to avoid false END decrements
                case_opens  = len(self._CASE_RE.findall(norm))
                case_closes = len(self._ENDCASE_RE.findall(norm))
                case_depth  = max(0, case_depth + case_opens - case_closes)

                # Count BEGIN opens (exclude CASE)
                begin_opens = len(self._BEGIN_RE.findall(norm)) - case_opens
                begin_depth = max(0, begin_depth + begin_opens)

                # Count END closes — but not END IF / END LOOP / END CASE
                # (those are handled by their own openers)
                end_noop = self._ENDIF_RE.findall(norm) + self._ENDCASE_RE.findall(norm)
                end_total = len(self._END_RE.findall(norm))
                end_real  = max(0, end_total - len(end_noop))
                begin_depth = max(0, begin_depth - end_real)

                # Slash terminator: always ends the block
                slash = self._SLASH_RE.match(raw_line)

                if slash or (end_real > 0 and begin_depth == 0):
                    end_line = lineno
                    self._emit(block_type, block_subtype, block_obj,
                               block_start, end_line, accum)
                    state = "IDLE"
                    accum = []
                    begin_depth = 0
                    case_depth  = 0

            # ── ANONYMOUS: bare BEGIN...END block ─────────────────────────
            elif state == "ANONYMOUS":
                accum.append(raw_line)

                case_opens  = len(self._CASE_RE.findall(norm))
                case_closes = len(self._ENDCASE_RE.findall(norm))
                case_depth  = max(0, case_depth + case_opens - case_closes)

                begin_opens = len(self._BEGIN_RE.findall(norm)) - case_opens
                begin_depth = max(0, begin_depth + begin_opens)

                end_noop  = self._ENDIF_RE.findall(norm) + self._ENDCASE_RE.findall(norm)
                end_total = len(self._END_RE.findall(norm))
                end_real  = max(0, end_total - len(end_noop))
                begin_depth = max(0, begin_depth - end_real)

                slash = self._SLASH_RE.match(raw_line)

                if slash or (end_real > 0 and begin_depth == 0):
                    self._emit("ANONYMOUS_BLOCK", "ANONYMOUS", "",
                               block_start, lineno, accum)
                    state = "IDLE"
                    accum = []
                    begin_depth = 0
                    case_depth  = 0

            i += 1

        # Flush any unclosed block at EOF (common in files without / terminator)
        if state != "IDLE" and accum:
            self._emit(block_type, block_subtype, block_obj,
                       block_start, len(lines), accum)

        return self._blocks

    # ── Block emitter ───────────────────────────────────────────────────────

    def _emit(
        self,
        btype: str, subtype: str, obj_name: str,
        start: int, end: int,
        accum: list[str],
    ) -> None:
        self._counter += 1
        block_id = f"{self.file_stem}::{self._counter}"
        text     = "\n".join(accum)

        reads, writes = extract_tables(text)
        sig           = extract_signature(text, subtype)
        flags         = extract_flags(text)
        dml_ops       = extract_dml_ops(text)
        calls         = extract_calls(text)
        preview       = raw_preview(self._lines, start - 1, end - 1, n=8)

        # Children: only for PL/SQL and anonymous blocks
        children: list[dict] = []
        if btype in ("PLSQL_BLOCK", "ANONYMOUS_BLOCK"):
            # Body text starts after the first BEGIN line
            body_lines_list = self._lines[start - 1: end]
            body_text = "\n".join(body_lines_list)
            # Find the line index of the first BEGIN within the block
            begin_local = next(
                (i for i, ln in enumerate(body_lines_list)
                 if re.search(r"\bBEGIN\b", ln, re.I)),
                0
            )
            body_start_abs = start + begin_local
            inner_text = "\n".join(body_lines_list[begin_local:])
            children = extract_children(inner_text, body_start_abs, block_id, self._lines)

        block: dict = {
            "block_id":    block_id,
            "type":        btype,
            "subtype":     subtype,
            "object_name": obj_name or None,
            "lines":       [start, end],
            "signature":   sig,
            "reads":       reads,
            "writes":      writes,
            "dml_ops":     dml_ops,
            "flags":       flags,
            "calls":       calls,
            "raw_preview": preview,
            "description": None,
            "children":    children,
        }
        self._blocks.append(block)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — FILE PROCESSOR (discover + parse fused)
# ═══════════════════════════════════════════════════════════════════════════════

def process_file(abs_path: Path, sql_dir: Path, encoding: str) -> dict:
    """
    Single-read processor. Returns a complete file entry with both discovery
    metadata and parsed block tree.
    """
    rel_path = str(abs_path.relative_to(sql_dir))
    stat     = abs_path.stat()

    entry: dict = {
        "file":          rel_path,
        "abs_path":      str(abs_path),
        "size_bytes":    stat.st_size,
        "sha256":        sha256_file(abs_path),
        "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }

    if stat.st_size == 0:
        entry.update({
            "status": "empty", "warnings": ["File is empty"],
            "line_counts": {"total_lines":0,"code_lines":0,"comment_lines":0,"blank_lines":0},
            "file_role": "unknown", "complexity": "low",
            "encoding_used": encoding, "content_hints": {}, "blocks": [],
        })
        return entry

    content, warn = read_safe(abs_path, encoding)
    if content is None:
        entry.update({"status": "unreadable", "error": warn, "warnings": [warn], "blocks": []})
        return entry

    lc      = line_counts(content)
    hints   = content_hints(content)
    role    = file_role(hints, rel_path)
    cx      = complexity(hints, lc)
    enc_used = "latin-1" if (warn and "latin-1" in warn) else encoding

    warnings = [warn] if warn else []
    if lc["code_lines"] == 0 and stat.st_size > 0:
        warnings.append("File has no detectable SQL code lines (comments/whitespace only)")

    # ── Parse ──────────────────────────────────────────────────────────────
    blocks: list[dict] = []
    parse_error: str | None = None
    if lc["code_lines"] > 0:
        try:
            parser = SQLStateParser(rel_path)
            blocks = parser.parse(content)
        except Exception as e:
            parse_error = f"parse_error:{e}"
            warnings.append(parse_error)

    entry.update({
        "status":        "ok",
        "line_counts":   lc,
        "file_role":     role,
        "complexity":    cx,
        "encoding_used": enc_used,
        "content_hints": hints,
        "warnings":      warnings,
        "parse_error":   parse_error,
        "blocks":        blocks,
    })
    return entry


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SUMMARY BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_summary(file_entries: list[dict], excluded: int) -> dict:
    ok_entries  = [e for e in file_entries if e.get("status") == "ok"]
    role_counts: dict[str, int] = {}
    cx_counts:   dict[str, int] = {}
    type_counts: dict[str, int] = {}
    total_lines = total_code = total_blocks = total_children = 0
    codebase_hints: dict[str, int] = {}

    for e in ok_entries:
        role_counts[e.get("file_role","unknown")] = role_counts.get(e.get("file_role","unknown"), 0) + 1
        cx   = e.get("complexity","low")
        cx_counts[cx] = cx_counts.get(cx, 0) + 1
        lc   = e.get("line_counts", {})
        total_lines += lc.get("total_lines", 0)
        total_code  += lc.get("code_lines",  0)

        for b in e.get("blocks", []):
            total_blocks += 1
            sub = b.get("subtype","?")
            type_counts[sub] = type_counts.get(sub, 0) + 1
            total_children += len(b.get("children", []))

        for hint_key in e.get("content_hints", {}):
            codebase_hints[hint_key] = codebase_hints.get(hint_key, 0) + 1

    high_cx = [e["file"] for e in ok_entries if e.get("complexity") == "high"]
    warnings = [{"file": e["file"], "warnings": e["warnings"]}
                for e in file_entries if e.get("warnings")]
    unreadable = [e["file"] for e in file_entries if e.get("status") == "unreadable"]
    parse_errors = [e["file"] for e in ok_entries if e.get("parse_error")]

    return {
        "total_files_found":      len(file_entries) + excluded,
        "total_files_included":   len(file_entries),
        "total_files_excluded":   excluded,
        "total_files_ok":         len(ok_entries),
        "total_files_empty":      sum(1 for e in file_entries if e.get("status") == "empty"),
        "total_files_unreadable": len(unreadable),
        "total_files_parse_error": len(parse_errors),
        "total_lines":            total_lines,
        "total_code_lines":       total_code,
        "total_blocks":           total_blocks,
        "total_child_statements": total_children,
        "files_by_role":          role_counts,
        "files_by_complexity":    cx_counts,
        "blocks_by_subtype":      type_counts,
        "codebase_features":      codebase_hints,
        "high_complexity_files":  high_cx,
        "files_with_warnings":    warnings,
        "unreadable_files":       unreadable,
        "parse_error_files":      parse_errors,
        "stage2_enrich_hint": {
            "total_blocks_to_enrich": total_blocks,
            "recommended_batch_size": 25,
            "estimated_batches":      max(1, total_blocks // 25),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — DIRECTORY WALKER
# ═══════════════════════════════════════════════════════════════════════════════

def walk(
    sql_dir: Path,
    exclude_patterns: list[str],
    encoding: str,
    verbose: bool,
) -> tuple[list[dict], int]:
    all_files = sorted(sql_dir.rglob("*.sql"))
    entries: list[dict] = []
    excluded = 0

    for abs_path in all_files:
        rel = str(abs_path.relative_to(sql_dir))
        if should_exclude(rel, exclude_patterns):
            excluded += 1
            if verbose:
                print(f"  [excluded ] {rel}", file=sys.stderr)
            continue

        entry = process_file(abs_path, sql_dir, encoding)
        entries.append(entry)

        if verbose:
            status  = entry.get("status","?")
            role    = entry.get("file_role","")
            cx      = entry.get("complexity","")
            lines   = entry.get("line_counts",{}).get("total_lines",0)
            nblocks = len(entry.get("blocks",[]))
            warn    = f"  ⚠ {'; '.join(entry['warnings'])}" if entry.get("warnings") else ""
            print(
                f"  [{status:10}] {rel:55} role={role:12} cx={cx:6} "
                f"lines={lines:4} blocks={nblocks}{warn}",
                file=sys.stderr,
            )

    return entries, excluded


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Stage 0: Discover + Parse .sql files → inventory-parse-artifact.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python 00_discover_parse.py ./sql_codebase
  python 00_discover_parse.py ./sql_codebase --output checkpoints/inventory-parse-artifact.json -v
  python 00_discover_parse.py ./sql_codebase --exclude "legacy/*" "*_v1*" --encoding cp1252
        """,
    )
    ap.add_argument("sql_dir",  help="Root directory of .sql files (recursive)")
    ap.add_argument("--output", "-o", default="checkpoints/inventory-parse-artifact.json")
    ap.add_argument("--exclude", "-e", nargs="+", default=[], metavar="PATTERN")
    ap.add_argument("--no-default-excludes", action="store_true")
    ap.add_argument("--encoding", default="utf-8")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    sql_dir = Path(args.sql_dir).resolve()
    if not sql_dir.exists() or not sql_dir.is_dir():
        print(f"ERROR: not a directory: {sql_dir}", file=sys.stderr)
        sys.exit(1)

    excludes = [] if args.no_default_excludes else list(DEFAULT_EXCLUDES)
    excludes.extend(args.exclude)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.now(timezone.utc).isoformat()

    if args.verbose:
        print(f"\n[Stage 0: DISCOVER + PARSE]  {sql_dir}", file=sys.stderr)
        print(f"Excludes : {excludes}", file=sys.stderr)
        print(f"Encoding : {args.encoding}\n", file=sys.stderr)

    entries, excluded = walk(sql_dir, excludes, args.encoding, args.verbose)
    summary = build_summary(entries, excluded)

    artifact = {
        "pipeline_stage": "00_discover_parse",
        "schema_version": "1.1",
        "generated_at":   run_ts,
        "source_dir":     str(sql_dir),
        "cli_args": {
            "encoding":        args.encoding,
            "exclude_patterns": excludes,
        },
        "summary": summary,
        "files":   entries,
    }

    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))

    # ── Terminal report ────────────────────────────────────────────────────
    s = summary
    print(f"[00_discover_parse] Complete.")
    print(f"  Source     : {sql_dir}")
    print(f"  Output     : {out_path}")
    print(f"  Files      : {s['total_files_found']} found, "
          f"{s['total_files_excluded']} excluded, "
          f"{s['total_files_ok']} parsed OK, "
          f"{s['total_files_empty']} empty, "
          f"{s['total_files_unreadable']} unreadable, "
          f"{s['total_files_parse_error']} parse errors")
    print(f"  Lines      : {s['total_lines']} total, {s['total_code_lines']} code")
    print(f"  Blocks     : {s['total_blocks']} top-level, {s['total_child_statements']} child statements")
    print(f"  Roles      : {s['files_by_role']}")
    print(f"  Complexity : {s['files_by_complexity']}")
    print(f"  Block types: {s['blocks_by_subtype']}")
    if s["high_complexity_files"]:
        print(f"  ⚠ High-complexity: {s['high_complexity_files']}")
    if s["parse_error_files"]:
        print(f"  ✗ Parse errors  : {s['parse_error_files']}")
    print(f"\n  Next step  : python 02_enrich.py {out_path}")


if __name__ == "__main__":
    main()
