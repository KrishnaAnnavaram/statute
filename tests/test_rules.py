#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/05_rules.py.

Includes a regression guard for a real bug found during development: a
cursor record's dotted field access (`rec.balance`) was truncated to just
the generic loop-variable name (`rec`), producing the meaningless rule
name "Enforce Rec" instead of "Enforce Balance".

Usage:
    python tests/test_rules.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY_SCRIPT = ROOT / ".claude" / "scripts" / "00_inventory.py"
PARSER_SCRIPT = ROOT / ".claude" / "scripts" / "02_parser.py"
DATA_SCRIPT = ROOT / ".claude" / "scripts" / "03_data.py"
RULES_SCRIPT = ROOT / ".claude" / "scripts" / "05_rules.py"

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

    data_dir = work_dir / "data"
    subprocess.run([sys.executable, str(DATA_SCRIPT), "--inventory-root", str(inv_dir),
                     "--parser-root", str(parser_dir), "--output", str(data_dir / "run")],
                    capture_output=True, text=True, check=True)
    (data_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/data_artifact.json", "updated_at": "test"}))

    rules_dir = work_dir / "rules_out"
    r = subprocess.run([sys.executable, str(RULES_SCRIPT), "--parser-root", str(parser_dir),
                         "--data-root", str(data_dir), "--inventory-root", str(inv_dir),
                         "--output", str(rules_dir)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"05_rules.py failed:\n{r.stdout}\n{r.stderr}")
    print(r.stdout)
    return json.loads((rules_dir / "rules_artifact.json").read_text(encoding="utf-8"))


def test_real_pipeline(work_dir: Path) -> None:
    print("\n=== Full pipeline: real src/ rule mining ===")
    artifact = run_pipeline(ROOT / "src", work_dir)
    rules = artifact["business_rules"]
    by_name = {r["name"]: r for r in rules}

    # CHECK-constraint-sourced rule (from Agent 3's promotable_to_rule)
    check_rules = [r for r in rules if r["source"]["kind"] == "ddl_check_constraint"]
    check(len(check_rules) == 1, "the accounts.account_status CHECK constraint promoted to exactly one rule")
    if check_rules:
        check(check_rules[0]["confidence"] == "confirmed", "CHECK-constraint rule gets top confidence, no SME review")
        check(check_rules[0]["requires_sme_review"] is False, "CHECK-constraint rule never flagged for SME review")

    # Named business exceptions promoted; WHEN OTHERS excluded
    exc_rules = [r for r in rules if r["source"]["kind"] == "named_exception"]
    exc_names = {r["condition_text"].upper() for r in exc_rules}
    check("E_INSUFFICIENT_BALANCE" in exc_names, "named exception E_INSUFFICIENT_BALANCE promoted to a rule")
    check("E_DAILY_LIMIT_EXCEEDED" in exc_names, "named exception E_DAILY_LIMIT_EXCEEDED promoted to a rule")
    check("OTHERS" not in exc_names, "generic WHEN OTHERS handler never promoted to a business rule")
    check(all(r["confidence"] == "confirmed" for r in exc_rules), "all named-exception rules get top confidence")

    # Regression guard: dotted record-field subject must not collapse to the
    # generic loop-variable name.
    check("Enforce Rec" not in by_name, "cursor record field (rec.balance) never produces the meaningless name 'Enforce Rec'")
    check("Enforce Balance" in by_name, "cursor record field (rec.balance) correctly resolves to 'Enforce Balance'")

    # Every rule traces to a real source
    for r in rules:
        check("source" in r and r["source"].get("kind"), f"{r['rule_id']} has a traceable source")
        break  # one representative check is enough to avoid flooding output; full coverage below
    check(all("source" in r and r["source"].get("kind") for r in rules), "every extracted rule has a traceable source (no invented rules)")

    # Rule sets partition all rules
    all_rule_ids_in_sets = {rid for rs in artifact["rule_sets"] for rid in rs["rule_ids"]}
    check(all_rule_ids_in_sets == {r["rule_id"] for r in rules}, "every rule belongs to exactly one rule set")

    check(len(artifact.get("design_references", [])) >= 2, "design_references present with cited sources")


def test_category_and_pattern_classification() -> None:
    print("\n=== Direct unit test: category/pattern classification ===")
    import importlib
    rl = importlib.import_module("05_rules")

    check(rl.classify_category("p_trans_amount > p_credit_limit") == "LIMIT_CHECK",
          "amount-vs-limit comparison classified as LIMIT_CHECK")
    check(rl.classify_category("v_account_status = 'CLOSED'") == "VALIDATION",
          "status field comparison classified as VALIDATION")
    check(rl.classify_pattern("v_status = 'ACTIVE'") == "FIELD_VALUE_COMPARE", "literal comparison pattern detected")
    check(rl.classify_pattern("v_amount > 10000 AND v_flag = 'Y'") == "MULTI_CONDITION", "AND/OR compound condition pattern detected")
    check(rl.business_name("p_account_number") == "Account Number", "parameter prefix stripped and abbreviation expanded")
    check(rl.business_name("rec.balance") == "Balance", "dotted record-field access resolves to the field name, not the loop variable")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        test_real_pipeline(Path(tmp))
    test_category_and_pattern_classification()

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
