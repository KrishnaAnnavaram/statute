#!/usr/bin/env python3
"""
Stage 0: INVENTORY
-----------------
Walks a directory tree of .sql files and produces inventory-artifact.json — a complete
file-level inventory with metadata needed by all downstream pipeline stages.

Zero LLM calls. Zero external dependencies. Pure Python stdlib only.

Output: output/inventory/<run_version>/inventory-artifact.json (new timestamped
        folder every run; output/inventory/latest.json points at the most
        recent successful run). Pass --output <path> for an exact fixed path
        instead (no versioning; used by the test suite).

Usage:
    python .claude/scripts/00_inventory.py <sql_dir> [--output <path> | --output-root <dir>]
                          [--exclude <pattern> ...]
                          [--encoding <enc>] [--no-content-hints] [--verbose]
    (run from the repo root — output paths are relative to the current
    working directory, not to this script's location)

Claude Code invocation:
    When a user provides a directory of .sql files and asks to begin the
    SQL → BRD pipeline, run this script first. Its output is the required
    input for 01_parse.py.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Content-hint patterns
# Lightweight regex scan of raw file text to detect what flavours of SQL
# are present. This is NOT a parser — it does not understand nesting or
# semantics. It only answers: "does this file contain X at all?"
# The real parser (01_parse.py) does the structural work.
# ---------------------------------------------------------------------------

# Each entry: (hint_key, compiled_regex)
# Patterns use IGNORECASE | MULTILINE. Word boundaries (\b) prevent partial
# matches (e.g. "CREATED" matching "CREATE").
CONTENT_HINT_PATTERNS: list[tuple[str, re.Pattern]] = [
    # PL/SQL structural keywords
    ("has_plsql_blocks",      re.compile(r"\bBEGIN\b",                          re.I | re.M)),
    ("has_package",           re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?PACKAGE\b", re.I | re.M)),
    ("has_procedure",         re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?PROCEDURE\b", re.I | re.M)),
    ("has_function",          re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?FUNCTION\b",  re.I | re.M)),
    ("has_trigger",           re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?TRIGGER\b",   re.I | re.M)),
    ("has_type",              re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?TYPE\b",      re.I | re.M)),
    # DDL
    ("has_create_table",      re.compile(r"\bCREATE\s+TABLE\b",                 re.I | re.M)),
    ("has_alter_table",       re.compile(r"\bALTER\s+TABLE\b",                  re.I | re.M)),
    ("has_drop",              re.compile(r"\bDROP\s+(TABLE|VIEW|INDEX|SEQUENCE|PROCEDURE|FUNCTION|PACKAGE|TRIGGER|TYPE)\b", re.I | re.M)),
    ("has_create_view",       re.compile(r"\bCREATE\s+(OR\s+REPLACE\s+)?VIEW\b", re.I | re.M)),
    ("has_create_index",      re.compile(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b",     re.I | re.M)),
    ("has_create_sequence",   re.compile(r"\bCREATE\s+SEQUENCE\b",              re.I | re.M)),
    # DML
    ("has_select",            re.compile(r"\bSELECT\b",                         re.I | re.M)),
    ("has_insert",            re.compile(r"\bINSERT\s+INTO\b",                  re.I | re.M)),
    ("has_update",            re.compile(r"\bUPDATE\b",                         re.I | re.M)),
    ("has_delete",            re.compile(r"\bDELETE\s+FROM\b",                  re.I | re.M)),
    ("has_merge",             re.compile(r"\bMERGE\s+INTO\b",                   re.I | re.M)),
    # Permissions / metadata
    ("has_grants",            re.compile(r"\bGRANT\b",                          re.I | re.M)),
    ("has_comments",          re.compile(r"\bCOMMENT\s+ON\b",                   re.I | re.M)),
    # Transactions
    ("has_commit",            re.compile(r"\bCOMMIT\b",                         re.I | re.M)),
    ("has_rollback",          re.compile(r"\bROLLBACK\b",                       re.I | re.M)),
    # Oracle-specifics relevant to PySpark migration
    ("has_dbms_calls",        re.compile(r"\bDBMS_\w+\.",                       re.I | re.M)),
    ("has_utl_calls",         re.compile(r"\bUTL_\w+\.",                        re.I | re.M)),
    ("has_dynamic_sql",       re.compile(r"\bEXECUTE\s+IMMEDIATE\b",            re.I | re.M)),
    ("has_cursors",           re.compile(r"\bCURSOR\b",                         re.I | re.M)),
    ("has_exception_handling",re.compile(r"\bEXCEPTION\b",                      re.I | re.M)),
    ("has_autonomous_txn",    re.compile(r"PRAGMA\s+AUTONOMOUS_TRANSACTION",    re.I | re.M)),
    ("has_bulk_collect",      re.compile(r"\bBULK\s+COLLECT\b",                 re.I | re.M)),
    ("has_forall",            re.compile(r"\bFORALL\b",                         re.I | re.M)),
    # Migration markers (common in Flyway/Liquibase shops)
    ("has_migration_markers", re.compile(r"(--\s*migration|--\s*changelog|--\s*changeset|flyway|liquibase)", re.I | re.M)),
]

# Regex to extract the first meaningful SQL keyword from a non-blank,
# non-comment line. Used to classify file "primary type".
_FIRST_KEYWORD_RE = re.compile(
    r"^\s*(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|SELECT|GRANT|REVOKE|COMMENT|BEGIN|DECLARE|MERGE|TRUNCATE|CALL|EXEC)\b",
    re.I
)

# Patterns for stripping comments before line counting (so blank-after-strip
# lines don't inflate code_line_count).
_SINGLE_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_MULTI_LINE_COMMENT_RE  = re.compile(r"/\*.*?\*/", re.S)


# ---------------------------------------------------------------------------
# Default exclusion patterns (glob-style, matched against relative path)
# ---------------------------------------------------------------------------
DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    "*.bak",
    "*.tmp",
    "*_backup.*",
    "*_old.*",
    ".git/*",
    "node_modules/*",
    "__pycache__/*",
]


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def compute_sha256(path: Path) -> str:
    """SHA-256 of raw file bytes. Used to detect file changes on re-runs."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_file_id(rel_path: str, used_ids: dict[str, str]) -> tuple[str, str | None]:
    """
    Deterministic, stable file_id: "{SLUG}__{8-char path hash}".

    - SLUG is the filename stem, upper-cased (human-readable, for scanning logs).
    - The hash is derived from the relative PATH, not file content, so the id
      stays identical across reruns regardless of scan order or how many other
      files were added/removed elsewhere in the repo — it changes only if this
      file itself is moved or renamed.

    This id is meant to be the single stable key used to reference this file
    everywhere downstream (object_registry, parser output, statement-level
    logging names, etc.) — never re-derive a different id for the same file.

    Collisions (two different paths producing the same id) are astronomically
    unlikely but handled explicitly: suffix _2, _3, ... and surface a warning
    rather than silently overwriting an existing id.
    """
    norm_path = rel_path.replace(os.sep, "/")
    stem = Path(rel_path).stem
    slug = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").upper() or "FILE"
    digest = hashlib.sha256(norm_path.encode("utf-8")).hexdigest()[:8].upper()
    base_id = f"{slug}__{digest}"

    file_id = base_id
    warning = None
    suffix = 2
    while file_id in used_ids:
        warning = (f"file_id_collision: '{file_id}' already assigned to "
                   f"'{used_ids[file_id]}'; this file suffixed to disambiguate")
        file_id = f"{base_id}_{suffix}"
        suffix += 1

    used_ids[file_id] = rel_path
    return file_id, warning


def read_file_safe(path: Path, encoding: str) -> tuple[str | None, str | None]:
    """
    Read file text. Returns (content, None) on success or (None, error_msg)
    on failure. Tries the specified encoding first, then falls back to
    latin-1 (which never fails — every byte is a valid latin-1 character).
    """
    try:
        return path.read_text(encoding=encoding), None
    except UnicodeDecodeError:
        try:
            content = path.read_text(encoding="latin-1")
            return content, f"encoding_fallback:latin-1 (original encoding {encoding!r} failed)"
        except Exception as e:
            return None, f"read_error:{e}"
    except Exception as e:
        return None, f"read_error:{e}"


def count_lines(content: str) -> dict[str, int]:
    """
    Returns a breakdown of line types:
      total_lines       — every line including blank and comment-only
      code_lines        — lines with SQL tokens after stripping comments
      comment_lines     — lines that are purely comments (-- or /* */)
      blank_lines       — empty / whitespace-only lines
    """
    raw_lines = content.splitlines()
    total = len(raw_lines)

    # Strip inline comments to find which lines have actual code
    stripped = _SINGLE_LINE_COMMENT_RE.sub("", content)
    stripped = _MULTI_LINE_COMMENT_RE.sub("", stripped)
    stripped_lines = stripped.splitlines()

    code = sum(1 for ln in stripped_lines if ln.strip())
    blank = sum(1 for ln in raw_lines if not ln.strip())
    # comment_lines is a heuristic: total - code_lines - blank_lines
    comment = max(0, total - code - blank)

    return {
        "total_lines":   total,
        "code_lines":    code,
        "comment_lines": comment,
        "blank_lines":   blank,
    }


def classify_file_role(content: str, hints: dict[str, bool], rel_path: str) -> str:
    """
    Assign a single coarse role label to the file. Used by downstream stages
    to prioritise parsing strategy and BRD section grouping.

    Labels (in priority order):
      package        — contains PACKAGE or PACKAGE BODY
      procedure      — contains standalone PROCEDURE
      function       — contains standalone FUNCTION
      trigger        — contains TRIGGER
      schema_ddl     — primarily CREATE TABLE / ALTER TABLE / sequences / views
      migration      — detected migration markers or Flyway/Liquibase naming
      seed_data      — only DML (INSERT/UPDATE/DELETE), no DDL or PL/SQL
      mixed          — combination that doesn't fit one role cleanly
      unknown        — no recognisable SQL content
    """
    # Path-based migration detection (Flyway: V001__..., Liquibase: changelog)
    name = Path(rel_path).name.lower()
    if re.match(r"v\d+__", name) or "changelog" in name or hints.get("has_migration_markers"):
        return "migration"

    if hints.get("has_package"):
        return "package"
    if hints.get("has_procedure") and not hints.get("has_function"):
        return "procedure"
    if hints.get("has_function") and not hints.get("has_procedure"):
        return "function"
    if hints.get("has_trigger"):
        return "trigger"

    has_structural_ddl = (
        hints.get("has_create_table")
        or hints.get("has_alter_table")
        or hints.get("has_create_view")
        or hints.get("has_create_sequence")
        or hints.get("has_create_index")
    )
    has_dml = (
        hints.get("has_insert")
        or hints.get("has_update")
        or hints.get("has_delete")
        or hints.get("has_select")
    )
    has_plsql = hints.get("has_plsql_blocks")

    if has_structural_ddl and not has_dml and not has_plsql:
        return "schema_ddl"
    if has_dml and not has_structural_ddl and not has_plsql:
        return "seed_data"
    if has_structural_ddl or has_dml or has_plsql:
        return "mixed"

    return "unknown"


def extract_content_hints(content: str) -> dict[str, bool]:
    """Run all CONTENT_HINT_PATTERNS against file content."""
    return {key: bool(pattern.search(content)) for key, pattern in CONTENT_HINT_PATTERNS}


def infer_complexity(hints: dict[str, bool], line_counts: dict[str, int]) -> str:
    """
    Coarse complexity estimate for downstream token-budget planning:
      low    — simple DDL or single-purpose DML, no PL/SQL
      medium — PL/SQL present but no advanced features
      high   — cursors, dynamic SQL, bulk ops, exception handling, DBMS calls
    """
    high_signals = [
        hints.get("has_dynamic_sql"),
        hints.get("has_bulk_collect"),
        hints.get("has_forall"),
        hints.get("has_autonomous_txn"),
        hints.get("has_dbms_calls"),
        hints.get("has_utl_calls"),
        line_counts["code_lines"] > 150,
    ]
    medium_signals = [
        hints.get("has_plsql_blocks"),
        hints.get("has_cursors"),
        hints.get("has_exception_handling"),
        line_counts["code_lines"] > 40,
    ]

    if sum(bool(s) for s in high_signals) >= 2:
        return "high"
    if any(medium_signals):
        return "medium"
    return "low"


def generate_run_version() -> str:
    """
    Production-style run version stamp: "YYYY-MM-DDThh.mm.ss.sssZ" (UTC).
    Dots instead of colons so it is a valid folder name on Windows. Matches
    the timestamp-versioned-run convention used by tools like Kedro's
    versioned datasets: each run gets its own folder, "latest" is a pointer
    updated only on success, and nothing is ever overwritten in place.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H.%M.%S.") + f"{now.microsecond // 1000:03d}Z"


def should_exclude(rel_path: str, exclude_patterns: list[str]) -> bool:
    """Return True if rel_path matches any exclusion glob pattern."""
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        # Also match just the filename portion
        if fnmatch.fnmatch(Path(rel_path).name, pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# Per-file processor
# ---------------------------------------------------------------------------

def process_file(
    abs_path: Path,
    sql_dir: Path,
    encoding: str,
    include_hints: bool,
    used_ids: dict[str, str],
) -> dict:
    """
    Build the manifest entry for a single .sql file.
    Returns a dict conforming to the FileEntry schema.
    """
    rel_path = str(abs_path.relative_to(sql_dir))
    stat = abs_path.stat()

    file_id, id_warning = make_file_id(rel_path, used_ids)
    base_warnings = [id_warning] if id_warning else []

    entry: dict = {
        "file_id":       file_id,
        "file":          rel_path,
        "abs_path":      str(abs_path),
        "size_bytes":    stat.st_size,
        "sha256":        compute_sha256(abs_path),
        "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }

    # Handle unreadable / empty files gracefully — pipeline can skip them
    if stat.st_size == 0:
        entry.update({
            "status":       "empty",
            "line_counts":  {"total_lines": 0, "code_lines": 0, "comment_lines": 0, "blank_lines": 0},
            "file_role":    "unknown",
            "complexity":   "low",
            "encoding_used": encoding,
            "warnings":     base_warnings + ["File is empty"],
        })
        if include_hints:
            entry["content_hints"] = {key: False for key, _ in CONTENT_HINT_PATTERNS}
        return entry

    content, read_warning = read_file_safe(abs_path, encoding)

    if content is None:
        entry.update({
            "status":  "unreadable",
            "error":   read_warning,
            "warnings": base_warnings + [read_warning],
        })
        return entry

    line_counts = count_lines(content)
    hints       = extract_content_hints(content)
    file_role   = classify_file_role(content, hints, rel_path)
    complexity  = infer_complexity(hints, line_counts)

    # Detect encoding used (may differ from requested if fallback occurred)
    encoding_used = "latin-1" if (read_warning and "latin-1" in read_warning) else encoding

    warnings = list(base_warnings)
    if read_warning:
        warnings.append(read_warning)
    if line_counts["code_lines"] == 0 and stat.st_size > 0:
        warnings.append("File has no detectable SQL code lines (comments/whitespace only)")

    entry.update({
        "status":        "ok",
        "line_counts":   line_counts,
        "file_role":     file_role,
        "complexity":    complexity,
        "encoding_used": encoding_used,
        "warnings":      warnings,
    })

    if include_hints:
        # Only emit True hints to keep JSON compact — False == absent
        entry["content_hints"] = {k: v for k, v in hints.items() if v}

    return entry


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_summary(file_entries: list[dict], excluded_count: int) -> dict:
    """
    Aggregate statistics across all processed files.
    Consumed by downstream stages for token-budget planning and BRD scoping.
    """
    ok_entries = [e for e in file_entries if e.get("status") == "ok"]

    role_counts: dict[str, int] = {}
    complexity_counts: dict[str, int] = {}
    total_lines = 0
    total_code_lines = 0

    for e in ok_entries:
        role = e.get("file_role", "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1

        cx = e.get("complexity", "low")
        complexity_counts[cx] = complexity_counts.get(cx, 0) + 1

        lc = e.get("line_counts", {})
        total_lines      += lc.get("total_lines", 0)
        total_code_lines += lc.get("code_lines", 0)

    # Aggregate all True content hints across the codebase
    codebase_hints: dict[str, int] = {}
    for e in ok_entries:
        for hint_key in e.get("content_hints", {}):
            codebase_hints[hint_key] = codebase_hints.get(hint_key, 0) + 1

    # Identify files that need special attention in downstream stages
    high_complexity_files = [
        e["file"] for e in ok_entries if e.get("complexity") == "high"
    ]
    files_with_warnings = [
        {"file": e["file"], "warnings": e["warnings"]}
        for e in file_entries if e.get("warnings")
    ]
    unreadable_files = [
        e["file"] for e in file_entries if e.get("status") == "unreadable"
    ]

    return {
        "total_files_found":    len(file_entries) + excluded_count,
        "total_files_included": len(file_entries),
        "total_files_excluded": excluded_count,
        "total_files_ok":       len(ok_entries),
        "total_files_empty":    sum(1 for e in file_entries if e.get("status") == "empty"),
        "total_files_unreadable": len(unreadable_files),
        "total_lines":          total_lines,
        "total_code_lines":     total_code_lines,
        "files_by_role":        role_counts,
        "files_by_complexity":  complexity_counts,
        "codebase_features":    codebase_hints,
        "high_complexity_files": high_complexity_files,
        "files_with_warnings":  files_with_warnings,
        "unreadable_files":     unreadable_files,
        # Hints for downstream token budget planning
        "stage2_enrich_hint": {
            "estimated_blocks":      len(ok_entries) * 3,   # rough avg blocks per file
            "recommended_batch_size": 25,
            "estimated_batches":     max(1, (len(ok_entries) * 3) // 25),
        },
    }


# ---------------------------------------------------------------------------
# Directory walker
# ---------------------------------------------------------------------------

def discover(
    sql_dir: Path,
    exclude_patterns: list[str],
    encoding: str,
    include_hints: bool,
    verbose: bool,
) -> tuple[list[dict], int]:
    """
    Recursively walk sql_dir. Returns (file_entries, excluded_count).
    Files are sorted by relative path for deterministic output across runs.
    """
    all_sql_files: list[Path] = sorted(sql_dir.rglob("*.sql"))
    file_entries: list[dict] = []
    excluded_count = 0
    used_ids: dict[str, str] = {}

    for abs_path in all_sql_files:
        rel_path = str(abs_path.relative_to(sql_dir))

        if should_exclude(rel_path, exclude_patterns):
            excluded_count += 1
            if verbose:
                print(f"  [excluded] {rel_path}", file=sys.stderr)
            continue

        entry = process_file(abs_path, sql_dir, encoding, include_hints, used_ids)
        file_entries.append(entry)

        if verbose:
            status = entry.get("status", "?")
            role   = entry.get("file_role", "")
            cx     = entry.get("complexity", "")
            lines  = entry.get("line_counts", {}).get("total_lines", 0)
            warn   = f"  [!] {'; '.join(entry['warnings'])}" if entry.get("warnings") else ""
            print(f"  [{status:10}] {rel_path:50} role={role:12} complexity={cx:6} lines={lines}{warn}",
                  file=sys.stderr)

    return file_entries, excluded_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 0: Discover .sql files and produce inventory-artifact.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python .claude/scripts/00_inventory.py ./sql_codebase
  python .claude/scripts/00_inventory.py ./sql_codebase --output-root output/inventory --verbose
  python .claude/scripts/00_inventory.py ./sql_codebase --output checkpoints/inventory-artifact.json --verbose
  python .claude/scripts/00_inventory.py ./sql_codebase --exclude "*_backup*" "legacy/*" --no-content-hints
        """,
    )
    parser.add_argument(
        "sql_dir",
        help="Root directory containing .sql files (searched recursively)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Exact output file path. Overrides --output-root and disables run "
             "versioning — writes exactly here every time (used by tests / "
             "one-off invocations). If omitted, a new timestamped run folder "
             "is created under --output-root on every invocation.",
    )
    parser.add_argument(
        "--output-root",
        default="output/inventory",
        help="Root directory for versioned runs when --output is not given "
             "(default: output/inventory). Each run writes to "
             "<root>/<run_version>/inventory-artifact.json and updates "
             "<root>/latest.json to point at it.",
    )
    parser.add_argument(
        "--exclude", "-e",
        nargs="+",
        default=[],
        metavar="PATTERN",
        help="Additional glob patterns to exclude (e.g. '*_backup*' 'legacy/*')",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Disable built-in exclusion patterns",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Primary encoding to try when reading files (default: utf-8)",
    )
    parser.add_argument(
        "--no-content-hints",
        action="store_true",
        help="Omit content_hints from output (smaller JSON, Stage 1 will re-derive)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-file status to stderr during discovery",
    )
    args = parser.parse_args()

    sql_dir = Path(args.sql_dir).resolve()
    if not sql_dir.exists():
        print(f"ERROR: directory not found: {sql_dir}", file=sys.stderr)
        sys.exit(1)
    if not sql_dir.is_dir():
        print(f"ERROR: not a directory: {sql_dir}", file=sys.stderr)
        sys.exit(1)

    exclude_patterns = [] if args.no_default_excludes else list(DEFAULT_EXCLUDE_PATTERNS)
    exclude_patterns.extend(args.exclude)

    include_hints = not args.no_content_hints

    # ---- Resolve output location ----
    # --output given: exact-path override, no versioning (used by tests and
    #   one-off invocations that need a known, fixed path).
    # --output omitted: production default — every run gets its own
    #   timestamped folder under --output-root, so re-running this stage
    #   never overwrites a previous run's artifact. latest.json is updated
    #   only after a successful write, so downstream stages that resolve
    #   "the current inventory" via latest.json never pick up a partial run.
    versioned_run = args.output is None
    run_version = generate_run_version()
    if versioned_run:
        run_dir = Path(args.output_root) / run_version
        output_path = run_dir / "inventory-artifact.json"
    else:
        output_path = Path(args.output)
        run_dir = output_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)

    # ---- Run discovery ----
    run_ts = datetime.now(timezone.utc).isoformat()
    if args.verbose:
        print(f"\n[Stage 0: INVENTORY]  {sql_dir}", file=sys.stderr)
        print(f"Exclusion patterns: {exclude_patterns}", file=sys.stderr)
        print(f"Encoding: {args.encoding}  |  Content hints: {include_hints}\n", file=sys.stderr)

    file_entries, excluded_count = discover(
        sql_dir=sql_dir,
        exclude_patterns=exclude_patterns,
        encoding=args.encoding,
        include_hints=include_hints,
        verbose=args.verbose,
    )

    summary = build_summary(file_entries, excluded_count)

    # file_index: cheap file_id -> path lookup, used by every downstream stage
    # to reference a file without carrying its full metadata around.
    # file_metadata: the actual per-file payload, keyed by the same file_id —
    # single source of truth so metadata never has to be copied/duplicated
    # into other artifacts.
    file_index: dict[str, str] = {e["file_id"]: e["file"] for e in file_entries}
    file_metadata: dict[str, dict] = {
        e["file_id"]: {k: v for k, v in e.items() if k != "file_id"}
        for e in file_entries
    }

    manifest = {
        "pipeline_stage":   "00_inventory",
        "schema_version":   "2.0",
        "generated_at":     run_ts,
        "source_dir":       str(sql_dir),
        "cli_args": {
            "encoding":          args.encoding,
            "exclude_patterns":  exclude_patterns,
            "content_hints":     include_hints,
        },
        "summary":       summary,
        "file_index":    file_index,
        "file_metadata": file_metadata,
    }

    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        run_meta = {
            "stage":        "00_inventory",
            "run_version":  run_version,
            "generated_at": run_ts,
            "status":       "success",
            "source_dir":   str(sql_dir),
            "cli_args": {
                "encoding":          args.encoding,
                "exclude_patterns":  exclude_patterns,
                "content_hints":     include_hints,
            },
            "output_file":  output_path.name,
            "stats_summary": {
                "total_files_ok": summary["total_files_ok"],
                "total_files_excluded": summary["total_files_excluded"],
                "total_files_unreadable": summary["total_files_unreadable"],
            },
        }
        (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2, ensure_ascii=False), encoding="utf-8")

        latest_pointer = {
            "run_version": run_version,
            "path":        f"{run_version}/inventory-artifact.json",
            "updated_at":  run_ts,
        }
        latest_path = Path(args.output_root) / "latest.json"
        latest_path.write_text(json.dumps(latest_pointer, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- Stdout report (consumed by Claude Code / orchestrator) ----
    ok   = summary["total_files_ok"]
    warn = len(summary["files_with_warnings"])
    bad  = summary["total_files_unreadable"] + summary["total_files_empty"]

    print(f"[00_inventory] Complete.")
    print(f"  Source dir : {sql_dir}")
    print(f"  Output     : {output_path}")
    print(f"  Files found: {summary['total_files_found']} total, "
          f"{summary['total_files_excluded']} excluded, "
          f"{ok} OK, {bad} skipped, {warn} with warnings")
    print(f"  Lines      : {summary['total_lines']} total, {summary['total_code_lines']} code")
    print(f"  Roles      : {summary['files_by_role']}")
    print(f"  Complexity : {summary['files_by_complexity']}")
    if summary["high_complexity_files"]:
        print(f"  [!] High-complexity files: {summary['high_complexity_files']}")
    if summary["unreadable_files"]:
        print(f"  [X] Unreadable files: {summary['unreadable_files']}")
    if versioned_run:
        print(f"  Run version: {run_version}")
        print(f"  Latest ptr : {latest_path}")
    print(f"\n  Next step  : python 01_parse.py {output_path}")


if __name__ == "__main__":
    main()