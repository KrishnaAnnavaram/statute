#!/usr/bin/env python3
"""
Stage 4: LOGIC (deterministic, no LLM)
-----------------------------------------
Reads Agent 2 (parser) + Agent 3 (data) output. Agent 2 already extracted
full statement structure and a control-flow graph (unlike the COBOL
reference pipeline this project is modeled after, whose parser only found
paragraph boundaries and needed a whole separate agent to re-derive
structure). So this agent's real job is narrower: TRANSLATE each object's
statement tree into readable pseudocode, and produce a short narrative.

Where Agent 2 already captured structured fields (tables/reads/writes/
predicate_reads/call_target/handler_for), pseudocode is built from those.
Where it didn't (ASSIGNMENT, IF/LOOP condition text, RAISE/RETURN), this
agent re-slices the statement's [start_line, end_line] from the original
source file — the same technique the reference pipeline's own
pseudocode-generator skill uses ("read the raw source lines").

Deliberately NOT done here: COBOL-style confident dead-code detection.
PL/SQL procedures are routinely invoked by schedulers, other schemas, or
application code entirely outside this repo, so "no internal callers
found" is reported as informational only, never as confirmed dead code.

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
    artifact_path = root_path / run_version / artifact_filename
    return json.loads(artifact_path.read_text(encoding="utf-8")), run_version


# ---------------------------------------------------------------------------
# Raw-source re-slicing helper
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
    lines = source_lines(abs_path)
    if not lines or start < 1:
        return ""
    # Strip trailing `--` comments PER LINE, before joining — stripping on
    # the joined blob truncates everything after the first comment anywhere
    # in the range, silently eating real statements (e.g. an ELSE/END IF
    # that comes after an earlier commented line).
    cleaned = [re.sub(r"--.*", "", l).strip() for l in lines[start - 1:end]]
    return re.sub(r"\s+", " ", " ".join(cleaned)).strip()


def render_predicate(predicate_reads: list[str]) -> str:
    """
    predicate_reads is a flat list of every column-like identifier sqlglot
    found in a WHERE clause — it doesn't preserve which side of an `=` each
    one was on. The overwhelmingly common real-world shape is a single
    `column = bind_value` match, so render exactly 2 items that way rather
    than as an ambiguous comma list; anything else falls back to "matching
    on:" so it never implies structure we don't actually have.
    """
    if not predicate_reads:
        return ""
    if len(predicate_reads) == 2:
        return f" WHERE {predicate_reads[0]} = {predicate_reads[1]}"
    return f" (matching on: {', '.join(predicate_reads)})"


def extract_condition(abs_path: str, start: int, end: int, stop_keyword: str) -> str:
    snippet = raw_snippet(abs_path, start, end)
    m = re.search(r"^\s*(?:IF|ELSIF|WHILE)\s+(.*?)\s+" + stop_keyword + r"\b", snippet, re.IGNORECASE)
    return m.group(1).strip() if m else snippet


def extract_elsif_conditions(abs_path: str, start: int, end: int) -> list[str]:
    full_text = raw_snippet(abs_path, start, end)
    return [m.strip() for m in re.findall(r"\bELSIF\s+(.*?)\s+THEN\b", full_text, re.IGNORECASE)]


def has_else_branch(abs_path: str, start: int, end: int) -> bool:
    full_text = raw_snippet(abs_path, start, end)
    return re.search(r"\bELSE\b", full_text, re.IGNORECASE) is not None


# ---------------------------------------------------------------------------
# Pseudocode translation catalogue
# ---------------------------------------------------------------------------

def translate_statement(stmt: dict, abs_path: str) -> str:
    st = stmt["statement_type"]
    indent = "  " * (stmt.get("nesting_depth", 1) - 1)

    if st == "SELECT_INTO":
        cols = ", ".join(stmt.get("reads", [])) or "columns"
        tables = ", ".join(stmt.get("tables", [])) or "?"
        where = render_predicate(stmt.get("predicate_reads", []))
        return f"{indent}LOOK UP {cols} FROM {tables}{where}"
    if st == "SELECT":
        cols = ", ".join(stmt.get("reads", [])) or "columns"
        tables = ", ".join(stmt.get("tables", [])) or "?"
        return f"{indent}READ {cols} FROM {tables}"
    if st == "UPDATE":
        writes = ", ".join(stmt.get("writes", [])) or "columns"
        tables = ", ".join(stmt.get("tables", [])) or "?"
        where = render_predicate(stmt.get("predicate_reads", []))
        return f"{indent}UPDATE {tables}: SET {writes}{where}"
    if st == "INSERT":
        tables = ", ".join(stmt.get("tables", [])) or "?"
        return f"{indent}INSERT a new row INTO {tables}"
    if st == "DELETE":
        tables = ", ".join(stmt.get("tables", [])) or "?"
        where = render_predicate(stmt.get("predicate_reads", []))
        return f"{indent}DELETE FROM {tables}{where}"
    if st == "MERGE":
        return f"{indent}MERGE data into {', '.join(stmt.get('tables', [])) or '?'}  -- complex; see source, line {stmt['start_line']}"
    if st == "DYNAMIC_SQL":
        return f"{indent}!! DYNAMIC SQL (EXECUTE IMMEDIATE) — target cannot be known statically, see source line {stmt['start_line']}"
    if st == "COMMIT":
        return f"{indent}COMMIT the transaction"
    if st == "ROLLBACK":
        return f"{indent}ROLL BACK the transaction"
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
        snippet = raw_snippet(abs_path, stmt["start_line"], stmt["end_line"]).rstrip(";")
        return f"{indent}SET {snippet}"
    if st == "CALL":
        target = stmt.get("call_target", "?")
        resolved_note = "" if stmt.get("resolved") else "  !! target not found locally — external or typo"
        return f"{indent}CALL {target}{resolved_note}"
    if st == "IF":
        cond = extract_condition(abs_path, stmt["start_line"], stmt["end_line"], "THEN")
        return f"{indent}IF {cond} THEN"
    if st == "LOOP":
        header = raw_snippet(abs_path, stmt["start_line"], stmt["start_line"])
        if re.search(r"\bFOR\b", header, re.IGNORECASE):
            kind = "FOR each iteration"
        elif re.search(r"\bWHILE\b", header, re.IGNORECASE):
            kind = "WHILE condition holds"
        else:
            kind = "LOOP (until an EXIT is hit)"
        return f"{indent}REPEAT — {kind}"
    if st == "CASE":
        return f"{indent}SELECT CASE"
    if st == "EXCEPTION_HANDLER":
        handlers = "+".join(stmt.get("handler_for", [])) or "OTHERS"
        return f"{indent}IF an error '{handlers}' occurs THEN"
    if st in ("BODY", "BLOCK"):
        return f"{indent}-- nested block"
    return f"{indent}-- {st}: see source line {stmt['start_line']}"


def _seq_num(statement_id: str) -> int:
    m = re.search(r"STMT_(\d+)$", statement_id)
    return int(m.group(1)) if m else 0


def render_object_pseudocode(statements: dict, abs_path: str) -> list[str]:
    """
    Walk the statement tree via parent_id (NOT dict insertion order — a flat
    walk silently drops IF/ELSIF/ELSE branch structure, which is actively
    misleading: it makes three mutually-exclusive branches read as one
    sequential block). Recreates THEN/ELSIF/ELSE and loop bodies as their
    own indented sections with the correct header line, and separates
    EXCEPTION handlers into their own trailing section.
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
        return [c for c in by_parent.get(if_stmt["statement_id"], []) if c.get("scope_path", [])[-1:] == [target]]

    def render_block(stmt_list: list[dict]) -> list[str]:
        out = []
        for s in stmt_list:
            out.append(translate_statement(s, abs_path))
            if s["statement_type"] == "IF":
                out.extend(render_block(branch_children(s, "THEN")))
                elsif_conditions = extract_elsif_conditions(abs_path, s["start_line"], s["end_line"])
                indent = "  " * (s.get("nesting_depth", 1) - 1)
                for i, cond in enumerate(elsif_conditions, start=1):
                    out.append(f"{indent}ELSIF {cond} THEN")
                    out.extend(render_block(branch_children(s, f"ELSIF{i}")))
                if has_else_branch(abs_path, s["start_line"], s["end_line"]):
                    out.append(f"{indent}ELSE")
                    out.extend(render_block(branch_children(s, "ELSE")))
                out.append(f"{indent}END IF")
            elif s["statement_type"] == "LOOP":
                out.extend(render_block(by_parent.get(s["statement_id"], [])))
                indent = "  " * (s.get("nesting_depth", 1) - 1)
                out.append(f"{indent}END REPEAT")
            elif s["statement_type"] in ("BODY", "BLOCK", "EXCEPTION_HANDLER"):
                out.extend(render_block(by_parent.get(s["statement_id"], [])))
        return out

    top_level = by_parent.get(None, [])
    main_body = [s for s in top_level if s["statement_type"] != "EXCEPTION_HANDLER"]
    handlers = [s for s in top_level if s["statement_type"] == "EXCEPTION_HANDLER"]

    rendered = render_block(main_body)
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


COMPLEXITY_WEIGHTS = {
    "IF": 1, "CASE": 1, "LOOP": 1, "CALL": 1, "EXCEPTION_HANDLER": 1,
    "SELECT_INTO": 1, "SELECT": 1, "UPDATE": 1, "INSERT": 1, "DELETE": 1, "MERGE": 1,
    "DYNAMIC_SQL": 3,
}


def compute_complexity(statements: dict) -> int:
    score = 0
    for s in statements.values():
        score += COMPLEXITY_WEIGHTS.get(s["statement_type"], 0)
        if s.get("nesting_depth", 1) >= 3:
            score += 1
    return score


def build_narrative(object_id: str, obj_type: str, statements: dict) -> str:
    dml_tables = sorted({t for s in statements.values() for t in s.get("tables", [])})
    calls = sorted({s["call_target"] for s in statements.values() if s.get("statement_type") == "CALL"})
    exc_count = sum(1 for s in statements.values() if s["statement_type"] == "EXCEPTION_HANDLER")
    parts = [f"{object_id} is a {obj_type.replace('_', ' ').lower()}."]
    if dml_tables:
        parts.append(f"It reads and/or writes: {', '.join(dml_tables)}.")
    if calls:
        parts.append(f"It calls: {', '.join(calls)}.")
    if exc_count:
        parts.append(f"It handles {exc_count} exception case(s).")
    return " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 4: Deterministic PL/SQL logic/pseudocode generator")
    ap.add_argument("--parser-root", default="output/parser")
    ap.add_argument("--parser-run", default="latest")
    ap.add_argument("--inventory-root", default="output/inventory")
    ap.add_argument("--inventory-run", default="latest")
    ap.add_argument("--output-root", default="output/logic")
    ap.add_argument("--output", default=None)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    parser_artifact, parser_run_version = load_run(args.parser_root, args.parser_run, "parser_artifact.json")
    inventory, inv_run_version = load_run(args.inventory_root, args.inventory_run, "inventory-artifact.json")
    parser_root = Path(args.parser_root) / parser_run_version

    file_abs_paths = {fid: meta["abs_path"] for fid, meta in inventory["file_metadata"].items()}

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    logic_dir = run_dir / "program_logic"
    logic_dir.mkdir(parents=True, exist_ok=True)

    object_index: dict[str, str] = {}
    all_call_targets: set[str] = set()
    stats = {"objects_processed": 0, "statements_translated": 0, "loops_classified": 0,
              "unbounded_loops_without_exit": 0, "objects_with_no_internal_callers": 0,
              "dynamic_sql_flags": 0}

    for object_id, rel_path in parser_artifact["object_index"].items():
        obj_path = parser_root / rel_path
        if not obj_path.exists():
            continue
        obj = json.loads(obj_path.read_text(encoding="utf-8"))
        if obj.get("parse_status") != "success":
            continue
        abs_path = file_abs_paths.get(obj["file_id"])
        statements = obj.get("statements", {})

        pseudocode = render_object_pseudocode(statements, abs_path)
        loops = []
        for s in statements.values():
            if s["statement_type"] == "LOOP" and abs_path:
                kind = classify_loop(abs_path, s)
                loops.append({"statement_id": s["statement_id"], "termination_pattern": kind})
                stats["loops_classified"] += 1
                if kind == "UNBOUNDED_LOOP_NEEDS_EXIT":
                    has_exit = any(c["statement_type"] == "EXIT" for c in statements.values()
                                   if c["parent_id"] == s["statement_id"])
                    if not has_exit:
                        stats["unbounded_loops_without_exit"] += 1
                        loops[-1]["warning"] = "no EXIT found directly inside this loop body"

            if s["statement_type"] == "CALL" and s.get("resolved") and s.get("call_target_object_id"):
                all_call_targets.add(s["call_target_object_id"])
            if s.get("requires_manual_review"):
                stats["dynamic_sql_flags"] += 1

        logic_record = {
            "object_id": object_id, "type": obj["type"], "file_id": obj["file_id"],
            "narrative": build_narrative(object_id, obj["type"], statements),
            "complexity_score": compute_complexity(statements),
            "pseudocode": pseudocode,
            "loops": loops,
            "statement_count": len(statements),
        }
        out_name = object_id.replace("::", "__").replace("/", "_") + "_logic.json"
        (logic_dir / out_name).write_text(json.dumps(logic_record, indent=2, ensure_ascii=False), encoding="utf-8")
        object_index[object_id] = f"program_logic/{out_name}"
        stats["objects_processed"] += 1
        stats["statements_translated"] += len(pseudocode)

    for object_id in parser_artifact["object_index"]:
        if object_id not in all_call_targets and object_id in object_index:
            stats["objects_with_no_internal_callers"] += 1

    logic_artifact = {
        "pipeline_stage": "4_logic", "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {"parser_run_version": parser_run_version, "inventory_run_version": inv_run_version},
        "stats": stats,
        "object_index": object_index,
        "note_on_no_internal_callers": "Informational only, NOT confirmed dead code — PL/SQL objects "
                                        "are routinely invoked by schedulers, other schemas, or "
                                        "application code entirely outside this repo.",
    }
    (run_dir / "logic_artifact.json").write_text(json.dumps(logic_artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        run_meta = {"stage": "4_logic", "run_version": run_version, "status": "success",
                     "generated_at": logic_artifact["generated_at"], "upstream": logic_artifact["upstream"],
                     "stats_summary": stats}
        (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2, ensure_ascii=False), encoding="utf-8")
        (Path(args.output_root) / "latest.json").write_text(json.dumps(
            {"run_version": run_version, "path": f"{run_version}/logic_artifact.json",
             "updated_at": logic_artifact["generated_at"]}, indent=2), encoding="utf-8")

    print("=== Logic Agent Complete ===")
    print(f"Objects processed          : {stats['objects_processed']}")
    print(f"Statements translated      : {stats['statements_translated']}")
    print(f"Loops classified           : {stats['loops_classified']}")
    print(f"Unbounded loops w/o EXIT   : {stats['unbounded_loops_without_exit']}")
    print(f"No internal callers (info) : {stats['objects_with_no_internal_callers']}")
    print(f"Dynamic SQL flags          : {stats['dynamic_sql_flags']}")
    print(f"Output                     : {run_dir / 'logic_artifact.json'}")
    print("=============================")


if __name__ == "__main__":
    main()
