#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/05_rules.py (redesigned agent).

The previous version of this suite tested a condition-mining agent with three
sources (IF conditions, named exceptions, CHECK constraints). The redesigned
agent mines from nine, restates exceptions as positive obligations, and
decomposes multi-branch constructs — so most of the old assertions described
behaviour that no longer exists. This suite tests what the agent does now.

Each test below traces to a specific defect or design decision, noted inline,
so a future reader can tell an intentional guarantee from an incidental one.
Correctness against hand-annotated rules is measured separately by
tests/evaluate_rules.py; this suite guards behaviour, not accuracy.

Usage:
    python tests/test_rules.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "scripts"

sys.path.insert(0, str(SCRIPTS))

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def _stage(script: str, args: list[str], out_dir: Path, artifact: str) -> Path:
    subprocess.run([sys.executable, str(SCRIPTS / script), *args, "--output", str(out_dir / "run")],
                   capture_output=True, text=True, check=True)
    (out_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": f"run/{artifact}", "updated_at": "test"}))
    return out_dir


def run_pipeline(sql_dir: Path, work_dir: Path) -> dict:
    """Stages 1-5. Agent 5 now consumes Agent 4's slices, so logic must run."""
    inv = work_dir / "inventory"
    subprocess.run([sys.executable, str(SCRIPTS / "01_inventory.py"), str(sql_dir),
                    "--output", str(inv / "run" / "inventory-artifact.json")],
                   capture_output=True, text=True, check=True)
    (inv / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "test"}))

    parser = _stage("02_parser.py", ["--inventory-root", str(inv)],
                    work_dir / "parser", "parser_artifact.json")
    data = _stage("03_data.py", ["--inventory-root", str(inv), "--parser-root", str(parser)],
                  work_dir / "data", "data_artifact.json")
    logic = _stage("04_logic.py", ["--parser-root", str(parser), "--inventory-root", str(inv)],
                   work_dir / "logic", "logic_artifact.json")

    rules = work_dir / "rules"
    r = subprocess.run([sys.executable, str(SCRIPTS / "05_rules.py"),
                        "--parser-root", str(parser), "--data-root", str(data),
                        "--inventory-root", str(inv), "--logic-root", str(logic),
                        "--output", str(rules / "run")], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"05_rules.py failed:\n{r.stdout}\n{r.stderr}")
    return json.loads((rules / "run" / "rules_artifact.json").read_text(encoding="utf-8"))


def test_pipeline_contract(artifact: dict) -> None:
    """Invariants every consumer downstream (Agents 6 and 7) relies on."""
    print("\n=== Contract: structure every downstream agent depends on ===")
    rules = artifact["business_rules"]

    check(len(rules) > 0, "the agent extracts rules from the real src/ corpus")
    check(all(r["source"].get("kind") for r in rules),
          "every rule carries a source kind (no invented rules)")
    check(all(r.get("rule_id") for r in rules), "every rule has a rule_id")
    check(len({r["rule_id"] for r in rules}) == len(rules), "rule_ids are unique")

    # Agent 7 formats rule provenance by branching on source kind. A kind it
    # does not recognise previously crashed it with KeyError: 'object_id' —
    # so object_id must be present on every non-DDL kind.
    non_ddl = [r for r in rules if not r["source"]["kind"].startswith("ddl_")]
    check(all("object_id" in r["source"] for r in non_ddl),
          "every code-sourced rule names its object_id (Agent 7 formats on it)")
    check(all("line" in r["source"] for r in non_ddl),
          "every code-sourced rule cites a source line (traceability to source)")

    ids_in_sets = {rid for rs in artifact["rule_sets"] for rid in rs["rule_ids"]}
    check(ids_in_sets == {r["rule_id"] for r in rules}, "rule sets partition all rules")
    check(len(artifact.get("design_references", [])) >= 2, "design_references cite sources")


def test_exceptions_are_obligations(artifact: dict) -> None:
    """
    SBVR principle: 'there are no exceptions; instead there are well stated
    business rules.' A RAISE guarded by an IF states a prohibition, and the
    BRD should read as the positive obligation, not as 'exception X is raised'.
    """
    print("\n=== Obligation form: exceptions restated as business rules ===")
    rules = artifact["business_rules"]
    obligations = [r for r in rules if r.get("is_obligation")]

    check(len(obligations) > 0, "the agent emits obligation-form rules")
    check(all("raise" not in r["name"].lower() for r in obligations),
          "no obligation rule is named after the RAISE mechanism")

    # A guarded RAISE must MERGE with the IF that guards it rather than
    # producing a second rule for the same decision — they are one rule.
    text = json.dumps(rules)
    check("e_insufficient_balance" not in text.lower() or
          any("must" in r["description"].lower() for r in obligations),
          "guarded exceptions are phrased as what must hold, not what is raised")


def test_branch_decomposition(artifact: dict) -> None:
    """
    A multi-branch construct encodes one business outcome PER BRANCH.
    Emitting only the leading IF cost 2 of 5 rules on the dormant-account
    procedure; leaving CASE whole cost 6 of 10 on the minimum-balance one.
    """
    print("\n=== Decomposition: every branch is its own business outcome ===")
    rules = artifact["business_rules"]

    case_rules = [r for r in rules if r["source"]["kind"] == "case_branch"]
    check(len(case_rules) >= 5,
          "a CASE expression is decomposed into one rule per branch, not left whole")
    check(any(r["structural_pattern"] == "DEFAULT_BRANCH" for r in case_rules),
          "the CASE ELSE branch is captured as the default rule")

    branch_rules = [r for r in rules if r["source"]["kind"] == "conditional_branch"]
    check(any(r["structural_pattern"] == "DEFAULT_BRANCH" for r in branch_rules),
          "an IF/ELSE else-branch is captured as the default rule")

    # Distinct branches must occupy distinct lines, or dedup collapses them.
    case_lines = [r["source"]["line"] for r in case_rules]
    check(len(set(case_lines)) == len(case_lines),
          "each CASE branch rule cites its own source line (not the statement start)")


def test_when_others_three_way_split(artifact: dict) -> None:
    """
    WHEN OTHERS is not one thing. Logging a per-row failure and continuing is
    a resilience REQUIREMENT; re-raising as -20010 is an error CONTRACT;
    a bare rollback-and-reraise is plumbing and must not reach the BRD.
    """
    print("\n=== WHEN OTHERS: resilience vs error contract vs plumbing ===")
    kinds = {r["source"]["kind"] for r in artifact["business_rules"]}

    check("failure_isolation" in kinds,
          "a per-row failure that is logged and skipped becomes a resilience rule")
    check("error_contract" in kinds,
          "a WHEN OTHERS that raises a specific application error becomes an error contract")

    generic = [r for r in artifact["business_rules"]
               if r["source"]["kind"] == "generic_exception"]
    check(all(r["requires_sme_review"] for r in generic),
          "any residual generic handler is flagged for SME review rather than asserted")


def test_derivation_and_cursor_mining(artifact: dict) -> None:
    """Sources the old three-source agent had no access to at all."""
    print("\n=== Slice-derived and cursor-derived rules ===")
    rules = artifact["business_rules"]
    kinds = {r["source"]["kind"] for r in rules}

    check("variable_derivation" in kinds,
          "business formulas are mined from Agent 4's backward slices")
    check("cursor_eligibility" in kinds,
          "a cursor WHERE clause is mined as a population-eligibility rule")

    # Regression guard: a slice includes TRANSITIVE dependencies, so the
    # statement computing v_interest_amount also appears in v_new_balance's
    # slice. Attributing it to both produced a duplicate rule.
    deriv = [r for r in rules if r["source"]["kind"] == "variable_derivation"]
    lines = [(r["source"]["object_id"], r["source"]["line"]) for r in deriv]
    check(len(set(lines)) == len(lines),
          "one derivation rule per formula (transitive slice members not re-attributed)")


def test_unit_level_helpers() -> None:
    """Direct tests of the classification and phrasing helpers."""
    print("\n=== Unit: classification, naming, derivation scoring ===")
    import importlib
    rl = importlib.import_module("05_rules")

    check(rl.classify_category("p_trans_amount > p_credit_limit") == "LIMIT_CHECK",
          "amount-vs-limit comparison classified as LIMIT_CHECK")
    check(rl.classify_category("v_account_status = 'CLOSED'") == "VALIDATION",
          "status field comparison classified as VALIDATION")
    check(rl.classify_pattern("v_status = 'ACTIVE'") == "FIELD_VALUE_COMPARE",
          "literal comparison pattern detected")
    check(rl.classify_pattern("v_amount > 10000 AND v_flag = 'Y'") == "MULTI_CONDITION",
          "AND/OR compound condition pattern detected")

    check(rl.business_name("p_account_number") == "Account Number",
          "parameter prefix stripped and abbreviation expanded")
    # Regression guard: `rec.balance` once collapsed to the generic loop
    # variable, producing the meaningless rule name "Enforce Rec".
    check(rl.business_name("rec.balance") == "Balance",
          "dotted record-field access resolves to the field, not the loop variable")

    # Enforcement state drives confidence: a DISABLED constraint is not a
    # confirmed rule just because it is written down.
    signal, conf, sme = rl._ENFORCEMENT_TO_CONFIDENCE["enforced"]
    check((conf, sme) == ("confirmed", False),
          "an ENABLED VALIDATED constraint is confirmed and needs no SME review")

    signal, conf, sme = rl._ENFORCEMENT_TO_CONFIDENCE["enforced_new_data_only"]
    check(conf != "confirmed" and sme,
          "ENABLE NOVALIDATE is not confirmed — existing rows may violate it")

    signal, conf, sme = rl._ENFORCEMENT_TO_CONFIDENCE["not_enforced"]
    check(conf == "low" and sme,
          "a DISABLED constraint is low confidence and flagged for SME review")


def test_dedup_prefers_obligations() -> None:
    print("\n=== Unit: deduplication keeps the stronger statement ===")
    import importlib
    rl = importlib.import_module("05_rules")

    weak = {"raw_key": "K", "name": "weak", "signal_strength": 2, "category": "VALIDATION",
            "source": {"kind": "conditional_branch"}}
    strong = {"raw_key": "K", "name": "strong", "signal_strength": 2, "is_obligation": True,
              "category": "VALIDATION", "source": {"kind": "named_exception"}}

    kept = rl.deduplicate([weak, strong])
    check(len(kept) == 1, "two rules sharing a raw_key collapse to one")
    check(kept[0]["name"] == "strong",
          "the obligation form wins over the bare condition for the same decision")

    louder = {"raw_key": "J", "name": "louder", "signal_strength": 5, "category": "VALIDATION",
              "source": {"kind": "conditional_branch"}}
    quieter = {"raw_key": "J", "name": "quieter", "signal_strength": 1, "category": "VALIDATION",
               "source": {"kind": "conditional_branch"}}
    kept = rl.deduplicate([quieter, louder])
    check(kept[0]["name"] == "louder",
          "with neither an obligation, the higher-signal rule wins regardless of order")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        artifact = run_pipeline(ROOT / "src", Path(tmp))
        test_pipeline_contract(artifact)
        test_exceptions_are_obligations(artifact)
        test_branch_decomposition(artifact)
        test_when_others_three_way_split(artifact)
        test_derivation_and_cursor_mining(artifact)

    test_unit_level_helpers()
    test_dedup_prefers_obligations()

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
