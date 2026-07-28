#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/03_data.py (schema_version 2.0).

Three layers:
  1. Advanced fixture (tests/fixtures/sample_ddl/) — exercises every DDL
     construct the agent extracts, especially the ones that are easy to
     silently drop: constraint enforcement state, ON DELETE actions, virtual
     columns, IDENTITY columns, COMMENT ON, views, indexes, synonyms,
     partitioning, global temporary tables, full sequence metadata.
  2. Real production DDL (src/) — guards the numbers that were verified by
     hand, plus the zero-unknown-reference cross-validation invariant.
  3. Error resilience — malformed DDL must not crash the run.

The single most important assertion in this file: a DISABLED CHECK
constraint must never be promotable to a business rule. Oracle tracks
STATUS and VALIDATED independently, and legacy schemas routinely leave
constraints disabled after bulk loads. Reporting one as an active rule
would be a false statement about what the system actually enforces.

Usage:
    python tests/test_data.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DDL_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sample_ddl"
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


def run_pipeline(sql_dir: Path, work_dir: Path) -> tuple[dict, Path]:
    inv_dir = work_dir / "inventory"
    r = subprocess.run(
        [sys.executable, str(INVENTORY_SCRIPT), str(sql_dir),
         "--output", str(inv_dir / "run" / "inventory-artifact.json")],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"01_inventory.py failed:\n{r.stdout}\n{r.stderr}")
    (inv_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "test"}))

    parser_dir = work_dir / "parser"
    r = subprocess.run(
        [sys.executable, str(PARSER_SCRIPT), "--inventory-root", str(inv_dir),
         "--output", str(parser_dir / "run")], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"02_parser.py failed:\n{r.stdout}\n{r.stderr}")
    (parser_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/parser_artifact.json", "updated_at": "test"}))

    data_dir = work_dir / "data_out"
    r = subprocess.run(
        [sys.executable, str(DATA_SCRIPT), "--inventory-root", str(inv_dir),
         "--parser-root", str(parser_dir), "--output", str(data_dir)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"03_data.py failed:\n{r.stdout}\n{r.stderr}")
    print(r.stdout)
    return json.loads((data_dir / "data_artifact.json").read_text(encoding="utf-8")), data_dir


# ---------------------------------------------------------------------------
# Layer 1 — advanced fixture: every construct
# ---------------------------------------------------------------------------

def test_advanced_fixture(work_dir: Path) -> None:
    print("\n=== Advanced DDL fixture: all constructs ===")
    art, data_dir = run_pipeline(DDL_FIXTURE_DIR, work_dir / "adv")
    tables, views, indexes = art["tables"], art["views"], art["indexes"]
    synonyms, sequences = art["synonyms"], art["sequences"]

    check(art["stats"]["parse_errors"] == 0, "advanced fixture parses with zero syntax errors")
    check(art["schema_version"] == "2.0", "artifact reports schema_version 2.0")

    # --- THE correctness assertion: constraint enforcement state ---
    print("\n  -- constraint enforcement (the correctness fix) --")
    contracts = tables["CONTRACTS"]
    by_name = {c["name"]: c for c in contracts["check_constraints"]}

    disabled = by_name.get("CK_CONTRACTS_PREMIUM")
    check(disabled is not None, "DISABLED check constraint is still extracted (not dropped)")
    if disabled:
        check(disabled["enforcement"]["status"] == "DISABLED", "DISABLE parsed as status DISABLED")
        check(disabled["enforcement"]["is_enforced"] is False, "DISABLED constraint reports is_enforced False")
        check(disabled["promotable_to_rule"] is False,
              "DISABLED constraint is NOT promotable to a business rule (the key correctness fix)")

    novalidate = by_name.get("CK_CONTRACTS_STATUS")
    check(novalidate is not None, "ENABLE NOVALIDATE check constraint extracted")
    if novalidate:
        check(novalidate["enforcement"]["status"] == "ENABLED", "ENABLE NOVALIDATE parsed as ENABLED")
        check(novalidate["enforcement"]["validated"] == "NOT_VALIDATED",
              "NOVALIDATE parsed as validated=NOT_VALIDATED")
        check(novalidate["enforcement"]["confidence"] == "enforced_new_data_only",
              "ENABLE NOVALIDATE gets its own distinct confidence level")
        check(novalidate["promotable_to_rule"] is True,
              "ENABLE NOVALIDATE is still promotable (it IS enforced going forward)")

    parties = tables["PARTIES"]
    plain_check = parties["check_constraints"][0]
    check(plain_check["enforcement"]["status"] == "ENABLED" and
          plain_check["enforcement"]["validated"] == "VALIDATED",
          "constraint with no explicit state defaults to Oracle's ENABLE VALIDATE")
    check(plain_check["enforcement"]["explicitly_stated"] is False,
          "default enforcement is flagged as not explicitly stated in the DDL")

    disabled_issues = [i for i in art["issues"] if i["type"] == "constraint_not_enforced"]
    check(len(disabled_issues) == 1, "DISABLED constraint raises exactly one 'not enforced' issue")
    nv_issues = [i for i in art["issues"] if i["type"] == "constraint_not_validated"]
    check(len(nv_issues) == 1, "ENABLE NOVALIDATE raises a 'not validated' info issue")

    # An enum sourced from a DISABLED constraint must be downgraded.
    print("\n  -- enum confidence follows constraint enforcement --")
    premium_col = next(c for c in contracts["columns"] if c["name"] == "CONTRACT_STATUS")
    check(premium_col.get("enum_values") == ["DRAFT", "ACTIVE", "LAPSED"],
          "enum values mined from the NOVALIDATE CHECK constraint")

    # --- ON DELETE ---
    print("\n  -- ON DELETE actions --")
    fk_cascade = contracts["foreign_keys"][0]
    check(fk_cascade["on_delete"] == "CASCADE", "ON DELETE CASCADE captured")
    fk_setnull = tables["CLAIMS"]["foreign_keys"][0]
    check(fk_setnull["on_delete"] == "SET_NULL", "ON DELETE SET NULL captured")
    check(parties["check_constraints"][0].get("on_delete") is None,
          "non-FK constraints carry no on_delete key")

    # --- virtual / IDENTITY columns ---
    print("\n  -- virtual and IDENTITY columns --")
    display = next((c for c in parties["columns"] if c["name"] == "DISPLAY_NAME"), None)
    check(display is not None, "virtual column extracted (was silently dropped before)")
    if display:
        check(display["is_virtual"] is True, "virtual column flagged is_virtual")
        check("first_name" in display["generation_expression"].lower() and
              "last_name" in display["generation_expression"].lower(),
              "virtual column generation formula captured")
    party_id = next(c for c in parties["columns"] if c["name"] == "PARTY_ID")
    check(party_id["is_identity"] is True, "IDENTITY column detected")
    check(party_id["identity_generation"] == "ALWAYS", "IDENTITY generation mode captured")

    # --- comments ---
    print("\n  -- COMMENT ON extraction --")
    check(parties["comment"] == "Legal entities that can hold a contract", "COMMENT ON TABLE captured")
    ptype = next(c for c in parties["columns"] if c["name"] == "PARTY_TYPE")
    check(ptype.get("comment") == "Legal classification driving KYC requirements",
          "COMMENT ON COLUMN captured and attached to the right column")

    # --- views / indexes / synonyms ---
    print("\n  -- views, indexes, synonyms --")
    check("ACTIVE_CONTRACTS" in views, "view extracted")
    av = views.get("ACTIVE_CONTRACTS", {})
    check(av.get("references_tables") == ["CONTRACTS"], "view's backing table resolved")
    check(av.get("filter_predicate") and "ACTIVE" in av["filter_predicate"],
          "view WHERE clause captured as a filter predicate (the rule the view encodes)")

    uix = next((i for i in indexes if i["index"] == "UIX_CLAIMS_CONTRACT_AMT"), None)
    check(uix is not None and uix["unique"] is True, "UNIQUE index extracted and flagged unique")
    if uix:
        check(uix["table"] == "CLAIMS" and uix["columns"] == ["CONTRACT_ID", "CLAIM_AMOUNT"],
              "index table and column list correct")
    nonuix = next((i for i in indexes if i["index"] == "IX_CONTRACTS_STATUS"), None)
    check(nonuix is not None and nonuix["unique"] is False, "non-unique index flagged correctly")

    check("SYN_PARTIES" in synonyms, "synonym extracted")
    check(synonyms.get("SYN_PARTIES", {}).get("target_object") == "PARTIES",
          "synonym target resolved")
    check(synonyms.get("SYN_PARTIES", {}).get("public") is True, "PUBLIC synonym flagged")

    # --- partitioning / GTT ---
    print("\n  -- partitioning and temporary tables --")
    part = contracts["partitioning"]
    check(part is not None, "partitioning metadata captured")
    if part:
        check(part["strategy"] == "RANGE", "RANGE partition strategy detected")
        check(part["key_columns"] == ["START_DATE"], "partition key column captured")
        check(part["partition_count"] == 3, "partition count correct")
    gtt = tables["TMP_CLAIM_BATCH"]
    check(gtt["temporary"] is True, "global temporary table flagged temporary")
    check(gtt["temporary_scope"] == "DELETE_ROWS", "ON COMMIT DELETE ROWS captured")
    check(parties["temporary"] is False, "ordinary table not flagged temporary")

    # --- sequences ---
    print("\n  -- full sequence metadata --")
    seq = sequences["SEQ_ORDER_ID"]
    check(seq["start_with"] == 5000 and seq["increment_by"] == 10, "sequence start/increment")
    check(seq["max_value"] == 9999999 and seq["min_value"] == 1000, "sequence max/min captured")
    check(seq["cycle"] is True and seq["cache"] == 50, "sequence CYCLE and CACHE captured")
    plain = sequences["SEQ_PLAIN_ID"]
    check(plain["increment_by"] == 1 and plain["cycle"] is False,
          "bare sequence gets Oracle defaults, not nulls")

    # --- inferred FK, type-compat aware ---
    print("\n  -- inferred relationships --")
    inferred = art["inferred_relationships"]
    claims_inf = [r for r in inferred if r["from_table"] == "CLAIMS" and r["from_column"] == "PARTY_ID"]
    check(len(claims_inf) == 1, "undeclared claims.party_id detected as an inferred relationship")
    if claims_inf:
        check(claims_inf[0]["relationship_type"] == "inferred",
              "inferred relationship never labelled 'declared'")
        check(claims_inf[0]["basis"] == "name_match+type_compatible",
              "inferred relationship records type compatibility in its basis")
    declared_pairs = {(fk["references_table"], t)
                      for t, tb in tables.items() for fk in tb["foreign_keys"]}
    check(("PARTIES", "CLAIMS") not in declared_pairs,
          "the inferred relationship is genuinely absent from declared FKs")

    # --- %TYPE resolution ---
    print("\n  -- %TYPE resolution --")
    res = {r["reference"]: r for r in art["type_reference_resolutions"]}
    check(res.get("CONTRACTS.CONTRACT_STATUS%TYPE", {}).get("resolved") is True,
          "valid %TYPE reference resolves against the data dictionary")
    check(res.get("CONTRACTS.NO_SUCH_COLUMN%TYPE", {}).get("resolved") is False,
          "invalid %TYPE reference reported unresolved, not silently accepted")

    # --- sequence usage, column catalogue, rule candidates ---
    print("\n  -- derived catalogues --")
    su = art["sequence_usages"]
    check(any(u["sequence"] == "SEQ_ORDER_ID" for u in su),
          "seq_order_id.NEXTVAL usage linked to the statement that uses it")

    cat = {c["column_id"]: c for c in art["column_catalogue"]}
    check("PARTIES.PARTY_TYPE" in cat, "flat column catalogue built")
    check(cat["PARTIES.PARTY_TYPE"]["description"] == "Legal classification driving KYC requirements",
          "column catalogue carries the COMMENT ON description")
    used = cat.get("CONTRACTS.CONTRACT_STATUS", {}).get("used_by_objects", [])
    check(len(used) >= 1, "column catalogue tracks which objects use a column")

    kinds = {c["source_kind"] for c in art["ddl_rule_candidates"]}
    check({"check_constraint", "virtual_column", "unique_constraint",
           "unique_index", "view_filter"} <= kinds,
          f"rule candidates harvested from all five DDL sources, got {sorted(kinds)}")
    disabled_cands = [c for c in art["ddl_rule_candidates"]
                      if c.get("constraint_name") == "CK_CONTRACTS_PREMIUM"]
    check(len(disabled_cands) == 1 and disabled_cands[0]["is_enforced"] is False,
          "DISABLED constraint still appears as a candidate but flagged is_enforced False")

    erd = (data_dir / "erd.mmd").read_text(encoding="utf-8")
    check(erd.startswith("erDiagram"), "ERD generated as valid Mermaid")
    check("[CASCADE]" in erd, "ERD annotates ON DELETE CASCADE on the relationship")


# ---------------------------------------------------------------------------
# Layer 2 — real production DDL
# ---------------------------------------------------------------------------

def test_real_production_ddl(work_dir: Path) -> None:
    print("\n=== Real src/ DDL (regression guard on verified numbers) ===")
    art, _ = run_pipeline(ROOT / "src", work_dir / "real")
    tables = art["tables"]

    check(art["stats"]["parse_errors"] == 0, "zero syntax errors parsing real DDL")
    check(art["stats"]["tables_found"] == 15, f"15 tables, got {art['stats']['tables_found']}")
    check(art["stats"]["sequences_found"] == 3, "3 sequences found")
    check(art["stats"]["declared_foreign_keys"] == 7, "7 declared foreign keys")

    accounts = tables["ACCOUNTS"]
    status_col = next(c for c in accounts["columns"] if c["name"] == "ACCOUNT_STATUS")
    check(status_col.get("enum_source") == "check_constraint", "CHECK-sourced enum on account_status")
    check(status_col.get("confidence") == "enforced",
          "enum from an ENABLED constraint keeps 'enforced' confidence")
    type_col = next(c for c in accounts["columns"] if c["name"] == "ACCOUNT_TYPE")
    check(type_col.get("enum_source") == "comment_only", "comment-only enum still detected")
    check(type_col.get("requires_sme_review") is True, "comment-only enum flagged for SME review")

    balance = next(c for c in accounts["columns"] if c["name"] == "BALANCE")
    check(balance["pyspark_type"] == "DecimalType(18,2)", "NUMBER(18,2) -> DecimalType(18,2)")
    dob = next(c for c in tables["CUSTOMERS"]["columns"] if c["name"] == "DATE_OF_BIRTH")
    check(dob["pyspark_type"] == "TimestampType", "Oracle DATE -> TimestampType (time component)")

    amort = tables["LOAN_AMORTIZATION_SCHEDULE"]
    check(set(amort["primary_key"]) == {"LOAN_ACCOUNT_NUMBER", "INSTALLMENT_NO"},
          "composite primary key extracted")

    check(art["stats"]["unknown_tables"] == 0, "zero unknown-table references (regression guard)")
    check(art["stats"]["unknown_columns"] == 0, "zero unknown-column references (regression guard)")
    check(len(art.get("design_references", [])) >= 6, "design_references cite every major decision")


# ---------------------------------------------------------------------------
# Layer 3 — resilience
# ---------------------------------------------------------------------------

def test_malformed_ddl_does_not_crash(work_dir: Path) -> None:
    print("\n=== Error resilience ===")
    bad = work_dir / "bad_ddl"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "broken.sql").write_text(
        "CREATE TABLE t_broken (col1 NUMBER, CONSTRAINT ck CHECK (col1 >);\n", encoding="utf-8")
    (bad / "fine.sql").write_text(
        "CREATE TABLE t_fine (id NUMBER PRIMARY KEY, name VARCHAR2(50));\n", encoding="utf-8")
    art, _ = run_pipeline(bad, work_dir / "resilience")
    check("T_FINE" in art["tables"], "well-formed table extracted despite a malformed neighbour")
    check(art["stats"]["parse_errors"] > 0, "malformed DDL's syntax error is logged, not swallowed")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        test_advanced_fixture(work)
        test_real_production_ddl(work)
        test_malformed_ddl_does_not_crash(work)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
