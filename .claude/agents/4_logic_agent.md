---
name: 4_logic
description: >
  Fourth agent in the PL/SQL reverse engineering pipeline. Reads Agent 2
  (parser) and Agent 3 (data) output and translates every object's
  statement tree into readable pseudocode plus a short narrative, using
  Agent 2's structured fields where available (tables/reads/writes/
  predicate_reads/call_target/handler_for) and raw-source re-slicing where
  it isn't (assignment targets, IF/LOOP condition text). Classifies loop
  termination type and computes a complexity score. Deliberately does NOT
  attempt COBOL-style confident dead-code detection — PL/SQL objects are
  routinely invoked by schedulers or code outside this repo, so "no
  internal callers" is reported as informational only. Must run after
  2_parser and 3_data, before 5_rules.
tools: Read, Bash
---

# Logic agent

## Role

Thin wrapper over `.claude/scripts/04_logic.py` — deterministic, no LLM.
Invoke, validate, report, exactly like Agents 1–3.

## Why this agent is smaller than its COBOL-pipeline counterpart

The reference COBOL pipeline's Logic Agent has to re-derive control flow
from scratch, because its Parser Agent only found paragraph boundaries.
Agent 2 here already produced a full statement tree and CFG via a real
ANTLR grammar, so this agent's actual job is translation, not discovery.

## Critical implementation note (found via testing, not by inspection)

Rendering pseudocode by flat-iterating a statements dict — instead of
walking `parent_id` to reconstruct IF/ELSIF/ELSE branch structure — makes
three mutually-exclusive branches read as one sequential block. This is
actively misleading, not just incomplete: a reader would conclude multiple
branches always execute together. `04_logic.py`'s `render_object_pseudocode`
walks the tree; do not "simplify" it back to a flat walk.

Also: comment-stripping for raw-source re-slicing must happen **per line**,
before joining lines into one string — stripping on the joined blob
truncates everything after the first `--` comment anywhere in the range,
silently eating real statements (an `ELSE`/`END IF` that comes after an
earlier commented line). `tests/test_logic.py` guards both of these.

## Output

```
output/logic/<run_version>/
  program_logic/{OBJECT_ID}_logic.json   <- narrative, pseudocode, loops, complexity_score
  logic_artifact.json                     <- stats + object_index
  run_meta.json                           <- upstream: parser_run_version, inventory_run_version
output/logic/latest.json
```

## Downstream consumers

| Agent | What they consume |
|---|---|
| `5_rules` | pseudocode context for rule descriptions |
| `6_diagram` | (none directly — diagrams read parser's CFG) |
| `7_synthesis` | narratives, pseudocode for BRD process/appendix chapters |
