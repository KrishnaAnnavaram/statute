#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/02_parser.py.

Unlike test_inventory.py this isn't a single golden-file diff — the parser's
output is too structurally rich (nested statement trees, call resolution)
for one byte-equality check to be a useful signal on failure. Instead this
runs a battery of targeted assertions against real fixture data, covering:

  1. End-to-end CLI run against the package fixture (packages, members,
     cross-member call resolution, dynamic SQL flagging, unresolved external
     call detection).
  2. Direct unit tests of the statement visitor against the real dormant-
     account procedure (IF/ELSIF/ELSE parent-child nesting, exception
     handler parenting, CFG edge shape).
  3. Error resilience — a deliberately malformed object must not crash the
     whole run; it should be isolated with parse_status: "failed" while
     everything else still parses.

Usage:
    python tests/test_parser.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sample_plsql"
INVENTORY_SCRIPT = ROOT / ".claude" / "scripts" / "00_inventory.py"
PARSER_SCRIPT = ROOT / ".claude" / "scripts" / "02_parser.py"

sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def run_pipeline(sql_dir: Path, work_dir: Path) -> dict:
    inv_dir = work_dir / "inventory"
    result = subprocess.run(
        [sys.executable, str(INVENTORY_SCRIPT), str(sql_dir), "--output", str(inv_dir / "run" / "inventory-artifact.json")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"00_inventory.py failed:\n{result.stdout}\n{result.stderr}")
    # 02_parser.py resolves via latest.json — build one manually since
    # --output on the inventory script bypasses run versioning.
    latest = {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "test"}
    (inv_dir / "latest.json").write_text(json.dumps(latest))

    parser_out = work_dir / "parser_output"
    result = subprocess.run(
        [sys.executable, str(PARSER_SCRIPT), "--inventory-root", str(inv_dir), "--output", str(parser_out)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"02_parser.py failed:\n{result.stdout}\n{result.stderr}")
    print(result.stdout)

    manifest = json.loads((parser_out / "parser_artifact.json").read_text(encoding="utf-8"))
    raw_structure = {}
    for name, rel in manifest["object_index"].items():
        raw_structure[name] = json.loads((parser_out / rel).read_text(encoding="utf-8"))
    return {"manifest": manifest, "objects": raw_structure}


def test_package_fixture(work_dir: Path) -> None:
    print("\n=== Package fixture: cross-member calls, dynamic SQL, unresolved refs ===")
    result = run_pipeline(FIXTURE_DIR, work_dir / "pkg")
    manifest, objects = result["manifest"], result["objects"]

    check(manifest["stats"]["parse_errors"] == 0, "zero ANTLR syntax errors across all fixture files")
    check(manifest["stats"]["package_members"] == 3, "package member count == 3 (credit/debit/get_balance)")

    check("PKGB-APP.LEGACY_CALC" in objects, "wrapped package body still discovered (header-only)")
    wrapped = objects.get("PKGB-APP.LEGACY_CALC", {})
    check(wrapped.get("parse_status") == "skipped_wrapped", "wrapped object marked skipped_wrapped, not sent through ANTLR")
    check(wrapped.get("statements") == {}, "wrapped object has no extracted statements")
    check(any(i.get("type") == "wrapped_object_skipped" for i in manifest["issues"]),
          "wrapped_object_skipped issue logged for legacy_calc")

    check("PKGS-APP.ACCOUNT_MGMT" in objects, "package spec discovered")
    check("PKGB-APP.ACCOUNT_MGMT" in objects, "package body discovered")
    check("PKGB-APP.ACCOUNT_MGMT::CREDIT_ACCOUNT" in objects, "credit_account member discovered with :: id")
    check("TRG-APP.ACCOUNTS_BIU" in objects, "trigger discovered")

    credit = objects["PKGB-APP.ACCOUNT_MGMT::CREDIT_ACCOUNT"]
    update_stmts = [s for s in credit["statements"].values() if s["statement_type"] == "UPDATE"]
    check(len(update_stmts) == 1, "credit_account has exactly one UPDATE statement")
    if update_stmts:
        check(update_stmts[0].get("writes") == ["balance"], "UPDATE writes == ['balance'] (SET target only, not WHERE columns)")
        check(update_stmts[0].get("tables") == ["accounts"], "UPDATE table == accounts")

    debit = objects["PKGB-APP.ACCOUNT_MGMT::DEBIT_ACCOUNT"]
    call_stmts = [s for s in debit["statements"].values() if s["statement_type"] == "CALL"]
    check(len(call_stmts) == 1 and call_stmts[0]["call_target"] == "CREDIT_ACCOUNT",
          "debit_account calls credit_account")
    check(call_stmts[0].get("resolved") is True, "sibling package-member call resolves without qualification")
    check(call_stmts[0].get("call_target_object_id") == "PKGB-APP.ACCOUNT_MGMT::CREDIT_ACCOUNT",
          "resolved call points at the correct member object_id")

    get_balance = objects["PKGB-APP.ACCOUNT_MGMT::GET_BALANCE"]
    dyn = [s for s in get_balance["statements"].values() if s["statement_type"] == "DYNAMIC_SQL"]
    check(len(dyn) == 1 and dyn[0].get("requires_manual_review") is True,
          "EXECUTE IMMEDIATE flagged as DYNAMIC_SQL requiring manual review")

    unresolved_issues = [i for i in manifest["issues"] if i.get("type") == "unresolved_reference"]
    check(any("AUDIT_LOG_PKG" in i["message"] for i in unresolved_issues),
          "AUDIT_LOG_PKG.RECORD_TXN (not a local package) logged as unresolved_reference")


def test_dormant_account_procedure_directly() -> None:
    print("\n=== Direct unit test: dormant-account procedure (nesting, CFG) ===")
    import importlib
    p = importlib.import_module("02_parser")

    src = ROOT / "src" / "02_simple_update_dormant_account_status.sql"
    tree, errors, _ = p.parse_source(str(src))
    check(errors == [], "dormant-account procedure parses with zero syntax errors")

    objs = p.discover_objects(tree, "TESTFILE")
    check(len(objs) == 1 and objs[0]["type"] == "PROCEDURE", "exactly one standalone PROCEDURE discovered")

    result = p.parse_object(objs[0], "TESTFILE")
    stmts = result["statements"]
    check(len(stmts) == 15, f"expected 15 statements, got {len(stmts)}")

    by_short = {sid.split("__")[-1]: s for sid, s in stmts.items()}
    check(by_short["STMT_0003"]["statement_type"] == "IF", "STMT_0003 is the IF/ELSIF/ELSE statement")
    then_child = by_short["STMT_0004"]
    check(then_child["parent_id"] == list(stmts.keys())[2], "THEN-branch UPDATE's parent_id points at the IF statement")
    check(then_child["scope_path"] == ["IF#3.THEN"], "THEN-branch scope_path breadcrumb correct")
    check(by_short["STMT_0006"]["scope_path"] == ["IF#3.ELSIF1"], "ELSIF-branch scope_path breadcrumb correct")
    check(by_short["STMT_0008"]["scope_path"] == ["IF#3.ELSE"], "ELSE-branch scope_path breadcrumb correct")

    handlers = [s for s in stmts.values() if s["statement_type"] == "EXCEPTION_HANDLER"]
    check(len(handlers) == 2, "two exception handlers found (NO_DATA_FOUND, OTHERS)")
    check({tuple(h["handler_for"]) for h in handlers} == {("NO_DATA_FOUND",), ("OTHERS",)},
          "handler_for correctly captures NO_DATA_FOUND and OTHERS")

    cfg = result["control_flow_graph"]
    exc_edges = [e for e in cfg["edges"] if e["type"] == "EXCEPTION_EDGE"]
    check(len(exc_edges) == 2, "CFG has exactly 2 EXCEPTION_EDGE entries, one per handler")


def test_malformed_object_does_not_crash_run(work_dir: Path) -> None:
    print("\n=== Error resilience: malformed object must not crash the whole run ===")
    bad_dir = work_dir / "bad_src"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "broken.sql").write_text(
        "CREATE OR REPLACE PROCEDURE p_broken IS BEGIN IF THEN END IF END p_broken;\n/\n",
        encoding="utf-8",
    )
    (bad_dir / "fine.sql").write_text(
        "CREATE OR REPLACE PROCEDURE p_fine IS BEGIN NULL; END p_fine;\n/\n",
        encoding="utf-8",
    )
    result = run_pipeline(bad_dir, work_dir / "resilience")
    manifest = result["manifest"]
    check(manifest["stats"]["objects_parsed"] == 2, "both objects attempted despite one being malformed")
    check("PROC-.P_FINE" in result["objects"], "the well-formed sibling object still parsed successfully")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        test_package_fixture(work_dir)
        test_dormant_account_procedure_directly()
        test_malformed_object_does_not_crash_run(work_dir)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
