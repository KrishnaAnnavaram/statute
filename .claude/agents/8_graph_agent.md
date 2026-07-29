---
name: 8_neo4j_graph
description: >
  Eighth and optional agent. Turns every pipeline artifact into a queryable
  knowledge graph — 13 node labels including Column, Statement and Parameter,
  and 22 relationship types including column-level lineage and a control-flow
  layer. Exports MERGE-based Cypher plus per-label CSVs for Neo4j, and provides
  a deterministic plain-English question interface that works with or without
  Neo4j installed. Declares its own blind spots as queryable nodes. No other
  stage depends on it; the JSON artifacts remain the source of truth.
tools: Read, Bash
---

# Knowledge graph agent

Wrapper over `.claude/scripts/08_graph.py`, with the model in
`lib_graph_model.py` and the question interface in `lib_graph_language.py`.
Deterministic, no LLM.

## What changed

| | Before | After |
|---|---|---|
| Node labels | 5 | **13** |
| Relationship types | 7 | **22** |
| Upstream artifacts read | 4 of 7 | **7 of 7** |
| Column-level lineage | none | `READS_COLUMN` / `WRITES_COLUMN` at object *and* statement level |
| Rule provenance | to the procedure | **to the statement** (`IMPLEMENTED_AT`) |
| Query interface | none | 12 plain-English questions + Cypher |
| Output location | `output/final_report/graph/` | `output/graph/` |
| Tests | 13 | **56** |

## Design notes worth preserving

- **One model, two views.** `lib_graph_model` builds an in-memory property
  graph; the Cypher/CSV export and the question interface are both views over
  it. A locally-answered question and the same question in Neo4j cannot
  disagree, because they read the same structure.
- **Column and Statement are nodes, not properties.** Property-graph practice:
  a thing taking part in several independent relationships must be a node. A
  Column is read, written, constrained and indexed. Making it a property would
  make impact analysis — the reason to build a graph at all — unaskable.
- **A Code Property Graph layer** (Yamaguchi et al., IEEE S&P 2014). Agent 2's
  statement tree is an AST, its `control_flow_graph` is a CFG, and Agent 4's
  slices are dependence facts. Joining them answers questions none answers
  alone. Edges are typed (`FOLLOWS`, `BRANCHES_TO`, `ON_ERROR_REACHES`,
  `LOOPS_BACK_TO`, `DETERMINES`) so a traversal can tell flow from a decision
  from an error path.
- **Statement-level column edges.** "Which line writes this column" is a more
  useful answer than "which procedure". Parameter names appearing in a
  statement's `reads` list find no Column node and are dropped by the edge
  guard rather than inventing phantom columns.
- **Concepts and constraints, after jQAssistant.** The export ships derived-view
  Cypher (concepts) and validation Cypher that should return nothing
  (constraints), so an analyst extends the graph without touching the extractor.
- **The English layer never generates.** Questions match a named intent
  catalogue; each intent owns a resolver and the equivalent Cypher. An
  unmatched question is refused with the list of what *is* supported. Total
  precision, imperfect recall — the right trade when a wrong impact answer is
  worse than none. This is why the negative tests matter most in the suite.
- **Blind spots are nodes.** Dynamic SQL, external callers, unresolved calls
  and trigger side effects are exported as `BlindSpot` so the limits are
  queryable. The impact-analysis literature is unanimous that no automated
  approach is complete; a graph that looks authoritative is more dangerous than
  a document that looks uncertain. Treat it as a lower bound on dependencies.

## Usage

```bash
python .claude/scripts/08_graph.py                       # build the export
python .claude/scripts/08_graph.py --list-questions      # what it can answer
python .claude/scripts/08_graph.py --ask "what breaks if I change ACCOUNTS.BALANCE"
python .claude/scripts/08_graph.py --ask "..." --json    # machine-readable
```

## Output

```
output/graph/<run_version>/import.cypher        <- MERGE-based, idempotent
output/graph/<run_version>/nodes/*.csv          <- one file per label
output/graph/<run_version>/rels/*.csv           <- one file per relationship type
output/graph/<run_version>/README.md            <- load guide, cookbook, blind spots
output/graph/<run_version>/graph_artifact.json
output/graph/latest.json
```
