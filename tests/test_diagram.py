#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/06_diagram.py (redesigned agent).

The previous suite had 7 checks, all syntactic — does the file start with
`flowchart TD`, do node ids avoid leading digits. It could not have caught any
of the defects the redesign fixed, because the only thing it could inspect was
a formatted string.

This suite asserts against the intermediate `DiagramSpec`, which is the point
of separating the model from the renderer. Structural checks on Mermaid text
remain, but they are now the last line of defence rather than the only one.

Each test traces to a specific defect or design invariant, noted inline.

Usage:
    python tests/test_diagram.py
"""

import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "scripts"
sys.path.insert(0, str(SCRIPTS))

dg = importlib.import_module("06_diagram")

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


def run_pipeline(work: Path) -> tuple:
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

    out = work / "diagram" / "run"
    r = subprocess.run([sys.executable, str(SCRIPTS / "06_diagram.py"),
                        "--parser-root", str(parser), "--data-root", str(data),
                        "--logic-root", str(logic), "--rules-root", str(rules),
                        "--inventory-root", str(inv), "--output", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"06_diagram.py failed:\n{r.stdout}\n{r.stderr}")
    artifact = json.loads((out / "diagrams_artifact.json").read_text(encoding="utf-8"))
    texts = {p.name: p.read_text(encoding="utf-8") for p in (out / "diagrams").glob("*.mmd")}
    return artifact, texts


# ---------------------------------------------------------------------------
# Unit tests against the model — impossible with the old string-building design
# ---------------------------------------------------------------------------

def test_collapse_invariant() -> None:
    """Detail is lost from straight-line runs first. A reader must always be
    able to see the shape of the logic, so structure is never collapsed."""
    print("\n=== Unit: collapse never removes structure ===")
    statements, ids = {}, []
    for i in range(1, 31):
        kind = "IF" if i % 10 == 0 else ("EXCEPTION_HANDLER" if i == 25 else "ASSIGNMENT")
        sid = f"S{i:03d}"
        statements[sid] = {"statement_id": sid, "statement_type": kind,
                           "start_line": i, "end_line": i, "parent_id": None}
        ids.append(sid)

    remap = dg.collapse_runs(ids, statements, budget=8)
    survivors = set(remap.values())
    check(len(survivors) < len(ids), "collapse reduces node count when over budget")
    for sid, s in statements.items():
        if s["statement_type"] in ("IF", "EXCEPTION_HANDLER"):
            check(remap[sid] == sid,
                  f"{s['statement_type']} at line {s['start_line']} survives collapse")

    untouched = dg.collapse_runs(ids, statements, budget=100)
    check(all(v == k for k, v in untouched.items()),
          "nothing is collapsed when the diagram already fits the budget")


def test_label_ladder() -> None:
    """Tier 1 rule text > tier 2 structured field > tier 3 fallback."""
    print("\n=== Unit: label resolution ladder ===")

    class FakeIdx:
        rules = {("OBJ", 10): [{"rule_id": "BR-001", "condition_text": "v_balance < 100",
                                "signal_strength": 5}]}

        def rule_at(self, oid, line):
            hits = self.rules.get((oid, line))
            return hits[0] if hits else None

        def rule_in_span(self, oid, start, end):
            return self.rule_at(oid, start)

    idx = FakeIdx()
    label, rules, tier = dg.label_for_statement(
        {"statement_type": "IF", "start_line": 10, "end_line": 12}, "OBJ", idx, "")
    check(tier == 1 and "balance" in label and label.endswith("?"),
          "a decision with a rule gets the business condition as a question")
    check(rules == ["BR-001"], "the decision node carries its rule id for traceability")

    label, _, tier = dg.label_for_statement(
        {"statement_type": "UPDATE", "start_line": 99, "end_line": 99, "tables": ["accounts"]},
        "OBJ", idx, "")
    check(tier == 2 and label == "Update ACCOUNTS", "DML falls back to the table it writes")

    # Regression: a rule anchored at a non-decision statement describes the
    # BRANCH starting there, not the statement. Taking it produced an UPDATE
    # drawn as a data store bearing an ELSIF's condition.
    label, _, tier = dg.label_for_statement(
        {"statement_type": "UPDATE", "start_line": 10, "end_line": 10, "tables": ["accounts"]},
        "OBJ", idx, "")
    check(label == "Update ACCOUNTS" and tier == 2,
          "a branch rule never labels a non-decision statement")


def test_condition_humanising() -> None:
    print("\n=== Unit: condition text stays balanced ===")
    # Regression: a blanket strip("()") amputated the closing paren of
    # NVL(x, y - 9999), leaving a label that looked truncated.
    out = dg.humanise_condition("days := as_of - NVL(last_txn, as_of - 9999)")
    check(out.count("(") == out.count(")"), "parentheses stay balanced")
    check(out.endswith(")"), "a trailing paren belonging to a function call is kept")
    check(dg.humanise_condition("(v_a > 1)") == "a > 1",
          "a wrapper enclosing the whole expression is still removed")


def test_branch_label_cleanup() -> None:
    print("\n=== Unit: no parser syntax in branch labels ===")

    class Idx:
        def rule_at(self, oid, line):
            return None

    label, rid = dg.branch_label("WHEN(NO_DATA_FOUND)", "OBJ", None, None, Idx())
    check(label == "NO_DATA_FOUND", "WHEN(...) wrapper stripped from handler labels")
    label, _ = dg.branch_label("NESTED_BLOCK#5", "OBJ", None, None, Idx())
    check(label == "", "parser-internal block names never reach a label")


def test_state_model_refuses_to_guess() -> None:
    """The only place this agent derives new knowledge, so the evidence bar is
    highest: an unresolvable transition is dropped, never invented."""
    print("\n=== Unit: state model discovery ===")

    class Idx:
        tables = {"ACCOUNTS": {"check_constraints": [
            {"name": "CK_S", "expression": "account_status IN ('ACTIVE','DORMANT','CLOSED')"}]},
            "NOSTATE": {"check_constraints": [
                {"name": "CK_X", "expression": "amount > 0"}]}}

    found = dg.discover_state_attributes(Idx())
    check("ACCOUNTS" in found, "an IN-list CHECK constraint is recognised as a state set")
    check(found["ACCOUNTS"]["states"] == ["ACTIVE", "DORMANT", "CLOSED"], "all states extracted")
    check("NOSTATE" not in found, "a range CHECK constraint is not mistaken for a state set")


def test_renderer_escaping() -> None:
    print("\n=== Unit: renderer escaping ===")
    spec = dg.DiagramSpec(diagram_id="t", type="process_flow", title="t")
    spec.nodes = [dg.Node(id="N1", kind=dg.KIND_DECISION, label='a "quoted" (paren) value')]
    text = dg.MermaidRenderer().render(spec)
    check("#quot;" in text, "embedded quotes become the #quot; entity")
    check(not dg.validate_mermaid(text, "t"), "escaped output passes structural validation")


# ---------------------------------------------------------------------------
# Integration + quality gates
# ---------------------------------------------------------------------------

def test_diagram_set(artifact: dict, texts: dict) -> None:
    print("\n=== Integration: the expected diagram set is produced ===")
    types = {e["type"] for e in artifact["diagram_index"].values()}
    check("dataflow" in types, "a system data-flow map is produced")
    check("process_flow" in types, "per-object process flows are produced")
    check("state" in types, "an entity state model is produced")
    check(bool(artifact.get("erd_reference")), "Agent 3's ERD is indexed, not regenerated")
    check(bool(artifact["crud_matrix"]["markdown"]), "the CRUD matrix is rendered")

    # Regression: the predecessor's component diagram had 5 nodes and 0 edges,
    # because this codebase has no internal calls. Joining the CRUD matrix is
    # what makes the overview carry information.
    flow = next(e for e in artifact["diagram_index"].values() if e["type"] == "dataflow")
    check(flow["edges"] > 0, "the data-flow map has edges (the old call graph had none)")


def test_quality_gates(artifact: dict) -> None:
    print("\n=== Quality gates ===")
    q = artifact["quality"]
    check(q["decision_label_tier1_pct"] >= 0.90,
          f"decision nodes carrying business text >= 90% (got {q['decision_label_tier1_pct']:.0%})")
    check(q["branch_traceability_pct"] >= 0.80,
          f"decision branches carrying a BR-id >= 80% (got {q['branch_traceability_pct']:.0%})")
    check(q["leaked_identifiers"] == 0, "no internal identifiers leaked")
    check(q["fallback_labels"] / max(q["total_nodes"], 1) < 0.15,
          f"tier-3 fallback labels stay marginal ({q['fallback_labels']}/{q['total_nodes']})")


def test_budget_is_enforced_or_declared(artifact: dict) -> None:
    """The old --max-nodes flag was declared and never read. Exceeding the
    budget is allowed only when the overrun is declared and explained."""
    print("\n=== Budget: enforced, or declared when structure forbids it ===")
    budget = artifact["node_budget"]
    for name, entry in artifact["diagram_index"].items():
        if entry["type"] != "process_flow":
            continue
        report = entry["budget"]
        within = entry["nodes"] <= budget
        check(within or report.get("oversize"),
              f"{name}: {entry['nodes']} nodes within budget {budget} or declared oversize")
        if report.get("oversize"):
            check(any(w["kind"] == "OVERSIZE" and w["diagram"] in name
                      for w in artifact["warnings"]),
                  f"{name}: the overrun is reported as a warning for the BRD")
    check(any(e["budget"].get("collapsed") or e["budget"].get("oversize")
              for e in artifact["diagram_index"].values()),
          "collapsing and oversize decisions are recorded, never silent")


def test_rendered_output_is_valid(artifact: dict, texts: dict) -> None:
    print("\n=== Rendered Mermaid ===")
    check(len(texts) == len(artifact["diagram_index"]),
          "every indexed diagram has a rendered file")
    for name, text in sorted(texts.items()):
        problems = dg.validate_mermaid(text, name)
        check(not problems, f"{name} passes structural validation")
    joined = "\n".join(texts.values())
    for bad in ("STMT_", "NESTED_BLOCK#", "IF#"):
        check(bad not in joined, f"no rendered diagram leaks '{bad}'")
    check("BR-" in joined, "rule ids appear in diagrams so the BRD can be cross-referenced")


def test_traceability_back_to_source(artifact: dict) -> None:
    """Green's hidden-dependencies problem: a diagram that cannot be tied back
    to the statement it came from is unverifiable."""
    print("\n=== Traceability ===")
    flows = [e for e in artifact["diagram_index"].values() if e["type"] == "process_flow"]
    check(all(e.get("node_origins") for e in flows),
          "each process flow records the real statement id behind every node")
    check(all(e.get("object_id") for e in flows), "each process flow names its object")
    check(any(e.get("rule_ids") for e in flows), "process flows list the rules they display")


def main() -> int:
    test_collapse_invariant()
    test_label_ladder()
    test_condition_humanising()
    test_branch_label_cleanup()
    test_state_model_refuses_to_guess()
    test_renderer_escaping()

    with tempfile.TemporaryDirectory() as tmp:
        artifact, texts = run_pipeline(Path(tmp))
        test_diagram_set(artifact, texts)
        test_quality_gates(artifact)
        test_budget_is_enforced_or_declared(artifact)
        test_rendered_output_is_valid(artifact, texts)
        test_traceability_back_to_source(artifact)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
