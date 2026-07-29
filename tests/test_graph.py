#!/usr/bin/env python3
"""
Regression tests for the knowledge graph (08_graph.py, lib_graph_model,
lib_graph_language).

The predecessor suite had 13 checks against a 5-node-type export. It could not
have caught the defects this redesign fixed, because the things now asserted —
column-level lineage, statement provenance, refusal to guess — did not exist.

The most important tests here are the NEGATIVE ones. A knowledge graph that
answers confidently and wrongly is worse than no graph at all, so the suite
checks that unknown questions are refused, that unidentifiable entities are
refused, and that the limits of the graph are exported rather than assumed away.

Usage:
    python tests/test_graph.py
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

bl = importlib.import_module("lib_business_language")
gm = importlib.import_module("lib_graph_model")
gl = importlib.import_module("lib_graph_language")
g8 = importlib.import_module("08_graph")

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


def run_pipeline(work: Path):
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
    report = _stage("07_synthesis.py", ["--inventory-root", str(inv), "--parser-root", str(parser),
                                        "--data-root", str(data), "--logic-root", str(logic),
                                        "--rules-root", str(rules), "--diagram-root", str(diagram)],
                    work / "report", "brd_index.json")

    out = work / "graph" / "run"
    roots = ["--inventory-root", str(inv), "--parser-root", str(parser), "--data-root", str(data),
             "--logic-root", str(logic), "--rules-root", str(rules),
             "--diagram-root", str(diagram), "--report-root", str(report)]
    r = subprocess.run([sys.executable, str(SCRIPTS / "08_graph.py"), *roots,
                        "--output", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"08_graph.py failed:\n{r.stdout}\n{r.stderr}")
    artifact = json.loads((out / "graph_artifact.json").read_text(encoding="utf-8"))
    cypher = (out / "import.cypher").read_text(encoding="utf-8")
    readme = (out / "README.md").read_text(encoding="utf-8")
    return artifact, cypher, readme, out, roots


def build_local_graph(roots: list):
    class A:
        pass
    a = A()
    a.run = "latest"
    for i in range(0, len(roots), 2):
        setattr(a, roots[i].lstrip("-").replace("-", "_"), roots[i + 1])
    return gm.build_graph(g8.collect_artifacts(a), bl.humanise, bl.object_title, bl.entity_title)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_schema(artifact: dict) -> None:
    print("\n=== Schema: the nodes that make the graph worth building ===")
    n = artifact["stats"]["nodes"]
    r = artifact["stats"]["relationships"]

    # Column as a node is the whole basis of impact analysis; without it the
    # graph can only say "this procedure touches ACCOUNTS".
    check(n.get("Column", 0) > 0, f"Column is a node ({n.get('Column', 0)})")
    check(n.get("Statement", 0) > 0, f"Statement is a node ({n.get('Statement', 0)})")
    check(n.get("Parameter", 0) > 0, f"Parameter is a node ({n.get('Parameter', 0)})")
    check(n.get("BusinessRule", 0) > 0, "BusinessRule is a node")
    check(n.get("Gap", 0) > 0, "Gaps from Agent 7 reach the graph")
    check(n.get("State", 0) > 0, "Entity states reach the graph")
    check(n.get("BlindSpot", 0) >= 4, "blind spots are exported as queryable nodes")

    check(r.get("READS_COLUMN", 0) > 0 and r.get("WRITES_COLUMN", 0) > 0,
          "column-level lineage exists in both directions")
    check(r.get("IMPLEMENTED_AT", 0) > 0,
          "rules link to the exact statement that implements them")
    check(r.get("FOLLOWS", 0) > 0 and r.get("BRANCHES_TO", 0) > 0,
          "the control-flow layer is present (Code Property Graph)")
    check(r.get("HAS_PARAMETER", 0) > 0, "the interface contract is in the graph")


def test_upstream_coverage(artifact: dict) -> None:
    """The predecessor read 4 of 7 artifacts. All 7 must contribute."""
    print("\n=== Coverage: every upstream agent contributes ===")
    n, r = artifact["stats"]["nodes"], artifact["stats"]["relationships"]
    for label, node, why in [
        ("1 inventory", "File", "files"),
        ("2 parser", "Statement", "statements and control flow"),
        ("3 data", "Column", "tables and columns"),
        ("5 rules", "BusinessRule", "business rules"),
        ("7 synthesis", "Gap", "open matters"),
    ]:
        check(n.get(node, 0) > 0, f"Agent {label} contributes {why}")
    # Agent 4 shows up as edges and properties rather than as its own label.
    check(r.get("DETERMINES", 0) > 0, "Agent 4 logic contributes dependence edges")
    check(n.get("State", 0) > 0, "Agent 6 diagram contributes entity states")


def test_export_is_loadable(cypher: str, out: Path) -> None:
    print("\n=== Export: safe and complete ===")
    check(cypher.count("MERGE") > 0, "the script uses MERGE")
    check("CREATE (" not in cypher, "no bare CREATE — re-running cannot duplicate data")
    check("CREATE CONSTRAINT" in cypher, "uniqueness constraints are declared")
    # Every MATCH used to attach a relationship must reference a node the
    # script created earlier, or the load silently drops edges.
    check(cypher.index("MERGE (n:") < cypher.index("MATCH ("),
          "nodes are created before relationships reference them")
    check((out / "nodes").is_dir() and (out / "rels").is_dir(), "CSV directories exist")
    check(len(list((out / "nodes").glob("*.csv"))) >= 10, "one CSV per node label")
    check((out / "README.md").exists(), "an import and query guide is written")


def test_documentation(readme: str, artifact: dict) -> None:
    print("\n=== Documentation: a graph nobody can query is useless ===")
    check("## Loading it" in readme, "loading instructions present")
    check("cypher-shell" in readme, "a concrete load command is given")
    check("## Questions this graph answers" in readme, "the question catalogue is published")
    check("## Concepts" in readme and "## Constraints" in readme,
          "derived views and validations ship with the graph")
    check("cannot see" in readme.lower(), "limits are documented, not implied")
    check(len(artifact["supported_questions"]) >= 10, "at least ten questions supported")
    check(len(artifact["blind_spots"]) >= 4, "blind spots are declared in the artifact")


# ---------------------------------------------------------------------------
# The plain-English interface
# ---------------------------------------------------------------------------

def test_answers(graph) -> None:
    print("\n=== Plain English: real questions get real answers ===")

    res = gl.ask(graph, "what breaks if I change ACCOUNTS.BALANCE")
    check(res["ok"] and res["intent"] == "impact_of_column", "impact question is understood")
    check(res["row_count"] > 0, "impact answer is non-empty")
    joined = " ".join(" ".join(str(c) for c in row) for row in res["rows"])
    check("line" in joined, "impact is reported at line level, not just procedure level")

    res = gl.ask(graph, "which rules apply to SP_TRANSFER_FUNDS")
    check(res["ok"] and res["row_count"] >= 5, "rules-for-a-unit question answered")

    res = gl.ask(graph, "where is BR-014 implemented")
    check(res["ok"] and "BR-014" in res["subject"], "rule provenance question answered")

    res = gl.ask(graph, "who writes to the ACCOUNTS table")
    check(res["ok"] and res["row_count"] > 0, "table access question answered")

    res = gl.ask(graph, "how do I call SP_TRANSFER_FUNDS")
    check(res["ok"] and res["row_count"] == 6, "interface question returns all 6 parameters")

    res = gl.ask(graph, "which rules still need review")
    check(res["ok"], "review-status question answered")

    res = gl.ask(graph, "what are the most complex program units")
    check(res["ok"] and (res["rows"][0][1] or 0) >= (res["rows"][-1][1] or 0),
          "complexity question answered, ranked highest first")

    res = gl.ask(graph, "which tables are never used")
    check(res["ok"], "orphan-table question answered")

    res = gl.ask(graph, "what can this graph not see")
    check(res["ok"] and res["row_count"] >= 4, "the graph reports its own blind spots")

    for r in [gl.ask(graph, q) for q in
              ["what breaks if I change ACCOUNTS.BALANCE",
               "which rules apply to SP_TRANSFER_FUNDS"]]:
        check(bool(r.get("cypher")), "every answer ships the equivalent Cypher")


def test_refusals(graph) -> None:
    """
    The negative tests, and the most important ones here.

    An impact-analysis answer that silently omits a dependency is the failure
    mode that sinks modernization projects. This interface must miss loudly
    rather than guess quietly.
    """
    print("\n=== Refusal: it never guesses ===")

    res = gl.ask(graph, "what is the meaning of life")
    check(not res["ok"], "an unsupported question is refused")
    check(bool(res.get("suggestions")), "a refusal lists what CAN be answered")

    res = gl.ask(graph, "what breaks if I change SOMETHING_NONEXISTENT.FIELD")
    check(not res["ok"], "an unidentifiable entity is refused, not approximated")

    res = gl.ask(graph, "")
    check(not res["ok"], "an empty question is refused")

    label, key = gl.resolve_entity(graph, "tell me about ACCOUNTS.BALANCE")
    check((label, key) == ("Column", "ACCOUNTS.BALANCE"), "qualified columns resolve exactly")
    label, key = gl.resolve_entity(graph, "what about BR-014")
    check((label, key) == ("BusinessRule", "BR-014"), "rule ids resolve exactly")
    label, _ = gl.resolve_entity(graph, "nothing named in this sentence")
    check(label is None, "a question naming nothing resolves to nothing")


def test_model_invariants(graph) -> None:
    print("\n=== Model invariants ===")
    # A dangling edge would silently disappear on load into Neo4j.
    dangling = [r for r in graph.rels
                if r[2] not in graph.nodes.get(r[1], {}) or r[4] not in graph.nodes.get(r[3], {})]
    check(not dangling, f"no relationship points at a missing node ({len(dangling)} found)")

    sigs = {(r[0], r[1], r[2], r[3], r[4], tuple(sorted(r[5].items()))) for r in graph.rels}
    check(len(sigs) == len(graph.rels), "no duplicate relationships")

    orphan_cols = [c for c in graph.nodes.get("Column", {})
                   if not [x for x in graph.inn("Column", c) if x[0] == "HAS_COLUMN"]]
    check(not orphan_cols, f"every Column belongs to a Table ({len(orphan_cols)} orphaned)")

    orphan_stmts = [s for s in graph.nodes.get("Statement", {})
                    if not [x for x in graph.inn("Statement", s) if x[0] == "CONTAINS_STATEMENT"]]
    check(not orphan_stmts, f"every Statement belongs to an Object ({len(orphan_stmts)} orphaned)")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        artifact, cypher, readme, out, roots = run_pipeline(Path(tmp))
        graph = build_local_graph(roots)

        test_schema(artifact)
        test_upstream_coverage(artifact)
        test_export_is_loadable(cypher, out)
        test_documentation(readme, artifact)
        test_answers(graph)
        test_refusals(graph)
        test_model_invariants(graph)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
