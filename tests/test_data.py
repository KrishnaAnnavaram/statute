#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/03_data.py.

Covers, using real fixtures rather than synthetic examples wherever
possible:
  1. End-to-end pipeline run (inventory -> parser -> data) against the real
     production-shaped DDL in src/00_ddl_create_schema.sql: table/column/
     PK/FK/CHECK extraction, comment-only enum mining, CHECK-constraint
     enum mining + rule promotion, implicit FK detection (with confidence
     tagging, never merged with declared FKs), cross-validation against
     Agent 2's output (must be zero unknown tables/columns on this real,
     already-debugged codebase — a regression guard), Oracle->PySpark type
     mapping, and ERD generation.
  2. Direct unit tests against tests/fixtures/sample_plsql/01_schema.sql +
     02_account_mgmt.sql for %TYPE resolution (a case the production DDL
     doesn't exercise) and confirms non-table DDL (view/index/synonym/
     grant) is safely ignored, not mis-parsed as a table.
  3. Error resilience — malformed DDL must not crash the run.

Usage:
    python tests/test_data.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sample_plsql"
INVENTORY_SCRIPT = ROOT / ".claude" / "scripts" / "01_inventory.py"
PARSER_SCRIPT = ROOT / ".claude" / "scripts" / "02_parser.py"
DATA_SCRIPT = ROOT / ".claude" / "scripts" / "03_data.py"

sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def run_full_pipeline(sql_dir: Path, work_dir: Path) -> dict:
    inv_dir = work_dir / "inventory"
    r = subprocess.run(
        [sys.executable, str(INVENTORY_SCRIPT), str(sql_dir), "--output", str(inv_dir / "run" / "inventory-artifact.json")],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"01_inventory.py failed:\n{r.stdout}\n{r.stderr}")
    (inv_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "test"}))

    parser_dir = work_dir / "parser"
    r = subprocess.run(
        [sys.executable, str(PARSER_SCRIPT), "--inventory-root", str(inv_dir), "--output", str(parser_dir / "run")],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"02_parser.py failed:\n{r.stdout}\n{r.stderr}")
    (parser_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/parser_artifact.json", "updated_at": "test"}))

    data_dir = work_dir / "data_out"
    r = subprocess.run(
        [sys.executable, str(DATA_SCRIPT), "--inventory-root", str(inv_dir), "--parser-root", str(parser_dir),
         "--output", str(data_dir)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"03_data.py failed:\n{r.stdout}\n{r.stderr}")
    print(r.stdout)
    return json.loads((data_dir / "data_artifact.json").read_text(encoding="utf-8"))


def test_real_production_ddl(work_dir: Path) -> None:
    print("\n=== Full pipeline: real src/ DDL (15 tables, 8 relationships, 1 CHECK) ===")
    artifact = run_full_pipeline(ROOT / "src", work_dir / "real")
    tables = artifact["tables"]

    check(artifact["stats"]["parse_errors"] == 0, "zero ANTLR syntax errors parsing real DDL")
    check(artifact["stats"]["tables_found"] == 15, f"15 tables found, got {artifact['stats']['tables_found']}")
    check(artifact["stats"]["sequences_found"] == 3, "3 sequences found")
    check(artifact["stats"]["declared_foreign_keys"] == 7, "7 declared foreign keys found")

    # CHECK constraint -> candidate business rule (accounts.account_status)
    accounts = tables["ACCOUNTS"]
    check(len(accounts["check_constraints"]) == 1, "accounts has exactly one CHECK constraint")
    status_col = next(c for c in accounts["columns"] if c["name"] == "ACCOUNT_STATUS")
    check(status_col.get("enum_source") == "check_constraint", "account_status enum sourced from CHECK constraint")
    check(status_col.get("confidence") == "enforced", "CHECK-sourced enum marked confidence: enforced")
    check(set(status_col.get("enum_values", [])) == {"ACTIVE", "DORMANT", "CLOSED"},
          "account_status enum values extracted correctly from CHECK expression")
    check(accounts["check_constraints"][0]["promotable_to_rule"] is True,
          "CHECK constraint flagged promotable_to_rule for the Rules Agent")

    # Comment-only enum (account_type has no CHECK, only an inline comment)
    type_col = next(c for c in accounts["columns"] if c["name"] == "ACCOUNT_TYPE")
    check(type_col.get("enum_source") == "comment_only", "account_type enum sourced from comment, not a constraint")
    check(type_col.get("confidence") == "documented_only", "comment-only enum marked confidence: documented_only")
    check(type_col.get("requires_sme_review") is True, "comment-only enum flagged for SME review")
    check("SAVINGS_REGULAR" in type_col.get("enum_values", []) and "OVERDRAFT" in type_col.get("enum_values", []),
          "account_type enum values mined correctly across a multi-line trailing comment")

    # Declared FK correctness
    fk_names = {fk["name"] for fk in accounts["foreign_keys"]}
    check("FK_ACCOUNTS_CUSTOMER" in fk_names, "accounts.customer_id declared FK extracted with correct name")
    ck_names = {fk["references_table"] for fk in accounts["foreign_keys"]}
    check("CUSTOMERS" in ck_names, "declared FK correctly points at CUSTOMERS table")

    # Implicit FK: fraud_score_results.account_number -> accounts.account_number (no declared FK exists)
    inferred = artifact["inferred_relationships"]
    fraud_inferred = [r for r in inferred if r["from_table"] == "FRAUD_SCORE_RESULTS"]
    check(len(fraud_inferred) == 1, "fraud_score_results.account_number detected as an inferred relationship")
    if fraud_inferred:
        check(fraud_inferred[0]["to_table"] == "ACCOUNTS", "inferred relationship correctly targets ACCOUNTS")
        check(fraud_inferred[0]["relationship_type"] == "inferred", "inferred relationship tagged 'inferred', never 'declared'")
    declared_pairs = {(fk["references_table"], t) for t, tbl in tables.items() for fk in tbl["foreign_keys"]}
    check(("ACCOUNTS", "FRAUD_SCORE_RESULTS") not in declared_pairs,
          "inferred relationship is genuinely absent from declared FKs (not a duplicate)")

    # Composite primary key (loan_amortization_schedule)
    amort = tables["LOAN_AMORTIZATION_SCHEDULE"]
    check(set(amort["primary_key"]) == {"LOAN_ACCOUNT_NUMBER", "INSTALLMENT_NO"},
          "composite primary key extracted correctly")

    # Default value kind classification (literal vs function_call)
    default_col = next(c for c in tables["CUSTOMERS"]["columns"] if c["name"] == "CUSTOMER_SINCE_DATE")
    check(default_col["default"]["kind"] == "function_call", "SYSDATE default classified as function_call")
    kyc_col = next(c for c in tables["CUSTOMERS"]["columns"] if c["name"] == "KYC_STATUS")
    check(kyc_col["default"]["kind"] == "literal", "'VERIFIED' default classified as literal")

    # Oracle -> PySpark type mapping
    check(status_col["pyspark_type"] == "StringType", "VARCHAR2 maps to PySpark StringType")
    balance_col = next(c for c in accounts["columns"] if c["name"] == "BALANCE")
    check(balance_col["pyspark_type"] == "DecimalType(18,2)", "NUMBER(18,2) maps to PySpark DecimalType(18,2)")
    dob_col = next(c for c in tables["CUSTOMERS"]["columns"] if c["name"] == "DATE_OF_BIRTH")
    check(dob_col["pyspark_type"] == "TimestampType" and "time component" in dob_col.get("note", ""),
          "Oracle DATE maps to TimestampType with the time-component gotcha noted, not narrowed to DateType")

    # Cross-validation against Agent 2's output — regression guard: this
    # codebase is already debugged, so this must stay at zero.
    check(artifact["stats"]["unknown_tables"] == 0, "zero unknown-table references cross-validating against parser output")
    check(artifact["stats"]["unknown_columns"] == 0, "zero unknown-column references cross-validating against parser output")

    # ERD
    erd_path = Path(list(Path(work_dir / "real" / "data_out").glob("erd.mmd"))[0])
    erd_text = erd_path.read_text(encoding="utf-8")
    check(erd_text.startswith("erDiagram"), "erd.mmd starts with a valid Mermaid erDiagram declaration")
    check("ACCOUNTS" in erd_text and "CUSTOMERS" in erd_text, "ERD includes real table names")

    # design_references present and non-empty — no unattributed rules
    check(len(artifact.get("design_references", [])) >= 3, "design_references present with cited sources")


def test_type_resolution_and_non_table_ddl_skipped() -> None:
    print("\n=== Direct unit test: %TYPE resolution + non-table DDL safely ignored ===")
    import importlib
    d = importlib.import_module("03_data")

    tree, errors = d.parse_source(str(FIXTURE_DIR / "01_schema.sql"))
    check(errors == [], "01_schema.sql (table+sequence+index+view+synonym+grant) parses with zero syntax errors")

    table_ctxs = d.find_all(tree, "Create_tableContext", [])
    check(len(table_ctxs) == 1, "exactly one CREATE TABLE found — view/index/synonym/grant correctly not mistaken for tables")

    table = d.extract_table(table_ctxs[0])
    check(table["table"] == "ACCOUNTS", "table name extracted correctly despite schema-qualified 'app.accounts'")
    check(table["primary_key"] == ["ACCOUNT_ID"], "inline PRIMARY KEY on account_id extracted correctly")
    balance_col = next(c for c in table["columns"] if c["name"] == "BALANCE")
    check(balance_col["pyspark_type"] == "DecimalType(15,2)", "NUMBER(15,2) in fixture maps correctly")

    seq_ctxs = d.find_all(tree, "Create_sequenceContext", [])
    check(len(seq_ctxs) == 1, "sequence found despite view/index/synonym/grant also present in the same file")

    # %TYPE resolution against the package fixture's declaration:
    # l_balance app.accounts.balance%TYPE  (in 02_account_mgmt.sql)
    tables = {table["table"]: table}
    m = d._TYPE_REF_RE.search("app.accounts.balance%TYPE")
    check(m is not None, "%TYPE regex matches a schema-qualified owner.table.column%TYPE reference")
    if m:
        tbl, col = m.group(1).upper(), m.group(2).upper()
        found = tbl in tables and any(c["name"] == col for c in tables[tbl]["columns"])
        check(found, "app.accounts.balance%TYPE resolves correctly against the extracted table model")


def test_malformed_ddl_does_not_crash(work_dir: Path) -> None:
    print("\n=== Error resilience: malformed DDL must not crash the run ===")
    bad_dir = work_dir / "bad_ddl"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "broken.sql").write_text(
        "CREATE TABLE t_broken (col1 NUMBER, CONSTRAINT ck CHECK (col1 >);\n",
        encoding="utf-8",
    )
    (bad_dir / "fine.sql").write_text(
        "CREATE TABLE t_fine (id NUMBER PRIMARY KEY, name VARCHAR2(50));\n",
        encoding="utf-8",
    )
    artifact = run_full_pipeline(bad_dir, work_dir / "resilience")
    check("T_FINE" in artifact["tables"], "well-formed sibling table still extracted despite malformed neighbor")
    check(artifact["stats"]["parse_errors"] > 0, "malformed DDL's syntax error is logged, not silently swallowed")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        test_real_production_ddl(work_dir)
        test_type_resolution_and_non_table_ddl_skipped()
        test_malformed_ddl_does_not_crash(work_dir)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
