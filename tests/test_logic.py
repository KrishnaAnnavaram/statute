#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/04_logic.py (schema_version 2.0).

The headline test validates our Cognitive Complexity implementation against
G. Ann Campbell's OWN published worked example (whitepaper p.9), not against
our own expectations. If our arithmetic disagrees with the metric author's,
our implementation is wrong — regardless of how reasonable it looks.

Also covered:
  - McCabe cyclomatic complexity, hand-verifiable on a real procedure
  - transaction hazards (COMMIT-in-loop, SAVEPOINT, no-transaction-control)
  - variable-centric backward slicing
  - CRUD matrix and shape classification
  - the v1 regression guards that must not rot: IF/ELSIF/ELSE structure must
    never flatten, and per-line comment stripping must not swallow an ELSE

Usage:
    python tests/test_logic.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "scripts"
LOGIC_FIXTURES = ROOT / "tests" / "fixtures" / "sample_logic"

sys.path.insert(0, str(SCRIPTS))

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def run_pipeline(sql_dir: Path, work_dir: Path) -> tuple[dict, Path]:
    inv = work_dir / "inventory"
    subprocess.run([sys.executable, str(SCRIPTS / "01_inventory.py"), str(sql_dir),
                    "--output", str(inv / "run" / "inventory-artifact.json")],
                   capture_output=True, text=True, check=True)
    (inv / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "t"}))

    parser = work_dir / "parser"
    subprocess.run([sys.executable, str(SCRIPTS / "02_parser.py"), "--inventory-root", str(inv),
                    "--output", str(parser / "run")], capture_output=True, text=True, check=True)
    (parser / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/parser_artifact.json", "updated_at": "t"}))

    logic = work_dir / "logic_out"
    r = subprocess.run([sys.executable, str(SCRIPTS / "04_logic.py"), "--parser-root", str(parser),
                        "--inventory-root", str(inv), "--output", str(logic)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"04_logic.py failed:\n{r.stdout}\n{r.stderr}")
    print(r.stdout)
    return json.loads((logic / "logic_artifact.json").read_text(encoding="utf-8")), logic


def load_object(artifact: dict, logic_dir: Path, object_id: str) -> dict:
    return json.loads((logic_dir / artifact["object_index"][object_id]).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Cognitive Complexity vs. the metric author's own worked example
# ---------------------------------------------------------------------------

def test_campbell_worked_example(work_dir: Path) -> None:
    print("\n=== Cognitive Complexity vs Campbell's published worked example (expect 9) ===")
    art, logic_dir = run_pipeline(LOGIC_FIXTURES, work_dir / "campbell")
    rec = load_object(art, logic_dir, "PROC-.SP_CAMPBELL_EXAMPLE")
    cog = rec["complexity"]["cognitive"]

    check(cog["score"] == 9,
          f"Cognitive Complexity == 9, matching the whitepaper's own arithmetic (got {cog['score']})")

    b = cog["breakdown"]
    # if(+1) + for(+1) + while(+1) + catch(+1) + if-in-catch(+1) = 5 structural
    check(b["structural"] == 5, f"5 structural increments (if, for, while, catch, if-in-catch), got {b['structural']}")
    # for at nesting 1, while at nesting 2, if-in-catch at nesting 1 = 4
    check(b["nesting"] == 4, f"4 nesting increments (1+2+1), got {b['nesting']}")
    check(b["hybrid_else_elsif"] == 0, "no ELSIF/ELSE in this example")
    check(b["logical_sequences"] == 0, "no compound boolean conditions in this example")

    print("\n  -- the enclosing block must NOT increment (Campbell: try is ignored) --")
    check(cog["score"] != 10, "nested BEGIN block correctly adds no increment of its own")


# ---------------------------------------------------------------------------
# 2. Transaction hazards
# ---------------------------------------------------------------------------

def test_transaction_hazards(work_dir: Path) -> None:
    print("\n=== Transaction boundary analysis ===")
    art, logic_dir = run_pipeline(LOGIC_FIXTURES, work_dir / "txn")

    loop_commit = load_object(art, logic_dir, "PROC-.SP_INCREMENTAL_COMMIT")
    hazards = {h["hazard"]: h for h in loop_commit["transactions"]["hazards"]}
    check("COMMIT_INSIDE_LOOP" in hazards, "COMMIT inside a cursor loop detected")
    if "COMMIT_INSIDE_LOOP" in hazards:
        check(hazards["COMMIT_INSIDE_LOOP"]["severity"] == "high", "commit-in-loop rated high severity")
        check("ORA-01555" in hazards["COMMIT_INSIDE_LOOP"]["explanation"],
              "explanation cites the actual Oracle failure mode (ORA-01555)")
    check(len(loop_commit["transactions"]["commit_inside_loop"]) == 1, "exactly one commit-in-loop occurrence")
    check(loop_commit["transactions"]["is_atomic"] is False, "commit-in-loop procedure is not atomic")
    check(loop_commit["shape"]["shape"] == "BATCH_PROCESSOR", "cursor loop with DML classified BATCH_PROCESSOR")
    check(loop_commit["shape"]["dml_inside_loop"] is True, "DML-inside-loop flag set")

    savepoint = load_object(art, logic_dir, "PROC-.SP_SAVEPOINT_USER")
    sp_haz = {h["hazard"] for h in savepoint["transactions"]["hazards"]}
    check("SAVEPOINT_PARTIAL_ROLLBACK" in sp_haz, "SAVEPOINT usage flagged as a migration hazard")
    check(len(savepoint["transactions"]["savepoints"]) == 1, "one SAVEPOINT recorded")
    check(len(savepoint["transactions"]["rollback_in_exception_handler"]) >= 1,
          "ROLLBACK inside an exception handler identified as compensating logic")

    none_ctl = load_object(art, logic_dir, "PROC-.SP_NO_TXN_CONTROL")
    nc_haz = {h["hazard"] for h in none_ctl["transactions"]["hazards"]}
    check("NO_TRANSACTION_CONTROL" in nc_haz, "absence of COMMIT/ROLLBACK reported (caller owns the boundary)")
    check(none_ctl["shape"]["shape"] == "QUERY_ONLY", "read-only procedure classified QUERY_ONLY")
    segs = none_ctl["transactions"]["transaction_segments"]
    check(any("no COMMIT" in (s.get("note") or "") for s in segs),
          "open transaction segment annotated as left to the caller")


# ---------------------------------------------------------------------------
# 3. Real production data — cyclomatic, slices, CRUD, structure guards
# ---------------------------------------------------------------------------

def test_real_src(work_dir: Path) -> None:
    print("\n=== Real src/ data ===")
    art, logic_dir = run_pipeline(ROOT / "src", work_dir / "real")
    rec = load_object(art, logic_dir, "PROC-.SP_UPDATE_DORMANT_ACCOUNT_STATUS")

    print("\n  -- McCabe cyclomatic (hand-verifiable) --")
    cyc = rec["complexity"]["cyclomatic"]
    # IF(1) + ELSIF(1) + 2 AND operators(2) + 2 exception handlers(2) = 6 decisions; +1 = 7
    check(cyc["score"] == 7, f"cyclomatic == 7 by hand-count, got {cyc['score']}")
    check(cyc["breakdown"]["if"] == 1 and cyc["breakdown"]["elsif"] == 1, "one IF and one ELSIF counted")
    check(cyc["breakdown"]["logical_operators"] == 2, "both AND operators counted as decisions (McCabe)")
    check(cyc["breakdown"]["exception_handler"] == 2, "both exception handlers counted")
    check(cyc["threshold"] == 10 and cyc["exceeds_threshold"] is False,
          "McCabe's threshold of 10 applied, not exceeded here")

    print("\n  -- the two metrics answer different questions --")
    cog = rec["complexity"]["cognitive"]
    check("test case" in cyc["means"].lower(), "cyclomatic explains itself as a test-case count")
    check("mental effort" in cog["means"].lower(), "cognitive explains itself as mental effort")

    print("\n  -- variable-centric backward slicing --")
    slices = {s["variable"]: s for s in rec["variable_slices"]}
    check("V_DAYS_INACTIVE" in slices, "slice computed for a derived local variable")
    if "V_DAYS_INACTIVE" in slices:
        sl = slices["V_DAYS_INACTIVE"]
        check(sl["statement_count"] >= 1, "slice contains the assigning statement")
        check("V_LAST_TXN_DATE" in sl["depends_on_variables"],
              "transitive dependency followed: v_days_inactive depends on v_last_txn_date")
    check("P_RESULT" in slices, "OUT parameter sliced (it is the procedure's output contract)")
    if "P_RESULT" in slices:
        check(slices["P_RESULT"]["statement_count"] >= 4,
              "p_result slice spans all branches that assign it, plus their controlling IF")

    print("\n  -- CRUD matrix --")
    check(rec["crud_matrix"].get("ACCOUNTS") == "RU",
          f"accounts is Read+Updated, got {rec['crud_matrix'].get('ACCOUNTS')}")
    check("crud_matrix" in art, "pipeline-level CRUD matrix aggregated across objects")

    print("\n  -- shape classification --")
    check(rec["shape"]["shape"] == "SINGLE_RECORD_TRANSACTION", "single-row DML classified correctly")
    check("shape_distribution" in art, "shape distribution rolled up")

    print("\n  -- v1 regression guards (must not rot) --")
    code = rec["pseudocode"]
    check(any(l.startswith("IF ") for l in code), "IF header present")
    check(any(l.strip().startswith("ELSIF ") for l in code), "ELSIF present — branches must not flatten")
    check(any(l.strip() == "ELSE" for l in code),
          "ELSE present — guards the per-line comment-strip bug that once swallowed it")
    check(any(l.strip() == "END IF" for l in code), "END IF closes the block")
    if_i = next(i for i, l in enumerate(code) if l.startswith("IF "))
    el_i = next(i for i, l in enumerate(code) if l.strip().startswith("ELSIF "))
    else_i = next(i for i, l in enumerate(code) if l.strip() == "ELSE")
    check(if_i < el_i < else_i, "branch headers in source order")
    check(not any("ACCOUNT_REACTIVATED" in l for l in code[if_i:el_i]),
          "THEN-branch does not leak the ELSIF branch's result")
    check(any(l == "EXCEPTION HANDLING:" for l in code), "exception handlers in their own trailing section")

    print("\n  -- narrative quality --")
    narr = rec["narrative"]
    check("SINGLE_RECORD_TRANSACTION" in narr, "narrative names the shape")
    check("cyclomatic" in narr and "cognitive" in narr, "narrative reports both metrics")
    names = narr.split("including")[-1] if "including" in narr else ""
    check(names.count("NO_DATA_FOUND") <= 1,
          "exception names de-duplicated in the narrative (nested blocks can repeat a handler)")

    check(len(art.get("design_references", [])) >= 5, "design_references cite every metric and technique")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        test_campbell_worked_example(work)
        test_transaction_hazards(work)
        test_real_src(work)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
