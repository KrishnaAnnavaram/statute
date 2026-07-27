#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/04_logic.py.

The headline case here is a regression guard for a real bug found during
development: a flat walk over the statements dict silently dropped IF/
ELSIF/ELSE branch structure, making three mutually-exclusive branches read
as one sequential block — actively misleading, not just incomplete. Also
guards the root cause (per-line vs per-blob comment stripping) so it can't
resurface in a different statement type.

Usage:
    python tests/test_logic.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY_SCRIPT = ROOT / ".claude" / "scripts" / "00_inventory.py"
PARSER_SCRIPT = ROOT / ".claude" / "scripts" / "02_parser.py"
LOGIC_SCRIPT = ROOT / ".claude" / "scripts" / "04_logic.py"

sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def run_pipeline(sql_dir: Path, work_dir: Path) -> dict:
    inv_dir = work_dir / "inventory"
    subprocess.run([sys.executable, str(INVENTORY_SCRIPT), str(sql_dir),
                     "--output", str(inv_dir / "run" / "inventory-artifact.json")],
                    capture_output=True, text=True, check=True)
    (inv_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "test"}))

    parser_dir = work_dir / "parser"
    subprocess.run([sys.executable, str(PARSER_SCRIPT), "--inventory-root", str(inv_dir),
                     "--output", str(parser_dir / "run")], capture_output=True, text=True, check=True)
    (parser_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/parser_artifact.json", "updated_at": "test"}))

    logic_dir = work_dir / "logic_out"
    r = subprocess.run([sys.executable, str(LOGIC_SCRIPT), "--parser-root", str(parser_dir),
                         "--inventory-root", str(inv_dir), "--output", str(logic_dir)],
                        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"04_logic.py failed:\n{r.stdout}\n{r.stderr}")
    print(r.stdout)
    return json.loads((logic_dir / "logic_artifact.json").read_text(encoding="utf-8"))


def test_if_elsif_else_structure_preserved(work_dir: Path) -> None:
    print("\n=== Regression guard: IF/ELSIF/ELSE must not flatten into one block ===")
    artifact = run_pipeline(ROOT / "src", work_dir)
    logic_dir = work_dir / "logic_out"
    rel = artifact["object_index"]["PROC-.SP_UPDATE_DORMANT_ACCOUNT_STATUS"]
    record = json.loads((logic_dir / rel).read_text(encoding="utf-8"))
    code = record["pseudocode"]

    check(any(l.startswith("IF ") and "THEN" in l for l in code), "IF header present")
    check(any(l.strip().startswith("ELSIF ") for l in code), "ELSIF header present (this is the exact bug that was fixed)")
    check(any(l.strip() == "ELSE" for l in code), "ELSE header present (was silently eaten by a per-blob comment-strip bug)")
    check(any(l.strip() == "END IF" for l in code), "END IF closes the block")

    if_idx = next(i for i, l in enumerate(code) if l.startswith("IF "))
    elsif_idx = next(i for i, l in enumerate(code) if l.strip().startswith("ELSIF "))
    else_idx = next(i for i, l in enumerate(code) if l.strip() == "ELSE")
    endif_idx = next(i for i, l in enumerate(code) if l.strip() == "END IF")
    check(if_idx < elsif_idx < else_idx < endif_idx, "branch headers appear in correct source order")

    check(any("ACCOUNT_REACTIVATED" in l for l in code[if_idx:elsif_idx]) is False,
          "THEN-branch content does not leak the ELSIF-branch's result value")
    check(any("NO_STATUS_CHANGE_REQUIRED" in l for l in code[elsif_idx:else_idx]) is False,
          "ELSIF-branch content does not leak the ELSE-branch's result value")

    check(any(l == "EXCEPTION HANDLING:" for l in code), "exception handlers get their own trailing section")
    check(code.index("EXCEPTION HANDLING:") > endif_idx, "exception section comes after the main body, not interleaved")

    where_line = next(l for l in code if "WHERE" in l)
    check(" = " in where_line and "," not in where_line.split("WHERE")[1],
          "a 2-item predicate renders as 'col = value', not an ambiguous comma list")


def test_loop_classification_and_complexity() -> None:
    print("\n=== Direct unit test: loop classification, complexity scoring ===")
    import importlib
    lg = importlib.import_module("04_logic")

    stmt_for = {"start_line": 10, "end_line": 10}
    stmt_while = {"start_line": 20, "end_line": 20}
    stmt_bare = {"start_line": 30, "end_line": 30}

    tmp_sql = ROOT / "tests" / "fixtures" / "sample_plsql" / "02_account_mgmt.sql"
    # Use a controlled synthetic file instead of a real one so line numbers are exact.
    synthetic = Path(tempfile.mktemp(suffix=".sql"))
    synthetic.write_text(
        "-- line 1\n"
        "FOR i IN 1..10 LOOP\n"          # line 2 -> FOR
        "  NULL;\n"
        "END LOOP;\n"
        "WHILE done = 'N' LOOP\n"        # line 5 -> WHILE
        "  NULL;\n"
        "END LOOP;\n"
        "LOOP\n"                          # line 8 -> bare
        "  NULL;\n"
        "END LOOP;\n",
        encoding="utf-8",
    )
    try:
        check(lg.classify_loop(str(synthetic), {"start_line": 2}) == "COUNTED_OR_CURSOR_LOOP", "FOR..IN loop classified as counted/cursor")
        check(lg.classify_loop(str(synthetic), {"start_line": 5}) == "CONDITIONAL_LOOP", "WHILE loop classified as conditional")
        check(lg.classify_loop(str(synthetic), {"start_line": 8}) == "UNBOUNDED_LOOP_NEEDS_EXIT", "bare LOOP classified as needing an EXIT")
    finally:
        synthetic.unlink(missing_ok=True)

    statements = {
        "a": {"statement_type": "IF", "nesting_depth": 1},
        "b": {"statement_type": "SELECT_INTO", "nesting_depth": 3},
        "c": {"statement_type": "DYNAMIC_SQL", "nesting_depth": 1},
    }
    score = lg.compute_complexity(statements)
    check(score == 1 + (1 + 1) + 3, f"complexity score weights DYNAMIC_SQL heavily and depth>=3 nesting extra, got {score}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        test_if_elsif_else_structure_preserved(Path(tmp))
    test_loop_classification_and_complexity()

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
