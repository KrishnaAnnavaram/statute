#!/usr/bin/env python3
"""
Stage 4: LOGIC (deterministic, no LLM)  —  schema_version 2.0
================================================================
Turns Agent 2's statement tree into artefacts a human can validate, and
computes the migration-relevant analyses nothing else in the pipeline
produces.

Seven analyses, each grounded in a cited source (see DESIGN_REFERENCES in
the output artifact):

  1. Pseudocode          — readable behavioural description per object
  2. Cyclomatic complexity   (McCabe 1976)      — testability
  3. Cognitive complexity    (Campbell 2023)    — understandability
  4. Variable-centric slices (Weiser 1981 / COBREX ICSME'22)
  5. Transaction boundaries  — Spark/ACID migration hazards
  6. CRUD matrix             — object x table access
  7. Shape classification    — batch vs single-record vs query vs calculation

Why TWO complexity metrics rather than one homemade score:
  - McCabe measures testability (paths to cover) but treats a flat 10-arm
    CASE and a triple-nested IF as equally complex — nesting, the thing
    that actually makes PL/SQL unreadable, is invisible to it.
  - Cognitive Complexity was formulated specifically to fix that, by
    penalising nesting and ignoring shorthand. It is the understandability
    number; McCabe is the testability number. They answer different
    questions and the BRD reports both.
  - The Maintainability Index was deliberately NOT adopted: its Halstead
    Volume term has no consensual definition and averaging complexity
    hides the power-law outliers where the real risk lives.

Zero LLM calls. 100% deterministic.

Output: output/logic/<run_version>/{program_logic/*.json, logic_artifact.json,
run_meta.json}, plus output/logic/latest.json.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DESIGN_REFERENCES = [
    {"claim": "Cyclomatic complexity = decision points + 1; measures testability, not understandability.",
     "source": "Thomas J. McCabe, 'A Complexity Measure', IEEE TSE SE-2(4), 1976. Recommended module "
               "threshold 10 (NIST allows up to 15 with written justification)."},
    {"claim": "Cognitive Complexity: +1 per flow break, PLUS a nesting increment per level of nesting; "
              "else/elsif increment but receive no nesting penalty (the mental cost was paid at the if).",
     "source": "G. Ann Campbell, 'Cognitive Complexity — a new way of measuring understandability', "
               "SonarSource v1.7 (2023), Appendix B specification. Peer-reviewed companion: "
               "Campbell, TechDebt 2018, doi 10.1145/3194164.3194186."},
    {"claim": "Business logic is best understood by slicing around business VARIABLES (what determines "
              "this value?), not by listing branch conditions in isolation.",
     "source": "Weiser, 'Program Slicing' (ICSE 1981); COBREX (ICSME 2022) applies exactly this to legacy "
               "business-rule extraction — it collects each business variable's statements plus their "
               "controlling context statements via DFS over the CFG."},
    {"claim": "A COMMIT inside a cursor loop is a recognised Oracle anti-pattern ('incremental commit' / "
              "'fetch across commit') and a first-order migration hazard.",
     "source": "Oracle practitioner literature on ORA-01555 'snapshot too old': committing inside the loop "
               "frees undo that the still-open cursor needs, making the error MORE likely, not less. "
               "Apache Spark has no transactional equivalent at all."},
    {"claim": "The Maintainability Index is deliberately not used.",
     "source": "van Deursen, 'Think Twice Before Using the Maintainability Index' — Halstead Volume has no "
               "consensual definition, the formula is dominated by file length, and averaging complexity "
               "erases the power-law outliers that carry the actual risk."},
]

# McCabe's own recommended limit; NIST permits up to 15 with justification.
CYCLOMATIC_THRESHOLD = 10
# SonarSource's default "too complex to understand" gate for a method.
COGNITIVE_THRESHOLD = 15


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
    return json.loads((root_path / run_version / artifact_filename).read_text(encoding="utf-8")), run_version


# ---------------------------------------------------------------------------
# Source access
# ---------------------------------------------------------------------------

_SOURCE_CACHE: dict[str, list[str]] = {}


def source_lines(abs_path: str) -> list[str]:
    if abs_path not in _SOURCE_CACHE:
        try:
            _SOURCE_CACHE[abs_path] = Path(abs_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            _SOURCE_CACHE[abs_path] = []
    return _SOURCE_CACHE[abs_path]


def raw_snippet(abs_path: str, start: int, end: int) -> str:
    """
    Source text for a line range with comments removed.

    Comments are stripped PER LINE before joining. Stripping on the joined
    blob truncates everything after the first `--` anywhere in the range,
    which silently swallows real statements (an ELSE or END IF that happens
    to follow a commented line).
    """
    lines = source_lines(abs_path)
    if not lines or start < 1:
        return ""
    cleaned = [re.sub(r"--.*", "", l).strip() for l in lines[start - 1:end]]
    return re.sub(r"\s+", " ", " ".join(cleaned)).strip()


def extract_condition(abs_path: str, start: int, end: int, stop_keyword: str) -> str:
    snippet = raw_snippet(abs_path, start, end)
    m = re.search(r"^\s*(?:IF|ELSIF|WHILE)\s+(.*?)\s+" + stop_keyword + r"\b", snippet, re.IGNORECASE)
    return m.group(1).strip() if m else snippet


def extract_elsif_conditions(abs_path: str, start: int, end: int) -> list[str]:
    return [m.strip() for m in re.findall(
        r"\bELSIF\s+(.*?)\s+THEN\b", raw_snippet(abs_path, start, end), re.IGNORECASE)]


def has_else_branch(abs_path: str, start: int, end: int) -> bool:
    return re.search(r"\bELSE\b", raw_snippet(abs_path, start, end), re.IGNORECASE) is not None


def _seq_num(statement_id: str) -> int:
    m = re.search(r"STMT_(\d+)$", statement_id)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Analysis 2 — Cyclomatic complexity (McCabe 1976)
# ---------------------------------------------------------------------------

def count_logical_operator_sequences(condition: str) -> int:
    """
    Number of maximal runs of LIKE binary logical operators.
    'a AND b AND c'      -> 1 sequence
    'a AND b OR c'       -> 2 sequences (operator changes)
    Used by BOTH metrics, but differently: McCabe counts every operator as a
    decision; Cognitive Complexity counts each SEQUENCE once (mixed operators
    are what actually hurt comprehension).
    """
    ops = [o.upper() for o in re.findall(r"\b(AND|OR)\b", condition, re.IGNORECASE)]
    if not ops:
        return 0
    return 1 + sum(1 for i in range(1, len(ops)) if ops[i] != ops[i - 1])


def count_logical_operators(condition: str) -> int:
    return len(re.findall(r"\b(AND|OR)\b", condition, re.IGNORECASE))


def branch_labels(statements: dict, parent_id: str, prefix: str) -> set[str]:
    """Distinct branch labels among a parent's children (e.g. CASE#7.WHEN2)."""
    out = set()
    for s in statements.values():
        if s.get("parent_id") == parent_id and s.get("scope_path"):
            tail = s["scope_path"][-1]
            if tail.startswith(prefix):
                out.add(tail)
    return out


def compute_cyclomatic(statements: dict, abs_path: str) -> dict:
    """
    McCabe's decision-point shortcut: complexity = decisions + 1.

    Counted as decisions: IF, each ELSIF, each CASE WHEN arm, each loop, each
    EXCEPTION handler, and each binary logical operator (McCabe counts every
    operator, since each creates an independent path at machine level).
    ELSE is NOT a decision — it is the fall-through of an existing one.
    """
    decisions = 0
    detail = {"if": 0, "elsif": 0, "case_when": 0, "loop": 0, "exception_handler": 0, "logical_operators": 0}

    for s in statements.values():
        st = s["statement_type"]
        if st == "IF":
            decisions += 1
            detail["if"] += 1
            cond = extract_condition(abs_path, s["start_line"], s["end_line"], "THEN")
            ops = count_logical_operators(cond)
            elsifs = extract_elsif_conditions(abs_path, s["start_line"], s["end_line"])
            decisions += len(elsifs)
            detail["elsif"] += len(elsifs)
            for e in elsifs:
                ops += count_logical_operators(e)
            decisions += ops
            detail["logical_operators"] += ops
        elif st == "LOOP":
            decisions += 1
            detail["loop"] += 1
        elif st == "CASE":
            arms = len(branch_labels(statements, s["statement_id"], "CASE#"))
            arms = max(arms, 1)
            decisions += arms
            detail["case_when"] += arms
        elif st == "EXCEPTION_HANDLER":
            decisions += 1
            detail["exception_handler"] += 1

    score = decisions + 1
    return {
        "score": score,
        "decision_points": decisions,
        "breakdown": detail,
        "threshold": CYCLOMATIC_THRESHOLD,
        "exceeds_threshold": score > CYCLOMATIC_THRESHOLD,
        "interpretation": ("simple, minimal risk" if score <= 10 else
                           "moderate risk" if score <= 20 else
                           "complex, high risk" if score <= 50 else
                           "untestable"),
        "means": "Minimum number of test cases needed for full branch coverage.",
    }


# ---------------------------------------------------------------------------
# Analysis 3 — Cognitive complexity (Campbell 2023, Appendix B spec)
# ---------------------------------------------------------------------------

# B2 — structures that INCREASE the nesting level for their children.
_NESTING_LEVEL_TYPES = {"IF", "CASE", "LOOP", "EXCEPTION_HANDLER"}
# B3 — structures that RECEIVE a nesting increment.
# Per spec, `else if` / `else` increment but take NO nesting penalty: the
# mental cost of the nesting was already paid when reading the opening `if`.
_NESTING_INCREMENT_TYPES = {"IF", "CASE", "LOOP", "EXCEPTION_HANDLER"}


def nesting_level_of(stmt: dict, statements: dict) -> int:
    """Count enclosing B2 structures by walking the parent chain — computed
    here rather than trusting any upstream depth convention."""
    level = 0
    parent_id = stmt.get("parent_id")
    guard = 0
    while parent_id and guard < 200:
        parent = statements.get(parent_id)
        if parent is None:
            break
        if parent["statement_type"] in _NESTING_LEVEL_TYPES:
            level += 1
        parent_id = parent.get("parent_id")
        guard += 1
    return level


def compute_cognitive(statements: dict, abs_path: str) -> dict:
    """
    Campbell's three rules:
      1. ignore shorthand (no increment for the procedure itself)
      2. +1 for each break in linear flow
      3. + nesting level for nested flow-breaking structures
    """
    score = 0
    detail = {"structural": 0, "nesting": 0, "hybrid_else_elsif": 0,
              "logical_sequences": 0, "goto": 0}

    for s in statements.values():
        st = s["statement_type"]
        level = nesting_level_of(s, statements)

        if st in _NESTING_INCREMENT_TYPES:
            score += 1                      # structural increment
            detail["structural"] += 1
            if level > 0:
                score += level              # nesting increment
                detail["nesting"] += level

        if st == "IF":
            cond = extract_condition(abs_path, s["start_line"], s["end_line"], "THEN")
            seqs = count_logical_operator_sequences(cond)
            score += seqs                    # fundamental increment, no nesting
            detail["logical_sequences"] += seqs

            # ELSIF / ELSE are hybrid: +1 each, but never a nesting increment.
            elsifs = extract_elsif_conditions(abs_path, s["start_line"], s["end_line"])
            score += len(elsifs)
            detail["hybrid_else_elsif"] += len(elsifs)
            for e in elsifs:
                seqs_e = count_logical_operator_sequences(e)
                score += seqs_e
                detail["logical_sequences"] += seqs_e
            if has_else_branch(abs_path, s["start_line"], s["end_line"]):
                score += 1
                detail["hybrid_else_elsif"] += 1

        elif st == "GOTO":
            score += 1
            detail["goto"] += 1

    return {
        "score": score,
        "breakdown": detail,
        "threshold": COGNITIVE_THRESHOLD,
        "exceeds_threshold": score > COGNITIVE_THRESHOLD,
        "interpretation": ("easy to understand" if score <= 5 else
                           "moderate mental effort" if score <= 10 else
                           "hard to understand" if score <= 20 else
                           "very hard — refactor before migrating"),
        "means": "Relative mental effort to understand this code. Penalises nesting; "
                 "ignores shorthand. Not a test-case count.",
    }


# ---------------------------------------------------------------------------
# Analysis 4 — variable-centric backward slicing (Weiser / COBREX)
# ---------------------------------------------------------------------------

_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_$#]*)\b")
_SQL_NOISE = {
    "SELECT", "FROM", "WHERE", "INTO", "AND", "OR", "NOT", "NULL", "IS", "IN",
    "THEN", "ELSE", "ELSIF", "IF", "END", "LOOP", "FOR", "WHILE", "BEGIN",
    "UPDATE", "SET", "INSERT", "VALUES", "DELETE", "COMMIT", "ROLLBACK",
    "RETURN", "RAISE", "EXCEPTION", "WHEN", "NVL", "TRUNC", "SYSDATE", "COUNT",
    "SUM", "MAX", "MIN", "AVG", "ROUND", "TO_DATE", "TO_CHAR", "ADD_MONTHS",
    "LAST_DAY", "GREATEST", "LEAST", "DECODE", "CASE", "AS", "BY", "ORDER",
    "GROUP", "HAVING", "DISTINCT", "EXISTS", "BETWEEN", "LIKE", "MOD", "ABS",
}


def identifiers_in(text: str) -> set[str]:
    return {m.group(1).upper() for m in _IDENT_RE.finditer(text)
            if m.group(1).upper() not in _SQL_NOISE and not m.group(1).isdigit()}


def assignment_targets_and_sources(stmt: dict, abs_path: str) -> tuple[set[str], set[str]]:
    """
    Which variables a statement WRITES and which it READS.

    Agent 2 deliberately strips the INTO clause before handing SELECT text to
    sqlglot (sqlglot cannot parse Oracle's SELECT..INTO), so INTO targets are
    not in the artifact and must be recovered from source here.
    """
    st = stmt["statement_type"]
    text = raw_snippet(abs_path, stmt["start_line"], stmt["end_line"])
    targets: set[str] = set()
    sources: set[str] = set()

    if st == "ASSIGNMENT":
        parts = re.split(r":=", text, maxsplit=1)
        if len(parts) == 2:
            targets |= identifiers_in(parts[0])
            sources |= identifiers_in(parts[1])
    elif st == "SELECT_INTO":
        m = re.search(r"\bINTO\b(.*?)\bFROM\b", text, re.IGNORECASE | re.DOTALL)
        if m:
            targets |= identifiers_in(m.group(1))
        sel = re.search(r"\bSELECT\b(.*?)\bINTO\b", text, re.IGNORECASE | re.DOTALL)
        if sel:
            sources |= identifiers_in(sel.group(1))
        whr = re.search(r"\bWHERE\b(.*)$", text, re.IGNORECASE | re.DOTALL)
        if whr:
            sources |= identifiers_in(whr.group(1))
    else:
        sources |= identifiers_in(text)

    return targets, sources


def control_ancestors(stmt_id: str, statements: dict) -> list[str]:
    """Control-dependence chain: every enclosing decision, per PDG semantics."""
    out, guard = [], 0
    parent_id = statements.get(stmt_id, {}).get("parent_id")
    while parent_id and guard < 200:
        out.append(parent_id)
        parent_id = statements.get(parent_id, {}).get("parent_id")
        guard += 1
    return out


def slice_for_variable(variable: str, statements: dict, abs_path: str,
                       writes_index: dict[str, list[str]],
                       reads_index: dict[str, set[str]]) -> dict:
    """
    Backward static slice: every statement that contributes to this
    variable's value, transitively, plus the conditions controlling them.

    This is the COBREX question — "what determines this value?" — rather than
    "what conditions exist?", which is what condition-mining alone answers.
    """
    var = variable.upper()
    included: set[str] = set()
    worklist = [var]
    seen_vars: set[str] = set()
    guard = 0

    while worklist and guard < 500:
        guard += 1
        v = worklist.pop()
        if v in seen_vars:
            continue
        seen_vars.add(v)
        for sid in writes_index.get(v, []):
            if sid in included:
                continue
            included.add(sid)
            for anc in control_ancestors(sid, statements):
                included.add(anc)
            for src in reads_index.get(sid, set()):
                if src not in seen_vars:
                    worklist.append(src)

    ordered = sorted(included, key=_seq_num)
    return {
        "variable": var,
        "determined_by_statements": ordered,
        "statement_count": len(ordered),
        "depends_on_variables": sorted(seen_vars - {var}),
        "source_lines": sorted({statements[s]["start_line"] for s in ordered if s in statements}),
    }


# ---------------------------------------------------------------------------
# Analysis 5 — transaction boundaries
# ---------------------------------------------------------------------------

def analyse_transactions(statements: dict) -> dict:
    """
    Segment the object by transaction-control statements and flag the
    migration hazards. Spark has no transactions, so every boundary here is
    a decision someone must make during the rewrite.
    """
    ordered = sorted(statements.values(), key=lambda s: _seq_num(s["statement_id"]))
    commits, rollbacks, savepoints = [], [], []
    commit_in_loop, rollback_in_handler = [], []

    for s in ordered:
        st = s["statement_type"]
        if st not in ("COMMIT", "ROLLBACK", "SAVEPOINT"):
            continue
        ancestors = [statements[a]["statement_type"] for a in control_ancestors(s["statement_id"], statements)
                     if a in statements]
        entry = {"statement_id": s["statement_id"], "line": s["start_line"]}
        if st == "COMMIT":
            commits.append(entry)
            if "LOOP" in ancestors:
                commit_in_loop.append(entry)
        elif st == "ROLLBACK":
            rollbacks.append(entry)
            if "EXCEPTION_HANDLER" in ancestors:
                rollback_in_handler.append(entry)
        else:
            savepoints.append(entry)

    # Segment: everything up to and including each COMMIT is one unit of work.
    segments, current = [], []
    for s in ordered:
        current.append(s)
        if s["statement_type"] == "COMMIT":
            written = sorted({t for x in current for t in (x.get("tables") or []) if x.get("writes")})
            segments.append({
                "ends_at_line": s["start_line"],
                "statement_count": len(current),
                "tables_written": written,
            })
            current = []
    if current:
        written = sorted({t for x in current for t in (x.get("tables") or []) if x.get("writes")})
        segments.append({"ends_at_line": None, "statement_count": len(current),
                         "tables_written": written, "note": "no COMMIT — transaction left open to the caller"})

    hazards = []
    if commit_in_loop:
        hazards.append({
            "hazard": "COMMIT_INSIDE_LOOP", "severity": "high",
            "occurrences": commit_in_loop,
            "explanation": "Committing inside a cursor loop is the 'incremental commit' anti-pattern. In "
                           "Oracle it frees undo the open cursor still needs, making ORA-01555 'snapshot "
                           "too old' MORE likely, not less. It also means the operation is not atomic: a "
                           "mid-loop failure leaves partial work committed. Spark has no transactional "
                           "equivalent — this must be redesigned, typically as a bulk/batch write.",
        })
    if savepoints:
        hazards.append({
            "hazard": "SAVEPOINT_PARTIAL_ROLLBACK", "severity": "high", "occurrences": savepoints,
            "explanation": "SAVEPOINT enables partial rollback within a transaction. Spark has no "
                           "equivalent; the compensating logic must be made explicit in the rewrite.",
        })
    if not commits and not rollbacks:
        hazards.append({
            "hazard": "NO_TRANSACTION_CONTROL", "severity": "info", "occurrences": [],
            "explanation": "This object issues no COMMIT or ROLLBACK — the transaction boundary is owned "
                           "by its caller. Confirm the caller's boundary before migrating.",
        })

    return {
        "commits": commits, "rollbacks": rollbacks, "savepoints": savepoints,
        "commit_inside_loop": commit_in_loop,
        "rollback_in_exception_handler": rollback_in_handler,
        "transaction_segments": segments,
        "hazards": hazards,
        "is_atomic": len(commits) <= 1 and not commit_in_loop,
    }


# ---------------------------------------------------------------------------
# Analysis 6 & 7 — CRUD matrix and shape classification
# ---------------------------------------------------------------------------

_CRUD_FOR = {"INSERT": "C", "SELECT": "R", "SELECT_INTO": "R", "UPDATE": "U",
             "DELETE": "D", "MERGE": "CU"}


def build_crud(statements: dict) -> dict[str, str]:
    crud: dict[str, set] = {}
    for s in statements.values():
        letters = _CRUD_FOR.get(s["statement_type"])
        if not letters:
            continue
        for t in (s.get("tables") or []):
            crud.setdefault(t.upper(), set()).update(letters)
    return {t: "".join(sorted(v)) for t, v in sorted(crud.items())}


def classify_shape(statements: dict, obj_type: str) -> dict:
    types = [s["statement_type"] for s in statements.values()]
    has_loop = "LOOP" in types
    dml = {"INSERT", "UPDATE", "DELETE", "MERGE"}
    has_dml = any(t in dml for t in types)
    has_return = "RETURN" in types

    dml_in_loop = any(
        s["statement_type"] in dml and
        any(statements[a]["statement_type"] == "LOOP"
            for a in control_ancestors(s["statement_id"], statements) if a in statements)
        for s in statements.values())

    if dml_in_loop:
        shape, why = "BATCH_PROCESSOR", ("Iterates a result set and writes inside the loop — the classic "
                                         "row-by-row batch pattern. In Spark this becomes a set-based "
                                         "DataFrame transformation, not a loop.")
    elif has_dml and not has_loop:
        shape, why = "SINGLE_RECORD_TRANSACTION", ("Reads and writes a small, bounded set of rows in one "
                                                   "pass — maps to a single transactional operation.")
    elif has_loop and not has_dml:
        shape, why = "ITERATIVE_QUERY", "Iterates a result set without writing — a read/report pattern."
    elif has_return and not has_dml:
        shape, why = "CALCULATION", ("Computes and returns a value with no persistent writes — maps "
                                     "cleanly to a Spark UDF or column expression.")
    elif has_dml:
        shape, why = "MIXED_WRITE", "Writes data in a pattern that does not fit a single standard shape."
    else:
        shape, why = "QUERY_ONLY", "Reads only; no persistent state change."

    return {"shape": shape, "rationale": why, "has_loop": has_loop,
            "has_dml": has_dml, "dml_inside_loop": dml_in_loop}


# ---------------------------------------------------------------------------
# Analysis 1 — pseudocode
# ---------------------------------------------------------------------------

def render_predicate(predicate_reads: list[str]) -> str:
    """
    predicate_reads is a flat list of identifiers sqlglot found in a WHERE
    clause; it does not record which side of an `=` each was on. The
    overwhelmingly common shape is `column = bind_value`, so render exactly
    two that way and fall back to a neutral phrasing otherwise — never imply
    structure we don't actually have.
    """
    if not predicate_reads:
        return ""
    if len(predicate_reads) == 2:
        return f" WHERE {predicate_reads[0]} = {predicate_reads[1]}"
    return f" (matching on: {', '.join(predicate_reads)})"


def translate_statement(stmt: dict, abs_path: str) -> str:
    st = stmt["statement_type"]
    indent = "  " * (stmt.get("nesting_depth", 1) - 1)

    if st == "SELECT_INTO":
        cols = ", ".join(stmt.get("reads", [])) or "columns"
        tables = ", ".join(stmt.get("tables", [])) or "?"
        return f"{indent}LOOK UP {cols} FROM {tables}{render_predicate(stmt.get('predicate_reads', []))}"
    if st == "SELECT":
        cols = ", ".join(stmt.get("reads", [])) or "columns"
        return f"{indent}READ {cols} FROM {', '.join(stmt.get('tables', [])) or '?'}"
    if st == "UPDATE":
        writes = ", ".join(stmt.get("writes", [])) or "columns"
        tables = ", ".join(stmt.get("tables", [])) or "?"
        return f"{indent}UPDATE {tables}: SET {writes}{render_predicate(stmt.get('predicate_reads', []))}"
    if st == "INSERT":
        return f"{indent}INSERT a new row INTO {', '.join(stmt.get('tables', [])) or '?'}"
    if st == "DELETE":
        tables = ", ".join(stmt.get("tables", [])) or "?"
        return f"{indent}DELETE FROM {tables}{render_predicate(stmt.get('predicate_reads', []))}"
    if st == "MERGE":
        return (f"{indent}MERGE data into {', '.join(stmt.get('tables', [])) or '?'}"
                f"  -- complex; see source line {stmt['start_line']}")
    if st == "DYNAMIC_SQL":
        return (f"{indent}!! DYNAMIC SQL (EXECUTE IMMEDIATE) — target cannot be known statically, "
                f"see source line {stmt['start_line']}")
    if st == "COMMIT":
        return f"{indent}COMMIT the transaction"
    if st == "ROLLBACK":
        return f"{indent}ROLL BACK the transaction"
    if st == "SAVEPOINT":
        return f"{indent}SET a SAVEPOINT (partial-rollback marker)"
    if st == "RAISE":
        snippet = raw_snippet(abs_path, stmt["start_line"], stmt["end_line"])
        return f"{indent}RAISE {snippet.replace('RAISE', '', 1).strip(' ;')}".rstrip()
    if st == "RETURN":
        snippet = raw_snippet(abs_path, stmt["start_line"], stmt["end_line"])
        return f"{indent}RETURN {snippet.replace('RETURN', '', 1).strip(' ;')}".rstrip()
    if st == "EXIT":
        return f"{indent}EXIT the loop"
    if st == "CONTINUE":
        return f"{indent}CONTINUE to the next loop iteration"
    if st == "NULL":
        return f"{indent}DO NOTHING"
    if st == "ASSIGNMENT":
        return f"{indent}SET {raw_snippet(abs_path, stmt['start_line'], stmt['end_line']).rstrip(';')}"
    if st == "CALL":
        target = stmt.get("call_target", "?")
        note = "" if stmt.get("resolved") else "  !! target not found locally — external or typo"
        return f"{indent}CALL {target}{note}"
    if st == "IF":
        return f"{indent}IF {extract_condition(abs_path, stmt['start_line'], stmt['end_line'], 'THEN')} THEN"
    if st == "LOOP":
        header = raw_snippet(abs_path, stmt["start_line"], stmt["start_line"])
        if re.search(r"\bFOR\b", header, re.IGNORECASE):
            kind = "FOR each row/iteration"
        elif re.search(r"\bWHILE\b", header, re.IGNORECASE):
            kind = "WHILE condition holds"
        else:
            kind = "LOOP (until an EXIT is hit)"
        return f"{indent}REPEAT — {kind}"
    if st == "CASE":
        return f"{indent}SELECT CASE"
    if st == "EXCEPTION_HANDLER":
        return f"{indent}IF an error '{'+'.join(stmt.get('handler_for', [])) or 'OTHERS'}' occurs THEN"
    if st in ("BODY", "BLOCK"):
        return f"{indent}-- nested block"
    return f"{indent}-- {st}: see source line {stmt['start_line']}"


def render_object_pseudocode(statements: dict, abs_path: str) -> list[str]:
    """
    Walk the statement tree via parent_id — NOT dict insertion order. A flat
    walk silently drops IF/ELSIF/ELSE branch structure, which is actively
    misleading: it makes three mutually-exclusive branches read as one
    sequential block.
    """
    if not abs_path:
        return []

    by_parent: dict[str | None, list[dict]] = {}
    for s in statements.values():
        by_parent.setdefault(s["parent_id"], []).append(s)
    for group in by_parent.values():
        group.sort(key=lambda s: _seq_num(s["statement_id"]))

    def branch_children(if_stmt: dict, suffix: str) -> list[dict]:
        target = f"IF#{_seq_num(if_stmt['statement_id'])}.{suffix}"
        return [c for c in by_parent.get(if_stmt["statement_id"], [])
                if c.get("scope_path", [])[-1:] == [target]]

    def render_block(stmt_list: list[dict]) -> list[str]:
        out = []
        for s in stmt_list:
            out.append(translate_statement(s, abs_path))
            st = s["statement_type"]
            if st == "IF":
                out.extend(render_block(branch_children(s, "THEN")))
                indent = "  " * (s.get("nesting_depth", 1) - 1)
                for i, cond in enumerate(
                        extract_elsif_conditions(abs_path, s["start_line"], s["end_line"]), start=1):
                    out.append(f"{indent}ELSIF {cond} THEN")
                    out.extend(render_block(branch_children(s, f"ELSIF{i}")))
                if has_else_branch(abs_path, s["start_line"], s["end_line"]):
                    out.append(f"{indent}ELSE")
                    out.extend(render_block(branch_children(s, "ELSE")))
                out.append(f"{indent}END IF")
            elif st == "LOOP":
                out.extend(render_block(by_parent.get(s["statement_id"], [])))
                out.append(f"{'  ' * (s.get('nesting_depth', 1) - 1)}END REPEAT")
            elif st in ("BODY", "BLOCK", "EXCEPTION_HANDLER", "CASE"):
                out.extend(render_block(by_parent.get(s["statement_id"], [])))
        return out

    top = by_parent.get(None, [])
    main = [s for s in top if s["statement_type"] != "EXCEPTION_HANDLER"]
    handlers = [s for s in top if s["statement_type"] == "EXCEPTION_HANDLER"]

    rendered = render_block(main)
    if handlers:
        rendered.append("EXCEPTION HANDLING:")
        rendered.extend(render_block(handlers))
    return rendered


def classify_loop(abs_path: str, stmt: dict) -> str:
    header = raw_snippet(abs_path, stmt["start_line"], stmt["start_line"])
    if re.search(r"\bFOR\b.*\bIN\b", header, re.IGNORECASE):
        return "COUNTED_OR_CURSOR_LOOP"
    if re.search(r"\bWHILE\b", header, re.IGNORECASE):
        return "CONDITIONAL_LOOP"
    return "UNBOUNDED_LOOP_NEEDS_EXIT"


def build_narrative(object_id: str, obj_type: str, statements: dict,
                    shape: dict, cyclo: dict, cog: dict, txn: dict) -> str:
    tables = sorted({t for s in statements.values() for t in (s.get("tables") or [])})
    calls = sorted({s["call_target"] for s in statements.values()
                    if s.get("statement_type") == "CALL" and s.get("call_target")})
    handlers = [s for s in statements.values() if s["statement_type"] == "EXCEPTION_HANDLER"]

    parts = [f"{object_id} is a {obj_type.replace('_', ' ').lower()} classified as {shape['shape']}.",
             shape["rationale"]]
    if tables:
        parts.append(f"It accesses: {', '.join(tables)}.")
    if calls:
        parts.append(f"It calls: {', '.join(calls)}.")
    if handlers:
        # De-duplicate: the same exception name legitimately appears in more
        # than one handler when nested blocks each catch it (e.g. two inner
        # blocks both catching NO_DATA_FOUND). Listing it twice reads as an
        # error in the document.
        named: list[str] = []
        for h in handlers:
            for name in h.get("handler_for") or []:
                if name.upper() != "OTHERS" and name not in named:
                    named.append(name)
        suffix = f", including {', '.join(named[:3])}." if named else "."
        parts.append(f"It handles {len(handlers)} error condition(s){suffix}")
    parts.append(f"Testability (cyclomatic) {cyclo['score']} — {cyclo['interpretation']}; "
                 f"understandability (cognitive) {cog['score']} — {cog['interpretation']}.")
    if txn["hazards"]:
        high = [h for h in txn["hazards"] if h["severity"] == "high"]
        if high:
            parts.append(f"Migration hazard: {', '.join(h['hazard'] for h in high)}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def analyse_object(object_id: str, obj: dict, abs_path: str) -> dict:
    statements = obj.get("statements", {})

    cyclo = compute_cyclomatic(statements, abs_path)
    cog = compute_cognitive(statements, abs_path)
    txn = analyse_transactions(statements)
    crud = build_crud(statements)
    shape = classify_shape(statements, obj.get("type", ""))

    # Indexes for slicing
    writes_index: dict[str, list[str]] = {}
    reads_index: dict[str, set[str]] = {}
    for s in statements.values():
        tgts, srcs = assignment_targets_and_sources(s, abs_path)
        reads_index[s["statement_id"]] = srcs
        for t in tgts:
            writes_index.setdefault(t, []).append(s["statement_id"])

    slice_vars = [d["name"] for d in obj.get("declarations", [])] + \
                 [p["name"] for p in obj.get("parameters", []) if "OUT" in (p.get("mode") or "")]
    slices = [slice_for_variable(v, statements, abs_path, writes_index, reads_index)
              for v in slice_vars]
    slices = [s for s in slices if s["statement_count"] > 0]

    loops = []
    for s in statements.values():
        if s["statement_type"] != "LOOP":
            continue
        kind = classify_loop(abs_path, s)
        entry = {"statement_id": s["statement_id"], "line": s["start_line"], "termination_pattern": kind}
        if kind == "UNBOUNDED_LOOP_NEEDS_EXIT":
            has_exit = any(c["statement_type"] == "EXIT" for c in statements.values()
                           if c.get("parent_id") == s["statement_id"])
            if not has_exit:
                entry["warning"] = "no EXIT found directly inside this loop body"
        loops.append(entry)

    return {
        "object_id": object_id, "type": obj.get("type"), "file_id": obj.get("file_id"),
        "narrative": build_narrative(object_id, obj.get("type", ""), statements, shape, cyclo, cog, txn),
        "shape": shape,
        "complexity": {"cyclomatic": cyclo, "cognitive": cog},
        "pseudocode": render_object_pseudocode(statements, abs_path),
        "variable_slices": slices,
        "transactions": txn,
        "crud_matrix": crud,
        "loops": loops,
        "statement_count": len(statements),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 4: Deterministic PL/SQL logic analyser")
    ap.add_argument("--parser-root", default="output/parser")
    ap.add_argument("--parser-run", default="latest")
    ap.add_argument("--inventory-root", default="output/inventory")
    ap.add_argument("--inventory-run", default="latest")
    ap.add_argument("--output-root", default="output/logic")
    ap.add_argument("--output", default=None)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    parser_artifact, parser_rv = load_run(args.parser_root, args.parser_run, "parser_artifact.json")
    inventory, inv_rv = load_run(args.inventory_root, args.inventory_run, "inventory-artifact.json")
    parser_root = Path(args.parser_root) / parser_rv
    file_abs_paths = {fid: m["abs_path"] for fid, m in inventory["file_metadata"].items() if m.get("abs_path")}

    versioned = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned else Path(args.output)
    logic_dir = run_dir / "program_logic"
    logic_dir.mkdir(parents=True, exist_ok=True)

    object_index: dict[str, str] = {}
    call_targets: set[str] = set()
    stats = {"objects_processed": 0, "statements_translated": 0, "variable_slices": 0,
             "loops_classified": 0, "unbounded_loops_without_exit": 0,
             "objects_exceeding_cyclomatic_threshold": 0, "objects_exceeding_cognitive_threshold": 0,
             "objects_with_transaction_hazards": 0, "commit_inside_loop": 0,
             "savepoint_usage": 0, "objects_with_no_internal_callers": 0}
    global_crud: dict[str, dict[str, str]] = {}
    shapes: dict[str, int] = {}

    for object_id, rel_path in parser_artifact["object_index"].items():
        p = parser_root / rel_path
        if not p.exists():
            continue
        obj = json.loads(p.read_text(encoding="utf-8"))
        if obj.get("parse_status") != "success":
            continue
        abs_path = file_abs_paths.get(obj.get("file_id"))
        if not abs_path:
            continue
        if args.verbose:
            print(f"  [analysing] {object_id}", file=sys.stderr)

        rec = analyse_object(object_id, obj, abs_path)
        out_name = object_id.replace("::", "__").replace("/", "_") + "_logic.json"
        (logic_dir / out_name).write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        object_index[object_id] = f"program_logic/{out_name}"

        stats["objects_processed"] += 1
        stats["statements_translated"] += len(rec["pseudocode"])
        stats["variable_slices"] += len(rec["variable_slices"])
        stats["loops_classified"] += len(rec["loops"])
        stats["unbounded_loops_without_exit"] += sum(1 for l in rec["loops"] if l.get("warning"))
        if rec["complexity"]["cyclomatic"]["exceeds_threshold"]:
            stats["objects_exceeding_cyclomatic_threshold"] += 1
        if rec["complexity"]["cognitive"]["exceeds_threshold"]:
            stats["objects_exceeding_cognitive_threshold"] += 1
        if any(h["severity"] == "high" for h in rec["transactions"]["hazards"]):
            stats["objects_with_transaction_hazards"] += 1
        stats["commit_inside_loop"] += len(rec["transactions"]["commit_inside_loop"])
        stats["savepoint_usage"] += len(rec["transactions"]["savepoints"])
        global_crud[object_id] = rec["crud_matrix"]
        shapes[rec["shape"]["shape"]] = shapes.get(rec["shape"]["shape"], 0) + 1

        for s in obj.get("statements", {}).values():
            if s.get("statement_type") == "CALL" and s.get("call_target_object_id"):
                call_targets.add(s["call_target_object_id"])

    stats["objects_with_no_internal_callers"] = sum(1 for oid in object_index if oid not in call_targets)

    logic_artifact = {
        "pipeline_stage": "4_logic", "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {"parser_run_version": parser_rv, "inventory_run_version": inv_rv},
        "design_references": DESIGN_REFERENCES,
        "stats": stats,
        "shape_distribution": shapes,
        "crud_matrix": global_crud,
        "object_index": object_index,
        "note_on_no_internal_callers": "Informational only, NOT confirmed dead code — PL/SQL objects are "
                                       "routinely invoked by schedulers, other schemas, or application "
                                       "code entirely outside this repository.",
    }
    (run_dir / "logic_artifact.json").write_text(
        json.dumps(logic_artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned:
        (run_dir / "run_meta.json").write_text(json.dumps(
            {"stage": "4_logic", "run_version": run_version, "status": "success",
             "generated_at": logic_artifact["generated_at"], "upstream": logic_artifact["upstream"],
             "stats_summary": stats}, indent=2), encoding="utf-8")
        (Path(args.output_root) / "latest.json").write_text(json.dumps(
            {"run_version": run_version, "path": f"{run_version}/logic_artifact.json",
             "updated_at": logic_artifact["generated_at"]}, indent=2), encoding="utf-8")

    print("=== Logic Agent Complete ===")
    print(f"Objects analysed            : {stats['objects_processed']}")
    print(f"Pseudocode lines            : {stats['statements_translated']}")
    print(f"Variable slices             : {stats['variable_slices']}")
    print(f"Shapes                      : {shapes}")
    print(f"Over cyclomatic threshold   : {stats['objects_exceeding_cyclomatic_threshold']} (>{CYCLOMATIC_THRESHOLD})")
    print(f"Over cognitive threshold    : {stats['objects_exceeding_cognitive_threshold']} (>{COGNITIVE_THRESHOLD})")
    print(f"Transaction hazards         : {stats['objects_with_transaction_hazards']} object(s)")
    print(f"  [!] COMMIT inside loop    : {stats['commit_inside_loop']}")
    print(f"  [!] SAVEPOINT usage       : {stats['savepoint_usage']}")
    print(f"Unbounded loops w/o EXIT    : {stats['unbounded_loops_without_exit']}")
    print(f"No internal callers (info)  : {stats['objects_with_no_internal_callers']}")
    print(f"Output                      : {run_dir / 'logic_artifact.json'}")
    print("=============================")


if __name__ == "__main__":
    main()
