---
name: 8_neo4j_graph
description: >
  Eighth and optional agent. Reads all prior artifacts and generates Neo4j
  import files (Cypher script + CSVs) that the user loads into Neo4j
  Desktop themselves. No database connection, no Python driver. Uses
  MERGE (never CREATE) so it is safe to re-run. Deliberately NOT wired as
  a dependency of any other agent — the JSON artifacts remain the
  pipeline's single source of truth end to end; this is an on-demand,
  read-only export for interactive graph exploration, not infrastructure.
tools: Read, Bash
---

# Neo4j graph agent

Thin wrapper over `.claude/scripts/08_graph.py` — deterministic, no LLM.

## Why this stays optional and terminal (a real decision, not a default)

Current 2026 tooling (e.g. Thoughtworks CodeConcise) treats a knowledge
graph as central, early-built infrastructure other analysis stages query.
That pattern earns its cost at genuine enterprise scale (hundreds+ of
programs). At this project's actual scale, the JSON artifacts already
carry full traceability (`statement_id` → `parent_id` → `object_id` →
resolved `call_target_object_id`), and introducing a live database
dependency into every agent from 3 onward would break the "run the
script, get the same output, no service required" guarantee the whole
pipeline is built on. Revisit this decision only if the real target
codebase turns out to be large — not before.

## Real bug found by reading actual output, not by code review

`business_rules.csv`'s `rule_set_id` column was empty for every single
row — `rule_rows` was built **before** the loop that actually assigns
`rule_set_id` onto each rule record. `tests/test_graph.py` asserts every
row has a non-empty, real `rule_set_id` as a permanent regression guard.

## Output

```
output/final_report/graph/<run_version>/
  import.cypher            <- run in Neo4j Browser
  cypher_library.md        <- ready-to-run analytical queries
  README.md                <- import instructions
  nodes/*.csv, rels/*.csv  <- for neo4j-admin bulk import
  graph_artifact.json
```
