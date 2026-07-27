#!/usr/bin/env python3
"""
Stage 8: NEO4J GRAPH (deterministic, no LLM, optional, terminal)
--------------------------------------------------------------------
Reads all prior artifacts and generates Neo4j import files (a Cypher
script + CSVs) that the user loads into Neo4j Desktop themselves. No
database connection, no Python driver. Uses MERGE (not CREATE) throughout
so it is safe to re-run.

Per the design discussion this agent resulted from: this is deliberately
NOT wired as a required dependency of any other agent. The JSON artifacts
remain the pipeline's single source of truth end to end; this is a
read-only, on-demand export for interactive graph exploration once the
BRD work is done — not infrastructure the other agents rely on.

Node types : File, Object, Table, BusinessRule, RuleSet
Rel types  : CONTAINS (file->object), CALLS (object->object),
             READS/WRITES (object->table, aggregated),
             REFERENCES (table->table FK), ENFORCED_IN (rule->object or
             rule->table for DDL-sourced rules), BELONGS_TO (rule->rule_set)
"""

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def generate_run_version() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H.%M.%S.") + f"{now.microsecond // 1000:03d}Z"


def load_run(root: str, run: str, artifact_filename: str) -> dict:
    root_path = Path(root)
    if run == "latest":
        pointer = json.loads((root_path / "latest.json").read_text(encoding="utf-8"))
        run_version = pointer["run_version"]
    else:
        run_version = run
    return json.loads((root_path / run_version / artifact_filename).read_text(encoding="utf-8")), Path(root_path / run_version)


def cypher_escape(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 8: Optional Neo4j graph export (no DB connection)")
    ap.add_argument("--inventory-root", default="output/inventory")
    ap.add_argument("--parser-root", default="output/parser")
    ap.add_argument("--data-root", default="output/data")
    ap.add_argument("--rules-root", default="output/rules")
    ap.add_argument("--run", default="latest")
    ap.add_argument("--output-root", default="output/final_report/graph")
    ap.add_argument("--output", default=None)
    ap.add_argument("--system-name", default="PL/SQL Banking System")
    args = ap.parse_args()

    inventory, _ = load_run(args.inventory_root, args.run, "inventory-artifact.json")
    parser_artifact, parser_root = load_run(args.parser_root, args.run, "parser_artifact.json")
    data_artifact, _ = load_run(args.data_root, args.run, "data_artifact.json")
    rules_artifact, _ = load_run(args.rules_root, args.run, "rules_artifact.json")

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    nodes_dir = run_dir / "nodes"
    rels_dir = run_dir / "rels"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    rels_dir.mkdir(parents=True, exist_ok=True)

    # ---- Nodes ----
    file_rows = [[fid, path] for fid, path in inventory["file_index"].items()]
    write_csv(nodes_dir / "files.csv", ["file_id", "path"], file_rows)

    object_rows = []
    file_of_object: dict[str, str] = {}
    for object_id, rel_path in parser_artifact["object_index"].items():
        obj_path = parser_root / rel_path
        obj = json.loads(obj_path.read_text(encoding="utf-8")) if obj_path.exists() else {}
        file_of_object[object_id] = obj.get("file_id", "")
        object_rows.append([object_id, obj.get("type", ""), obj.get("file_id", ""), obj.get("parse_status", "")])
    write_csv(nodes_dir / "objects.csv", ["object_id", "type", "file_id", "parse_status"], object_rows)

    table_rows = [[name, len(t["columns"]), ",".join(t["primary_key"] or [])]
                  for name, t in data_artifact["tables"].items()]
    write_csv(nodes_dir / "tables.csv", ["table", "column_count", "primary_key"], table_rows)

    # Must run BEFORE building rule_rows below — rule_set_id isn't present
    # on the rule records until this assignment happens. Building rule_rows
    # first (the original order here) silently produced an empty
    # rule_set_id column in business_rules.csv for every single row.
    for rs in rules_artifact["rule_sets"]:
        for r in rules_artifact["business_rules"]:
            if r["rule_id"] in rs["rule_ids"]:
                r["rule_set_id"] = rs["rule_set_id"]

    rule_rows = [[r["rule_id"], r["name"], r["category"], r["confidence"], r.get("rule_set_id", "")]
                 for r in rules_artifact["business_rules"]]
    write_csv(nodes_dir / "business_rules.csv", ["rule_id", "name", "category", "confidence", "rule_set_id"], rule_rows)

    rule_set_rows = [[rs["rule_set_id"], rs["name"], rs["rule_count"]] for rs in rules_artifact["rule_sets"]]
    write_csv(nodes_dir / "rule_sets.csv", ["rule_set_id", "name", "rule_count"], rule_set_rows)

    # ---- Relationships ----
    contains_rows = [[fid, oid] for oid, fid in file_of_object.items() if fid]
    write_csv(rels_dir / "contains.csv", ["file_id", "object_id"], contains_rows)

    calls_rows, reads_rows, writes_rows = [], [], []
    for object_id, rel_path in parser_artifact["object_index"].items():
        obj_path = parser_root / rel_path
        if not obj_path.exists():
            continue
        obj = json.loads(obj_path.read_text(encoding="utf-8"))
        seen_reads, seen_writes = set(), set()
        for stmt in obj.get("statements", {}).values():
            if stmt.get("statement_type") == "CALL" and stmt.get("resolved") and stmt.get("call_target_object_id"):
                calls_rows.append([object_id, stmt["call_target_object_id"]])
            for t in stmt.get("tables", []):
                if stmt.get("reads") and (object_id, t.upper()) not in seen_reads:
                    reads_rows.append([object_id, t.upper()]); seen_reads.add((object_id, t.upper()))
                if stmt.get("writes") and (object_id, t.upper()) not in seen_writes:
                    writes_rows.append([object_id, t.upper()]); seen_writes.add((object_id, t.upper()))
    write_csv(rels_dir / "calls.csv", ["from_object_id", "to_object_id"], calls_rows)
    write_csv(rels_dir / "reads.csv", ["object_id", "table"], reads_rows)
    write_csv(rels_dir / "writes.csv", ["object_id", "table"], writes_rows)

    references_rows = [[t["table"], fk["references_table"]] for t in
                        [{"table": n, **tbl} for n, tbl in data_artifact["tables"].items()]
                        for fk in t["foreign_keys"] if fk["references_table"] in data_artifact["tables"]]
    write_csv(rels_dir / "references.csv", ["from_table", "to_table"], references_rows)

    enforced_in_rows = []
    for r in rules_artifact["business_rules"]:
        src = r["source"]
        if src["kind"] == "ddl_check_constraint":
            enforced_in_rows.append([r["rule_id"], "table", src["table"]])
        else:
            enforced_in_rows.append([r["rule_id"], "object", src.get("object_id", "")])
    write_csv(rels_dir / "enforced_in.csv", ["rule_id", "target_type", "target_id"], enforced_in_rows)

    belongs_to_rows = [[r["rule_id"], r.get("rule_set_id", "")] for r in rules_artifact["business_rules"]]
    write_csv(rels_dir / "belongs_to.csv", ["rule_id", "rule_set_id"], belongs_to_rows)

    # ---- Cypher import script ----
    cy = [f"// PL/SQL Reverse Engineering Graph — Import Script\n// System  : {args.system_name}\n"
          f"// Generated: {datetime.now(timezone.utc).isoformat()}\n",
          "// SECTION 1 — Schema: constraints",
          "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Object) REQUIRE o.object_id IS UNIQUE;",
          "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Table) REQUIRE t.name IS UNIQUE;",
          "CREATE CONSTRAINT IF NOT EXISTS FOR (r:BusinessRule) REQUIRE r.rule_id IS UNIQUE;\n"]

    def merge_block(label, rows, header, key_field):
        cy.append(f"// SECTION — Nodes: {label}")
        for row in rows:
            props = ", ".join(f"{h}: '{cypher_escape(v)}'" for h, v in zip(header, row))
            cy.append(f"MERGE (n:{label} {{{header[0]}: '{cypher_escape(row[0])}'}}) SET n += {{{props}}};")
        cy.append("")

    merge_block("File", file_rows, ["file_id", "path"], "file_id")
    merge_block("Object", object_rows, ["object_id", "type", "file_id", "parse_status"], "object_id")
    merge_block("Table", table_rows, ["table", "column_count", "primary_key"], "table")
    merge_block("BusinessRule", rule_rows, ["rule_id", "name", "category", "confidence", "rule_set_id"], "rule_id")
    merge_block("RuleSet", rule_set_rows, ["rule_set_id", "name", "rule_count"], "rule_set_id")

    def merge_rel(rel_type, rows, from_label, from_key, to_label, to_key):
        cy.append(f"// SECTION — Relationships: {rel_type}")
        for a, b in rows:
            cy.append(f"MATCH (a:{from_label} {{{from_key}: '{cypher_escape(a)}'}}), "
                      f"(b:{to_label} {{{to_key}: '{cypher_escape(b)}'}}) MERGE (a)-[:{rel_type}]->(b);")
        cy.append("")

    merge_rel("CONTAINS", contains_rows, "File", "file_id", "Object", "object_id")
    merge_rel("CALLS", calls_rows, "Object", "object_id", "Object", "object_id")
    merge_rel("READS", reads_rows, "Object", "object_id", "Table", "table")
    merge_rel("WRITES", writes_rows, "Object", "object_id", "Table", "table")
    merge_rel("REFERENCES", references_rows, "Table", "table", "Table", "table")
    merge_rel("BELONGS_TO", belongs_to_rows, "BusinessRule", "rule_id", "RuleSet", "rule_set_id")
    cy.append("// SECTION — Relationships: ENFORCED_IN (target type varies — Object or Table)")
    for rule_id, target_type, target_id in enforced_in_rows:
        label = "Object" if target_type == "object" else "Table"
        key = "object_id" if target_type == "object" else "table"
        cy.append(f"MATCH (r:BusinessRule {{rule_id: '{cypher_escape(rule_id)}'}}), "
                  f"(t:{label} {{{key}: '{cypher_escape(target_id)}'}}) MERGE (r)-[:ENFORCED_IN]->(t);")

    (run_dir / "import.cypher").write_text("\n".join(cy) + "\n", encoding="utf-8")

    cypher_library = """# Cypher query library

## Count all nodes by type
MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY count DESC;

## Most-called objects (potential hub procedures)
MATCH (a:Object)-[:CALLS]->(b:Object)
WITH b, count(a) AS callers
RETURN b.object_id, callers ORDER BY callers DESC LIMIT 10;

## Objects that touch a given table
MATCH (o:Object)-[:READS|WRITES]->(t:Table {table: 'ACCOUNTS'})
RETURN o.object_id, o.type;

## Business rules enforced on a given table (impact analysis before a schema change)
MATCH (r:BusinessRule)-[:ENFORCED_IN]->(t:Table {table: 'ACCOUNTS'})
RETURN r.rule_id, r.name, r.confidence;

## Every rule requiring SME review
MATCH (r:BusinessRule) WHERE r.confidence IN ['low', 'medium']
RETURN r.rule_id, r.name, r.confidence ORDER BY r.confidence;

## Full call chain from a given object (impact analysis before refactoring)
MATCH path = (o:Object {object_id: 'PROC-.SP_TRANSFER_FUNDS'})-[:CALLS*1..5]->(downstream)
RETURN path;

## Tables with no declared foreign keys (orphaned or candidate for inferred-relationship review)
MATCH (t:Table) WHERE NOT (t)-[:REFERENCES]->() AND NOT ()-[:REFERENCES]->(t)
RETURN t.table;

## Rule sets by size
MATCH (rs:RuleSet)<-[:BELONGS_TO]-(r:BusinessRule)
RETURN rs.name, count(r) AS rule_count ORDER BY rule_count DESC;
"""
    (run_dir / "cypher_library.md").write_text(cypher_library, encoding="utf-8")

    readme = f"""# Neo4j import instructions — {args.system_name}

## Option A — Cypher script (recommended)
1. Open Neo4j Desktop and start your database.
2. Open Neo4j Browser, click the folder icon, select `import.cypher`.
3. Click Run. Verify with: `MATCH (n) RETURN labels(n)[0] AS type, count(n) AS count ORDER BY count DESC;`

## Option B — CSV import (large codebases)
Copy `nodes/*.csv` and `rels/*.csv` into your Neo4j import directory, then use `neo4j-admin database import`.

## First queries to run
See `cypher_library.md`.

## Note
This export is a read-only snapshot of the pipeline's JSON artifacts at generation time — it is not a
live, continuously-synced database. Re-run this agent and re-import to refresh it.
"""
    (run_dir / "README.md").write_text(readme, encoding="utf-8")

    node_counts = {"File": len(file_rows), "Object": len(object_rows), "Table": len(table_rows),
                    "BusinessRule": len(rule_rows), "RuleSet": len(rule_set_rows)}
    rel_counts = {"CONTAINS": len(contains_rows), "CALLS": len(calls_rows), "READS": len(reads_rows),
                   "WRITES": len(writes_rows), "REFERENCES": len(references_rows),
                   "BELONGS_TO": len(belongs_to_rows), "ENFORCED_IN": len(enforced_in_rows)}

    graph_artifact = {
        "pipeline_stage": "8_neo4j_graph", "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_counts": node_counts, "relationship_counts": rel_counts,
        "note": "Read-only export, not a live pipeline dependency. Re-run to refresh.",
    }
    (run_dir / "graph_artifact.json").write_text(json.dumps(graph_artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        (Path(args.output_root) / "latest.json").write_text(json.dumps(
            {"run_version": run_version, "path": f"{run_version}/graph_artifact.json",
             "updated_at": graph_artifact["generated_at"]}, indent=2), encoding="utf-8")

    print("=== Neo4j Graph Agent Complete ===")
    print(f"Output directory: {run_dir}")
    print("Nodes:")
    for k, v in node_counts.items():
        print(f"  {k:15}: {v}")
    print("Relationships:")
    for k, v in rel_counts.items():
        print(f"  {k:15}: {v}")
    print("\nNext step: see README.md for import instructions.")
    print("===================================")


if __name__ == "__main__":
    main()
