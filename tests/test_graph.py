#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/08_graph.py.

Headline regression guard: business_rules.csv's rule_set_id column was
empty for every row because rule_rows was built BEFORE the loop that
actually assigns rule_set_id onto each rule record — a plain ordering bug,
caught only by reading the actual generated CSV, not by reviewing the code.

Also verifies: CSV files parse as valid CSV with the right row counts,
import.cypher uses MERGE (never CREATE, for safe re-import), and every
CSV cross-reference (e.g. enforced_in -> a real object/table) is real.
"""

import csv
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "scripts"

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def run_step(script, out_dir, extra_args):
    cmd = [sys.executable, str(script)] + extra_args + ["--output", str(out_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{script.name} failed:\n{r.stdout}\n{r.stderr}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        subprocess.run([sys.executable, str(SCRIPTS / "01_inventory.py"), str(ROOT / "src"),
                         "--output", str(work / "inventory" / "run" / "inventory-artifact.json")],
                        capture_output=True, text=True, check=True)
        (work / "inventory" / "latest.json").write_text(json.dumps(
            {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "t"}))
        run_step(SCRIPTS / "02_parser.py", work / "parser" / "run", ["--inventory-root", str(work / "inventory")])
        (work / "parser" / "latest.json").write_text(json.dumps(
            {"run_version": "run", "path": "run/parser_artifact.json", "updated_at": "t"}))
        run_step(SCRIPTS / "03_data.py", work / "data" / "run",
                  ["--inventory-root", str(work / "inventory"), "--parser-root", str(work / "parser")])
        (work / "data" / "latest.json").write_text(json.dumps(
            {"run_version": "run", "path": "run/data_artifact.json", "updated_at": "t"}))
        run_step(SCRIPTS / "05_rules.py", work / "rules" / "run",
                  ["--parser-root", str(work / "parser"), "--data-root", str(work / "data"),
                   "--inventory-root", str(work / "inventory")])
        (work / "rules" / "latest.json").write_text(json.dumps(
            {"run_version": "run", "path": "run/rules_artifact.json", "updated_at": "t"}))

        graph_dir = work / "graph_out"
        r = subprocess.run([sys.executable, str(SCRIPTS / "08_graph.py"),
                             "--inventory-root", str(work / "inventory"), "--parser-root", str(work / "parser"),
                             "--data-root", str(work / "data"), "--rules-root", str(work / "rules"),
                             "--output", str(graph_dir)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"08_graph.py failed:\n{r.stdout}\n{r.stderr}")
        print(r.stdout)

        rules_artifact = json.loads((work / "rules" / "run" / "rules_artifact.json").read_text(encoding="utf-8"))
        real_rule_ids = {rr["rule_id"] for rr in rules_artifact["business_rules"]}
        real_rule_set_ids = {rs["rule_set_id"] for rs in rules_artifact["rule_sets"]}

        print("\n=== Regression guard: rule_set_id must not be empty ===")
        rows = list(csv.DictReader(io.StringIO((graph_dir / "nodes" / "business_rules.csv").read_text(encoding="utf-8"))))
        check(len(rows) == len(real_rule_ids), f"business_rules.csv row count matches rules_artifact ({len(rows)})")
        check(all(row["rule_set_id"] for row in rows), "every row has a non-empty rule_set_id")
        check(all(row["rule_set_id"] in real_rule_set_ids for row in rows),
              "every rule_set_id in the CSV is a real rule set, not a stray value")

        print("\n=== CSV structural sanity ===")
        obj_rows = list(csv.DictReader(io.StringIO((graph_dir / "nodes" / "objects.csv").read_text(encoding="utf-8"))))
        check(len(obj_rows) == 5, f"5 object nodes exported, got {len(obj_rows)}")
        table_rows = list(csv.DictReader(io.StringIO((graph_dir / "nodes" / "tables.csv").read_text(encoding="utf-8"))))
        check(len(table_rows) == 15, f"15 table nodes exported, got {len(table_rows)}")

        enforced_rows = list(csv.DictReader(io.StringIO((graph_dir / "rels" / "enforced_in.csv").read_text(encoding="utf-8"))))
        real_object_ids = {r["object_id"] for r in obj_rows}
        real_table_names = {r["table"] for r in table_rows}
        bad_refs = [r for r in enforced_rows
                     if (r["target_type"] == "object" and r["target_id"] not in real_object_ids)
                     or (r["target_type"] == "table" and r["target_id"] not in real_table_names)]
        check(not bad_refs, f"every enforced_in.csv target is a real object/table node, bad refs: {bad_refs}")
        check(all(r["rule_id"] in real_rule_ids for r in enforced_rows), "every enforced_in.csv rule_id is real")

        print("\n=== Cypher script safety ===")
        cypher_text = (graph_dir / "import.cypher").read_text(encoding="utf-8")
        check("MERGE" in cypher_text, "import.cypher uses MERGE")
        check("\nCREATE (" not in cypher_text, "import.cypher never uses raw CREATE for nodes (must stay safe to re-run)")
        check(cypher_text.count("MERGE (n:BusinessRule") == len(real_rule_ids),
              "one MERGE statement per business rule node")

        print("\n=== Documentation files ===")
        check((graph_dir / "README.md").exists(), "README.md generated")
        check((graph_dir / "cypher_library.md").exists(), "cypher_library.md generated")
        check("not a live" in (graph_dir / "README.md").read_text(encoding="utf-8").lower() or
              "read-only" in (graph_dir / "graph_artifact.json").read_text(encoding="utf-8").lower(),
              "output is clearly documented as a read-only snapshot, not live pipeline infrastructure")

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
