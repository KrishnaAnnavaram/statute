#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/07_synthesis.py and lib_business_language.

The predecessor suite checked that chapter headings existed and that no invented
rule ids appeared. It could not have caught the defects this redesign fixed,
because it never inspected the prose: the document was full of raw identifiers
("PROC-.SP_TRANSFER_FUNDS", "v_from_balance < p_amount") that no business reader
can parse, the word "scope" appeared nowhere, and a HIGH severity transaction
hazard was computed upstream and silently discarded.

These tests assert the properties that make the document usable by its four
audiences: readable for a sponsor, reviewable for an analyst, complete for a
build team, and parseable for a machine.

Usage:
    python tests/test_synthesis.py
"""

import importlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "scripts"
sys.path.insert(0, str(SCRIPTS))

bl = importlib.import_module("lib_business_language")
syn = importlib.import_module("07_synthesis")

failures: list = []


def check(condition: bool, label: str) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


def _stage(script: str, args: list, out_dir: Path, artifact: str) -> Path:
    subprocess.run([sys.executable, str(SCRIPTS / script), *args, "--output", str(out_dir / "run")],
                   capture_output=True, text=True, check=True)
    (out_dir / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": f"run/{artifact}", "updated_at": "test"}))
    return out_dir


def run_pipeline(work: Path, annotations: Path = None) -> tuple:
    inv = work / "inventory"
    subprocess.run([sys.executable, str(SCRIPTS / "01_inventory.py"), str(ROOT / "src"),
                    "--output", str(inv / "run" / "inventory-artifact.json")],
                   capture_output=True, text=True, check=True)
    (inv / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "test"}))

    parser = _stage("02_parser.py", ["--inventory-root", str(inv)], work / "parser",
                    "parser_artifact.json")
    data = _stage("03_data.py", ["--inventory-root", str(inv), "--parser-root", str(parser)],
                  work / "data", "data_artifact.json")
    logic = _stage("04_logic.py", ["--parser-root", str(parser), "--inventory-root", str(inv)],
                   work / "logic", "logic_artifact.json")
    rules = _stage("05_rules.py", ["--parser-root", str(parser), "--data-root", str(data),
                                   "--inventory-root", str(inv), "--logic-root", str(logic)],
                   work / "rules", "rules_artifact.json")
    diagram = _stage("06_diagram.py", ["--parser-root", str(parser), "--data-root", str(data),
                                       "--logic-root", str(logic), "--rules-root", str(rules),
                                       "--inventory-root", str(inv)],
                     work / "diagram", "diagrams_artifact.json")

    out = work / "report" / "run"
    cmd = [sys.executable, str(SCRIPTS / "07_synthesis.py"),
           "--inventory-root", str(inv), "--parser-root", str(parser), "--data-root", str(data),
           "--logic-root", str(logic), "--rules-root", str(rules), "--diagram-root", str(diagram),
           "--output", str(out)]
    if annotations:
        cmd += ["--annotations", str(annotations)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"07_synthesis.py failed:\n{r.stdout}\n{r.stderr}")
    brd = (out / "brd.md").read_text(encoding="utf-8")
    index = json.loads((out / "brd_index.json").read_text(encoding="utf-8"))
    return brd, index, work


# ---------------------------------------------------------------------------
# Unit: the business language layer
# ---------------------------------------------------------------------------

def test_business_language() -> None:
    print("\n=== Unit: identifiers become business language ===")
    check(bl.object_title("PROC-.SP_TRANSFER_FUNDS") == "Transfer Funds",
          "object identifier loses its type prefix and naming convention noise")
    check(bl.object_title("FUNC-.FN_CALCULATE_SIMPLE_INTEREST") == "Calculate Simple Interest",
          "function identifier becomes a capability name")
    check(bl.humanise("p_from_account") == "From Account",
          "parameter prefix stripped")
    check(bl.humanise("LAST_TXN_DATE") == "Last Transaction Date",
          "abbreviations expanded")
    # Regression: `e_` is the Oracle exception convention; keeping it produced
    # the meaningless "E Insufficient Balance".
    check(bl.humanise("e_insufficient_balance") == "Insufficient Balance",
          "exception prefix stripped")
    check(bl.humanise("rec.balance") == "Balance",
          "loop record qualifier dropped — 'Rec Balance' is worse than nothing")
    check(bl.entity_title("TRANSACTION_LEDGER") == "Transaction Ledger",
          "table name becomes an entity name")

    print("\n=== Unit: conditions become readable ===")
    out = bl.humanise_condition("v_from_balance < p_amount")
    check(out == "From Balance is below Amount",
          f"comparison reads as a sentence (got '{out}')")
    # Regression: substituting operators before identifiers fed the inserted
    # words back through the identifier pass, yielding "is Below".
    check("Below" not in out, "inserted operator words are not title-cased")
    check(bl.humanise_condition("v_status = 'ACTIVE'") == "Status is 'ACTIVE'",
          "quoted literals survive substitution untouched")
    check("is missing" in bl.humanise_condition("p_principal IS NULL"),
          "null checks read as plain English")

    print("\n=== Unit: types become readable ===")
    check(bl.plain_type("NUMBER(18,2)") == "Decimal number (18 digits, 2 decimal places)",
          "numeric precision explained")
    check(bl.plain_type("VARCHAR2(20)") == "Text (up to 20 characters)", "text length explained")


def test_provenance_stripping() -> None:
    """Upstream prose embeds provenance that is already a labelled attribute."""
    print("\n=== Unit: provenance removed from prose ===")
    # Regression: the original pattern used [^.]*? which can never span an
    # object id, because object ids contain a period.
    out = syn.humanise_description(
        "When x, the system does y. Implemented in PROC-.SP_A, line 33.", {}, {})
    check("Implemented in" not in out and "PROC-" not in out,
          "trailing 'Implemented in <object>, line N' is removed")
    out = syn.humanise_description(
        "Rejected and e_no_account is raised (PROC-.SP_A, line 30).", {}, {})
    check("(PROC-" not in out, "parenthesised provenance is removed")
    check("Insufficient" in syn.humanise_description("raises e_insufficient_funds", {}, {})
          or "Funds" in syn.humanise_description("raises e_insufficient_funds", {}, {}),
          "exception names in prose become business language")


def test_modality() -> None:
    """SBVR: a rule the database enforces cannot be violated; a code guard can."""
    print("\n=== Unit: SBVR modality ===")
    enforced = {"source": {"kind": "ddl_check_constraint"}, "condition_text": "x IN ('A')",
                "category": "VALIDATION", "is_enforced": True}
    guard = {"source": {"kind": "conditional_branch"}, "condition_text": "a < b",
             "category": "VALIDATION", "raises": "e_x"}
    check(syn.rule_modality(enforced) == "alethic", "an enforced constraint is definitional")
    check(syn.rule_modality(guard) == "deontic", "a code guard is behavioural")
    check(syn.formal_statement(enforced).startswith("It is necessary that"),
          "definitional rules read 'it is necessary that'")
    check(syn.formal_statement(guard).startswith("It is obligatory that"),
          "behavioural rules read 'it is obligatory that'")

    disabled = dict(enforced, is_enforced=False)
    check("NOT being enforced" in syn.formal_statement(disabled),
          "a disabled constraint is never stated as a guarantee")
    check(syn.verification_method(enforced).startswith("Inspection"),
          "a schema-enforced rule is verified by inspection")
    check(syn.verification_method(guard).startswith("Test"),
          "a code-enforced rule is verified by test")


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

def test_readable_for_a_business_reader(brd: str) -> None:
    print("\n=== Readable: no machine identifiers in prose ===")
    # Fenced blocks (pseudocode, diagrams) are deliberately technical — they
    # exist for the build team and must stay faithful to the source. Only the
    # surrounding prose has to be readable by a business audience.
    prose_lines, in_fence = [], False
    for line in brd.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.strip().startswith(("*Technical name", "|")) or "`" in line:
            continue
        prose_lines.append(line)
    prose = "\n".join(prose_lines)
    for bad in ("PROC-.", "FUNC-.", "STMT_", "NESTED_BLOCK", "SINGLE_RECORD_TRANSACTION",
                "BATCH_PROCESSOR", "v_", "p_"):
        check(bad not in prose, f"prose is free of '{bad}'")
    check("Transfer Funds" in brd, "capabilities are named in business language")


def test_structure_and_navigation(brd: str) -> None:
    print("\n=== Structure: a reader can find things ===")
    check("## Contents" in brd, "a contents page is present")
    anchors = set(re.findall(r"\]\(#([\w-]+)\)", brd))
    headings = {bl.anchor(h) for h in re.findall(r"^#{2,4} (.+)$", brd, re.M)}
    missing = anchors - headings
    check(not missing, f"every contents link points at a real heading (broken: {sorted(missing)[:3]})")
    check(len(anchors) >= 15, f"contents covers the document ({len(anchors)} links)")
    # Regression: 41 rule headings previously swamped the contents page.
    check(len(anchors) <= 80, f"contents stays navigable ({len(anchors)} links)")

    for section in ["Document Control", "How to Read This Document", "Part I", "Part II",
                    "Part III", "Part IV", "Scope", "Business Glossary",
                    "Business Rules Catalogue", "Data Model", "Interface Contracts",
                    "Requirements Traceability Matrix", "Rebuilding This System"]:
        check(section in brd, f"section present: {section}")


def test_completeness_for_a_build_team(brd: str, index: dict) -> None:
    print("\n=== Complete: enough to rebuild from ===")
    check("Supplied by caller" in brd, "interface parameters are documented with direction")
    check("Rebuild as" in brd, "each field carries a target type for a rebuild")
    check("Transaction boundary" in brd, "transaction boundaries are stated per capability")
    # Regression: a HIGH severity hazard was computed upstream and discarded.
    check("Savepoint Partial Rollback" in brd or "Transaction behaviour" in brd,
          "transaction hazards reach the document")
    check(brd.count("|") > 400, "content is presented as tables, not walls of prose")
    check("Decimal number" in brd, "field types are explained, not just quoted")


def test_traceability(brd: str, index: dict) -> None:
    print("\n=== Traceable: every rule can be checked ===")
    rows = index["traceability"]
    check(len(rows) == len(index["requirements"]), "every requirement has a traceability row")
    check(all(r.get("rule_id") for r in rows), "every row identifies its rule")
    with_line = [r for r in rows if r.get("line")]
    check(len(with_line) / max(len(rows), 1) > 0.8,
          f"most rules cite an exact source line ({len(with_line)}/{len(rows)})")
    ids = {r["id"] for r in index["requirements"]}
    referenced = set(re.findall(r"\bBR-\d{3}\b", brd))
    check(referenced <= ids, f"no invented rule ids (extras: {sorted(referenced - ids)[:3]})")


def test_machine_readable(index: dict) -> None:
    print("\n=== Machine-readable companion ===")
    for key in ("document", "capabilities", "requirements", "glossary", "gaps", "traceability"):
        check(key in index, f"index exposes '{key}'")
    r = index["requirements"][0]
    for attr in ("id", "heading", "text", "formal", "modality", "type",
                 "confidence", "verification_method", "source"):
        check(attr in r, f"each requirement carries the '{attr}' attribute")
    check({x["modality"] for x in index["requirements"]} <= {"alethic", "deontic"},
          "modality is one of the two SBVR values")


def test_honesty(brd: str, index: dict) -> None:
    print("\n=== Honest about its own limits ===")
    check("Out of scope" in brd, "what is NOT covered is stated explicitly")
    check("cannot" in brd.lower(), "the document states what the method cannot do")
    check("no language model generates" in brd.lower(),
          "provenance of the content is declared")
    # The hallucination guarantee is structural, not statistical — there is no
    # model in the generation path, so there is no temperature to tune.
    check("structurally impossible" in brd.lower(),
          "the document states that hallucination is structurally impossible, not merely rare")
    check(len(index["gaps"]) > 0, "open matters are surfaced rather than hidden")
    check("to be assigned" in brd, "unknowable attributes appear as visible blanks")
    check("Needs review" in brd, "uncertain rules are marked")


def test_annotations_survive(work_root: Path) -> None:
    """
    The curation layer. Static analysis cannot recover why a threshold exists;
    every commercial tool in this space ships somewhere for a human to say so.
    """
    print("\n=== Annotations: human knowledge is merged in ===")
    with tempfile.TemporaryDirectory() as tmp:
        ann = Path(tmp) / "notes.json"
        ann.write_text(json.dumps({"annotations": {
            "BR-001": {"note": "Mandated by regulation, not chosen.",
                       "owner": "Head of Retail", "priority": "Must have"},
            "executive_summary": {"note": "Core ledger, in service since 2004."},
        }}), encoding="utf-8")
        brd, index, _ = run_pipeline(Path(tmp) / "run", annotations=ann)
    check("Mandated by regulation" in brd, "a rule annotation reaches the document")
    check("in service since 2004" in brd, "an executive-summary annotation reaches the document")
    check("Head of Retail" in brd, "an owner annotation fills the 29148 Owner attribute")
    br1 = next((r for r in index["requirements"] if r["id"] == "BR-001"), None)
    check(br1 and br1.get("owner") == "Head of Retail",
          "annotations also reach the machine-readable index")


def main() -> int:
    test_business_language()
    test_provenance_stripping()
    test_modality()

    with tempfile.TemporaryDirectory() as tmp:
        brd, index, work = run_pipeline(Path(tmp))
        test_readable_for_a_business_reader(brd)
        test_structure_and_navigation(brd)
        test_completeness_for_a_build_team(brd, index)
        test_traceability(brd, index)
        test_machine_readable(index)
        test_honesty(brd, index)

    test_annotations_survive(ROOT)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
