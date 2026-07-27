---
name: 6_diagram
description: >
  Sixth agent in the PL/SQL reverse engineering pipeline. Translates
  existing structured data into Mermaid diagrams — a component diagram
  from Agent 2's resolved CALL edges, and a per-object process-flow
  diagram from Agent 2's control_flow_graph. Does not extract or interpret
  anything new. The ERD is Agent 3's responsibility (it owns the entity
  model), not this agent's. Must run after 5_rules, before 7_synthesis.
tools: Read, Bash
---

# Diagram agent

Thin wrapper over `.claude/scripts/06_diagram.py` — deterministic, no LLM.

## Two real bugs found by inspecting rendered output (not by code review)

1. Agent 2's `build_cfg` only ever linked **siblings** to each other. A
   decision (`IF`) node had no edge into any of its branches — only a
   fallthrough edge to whatever follows the whole `IF/ELSIF/ELSE`. A
   rendered diagram would show the decision skipping straight past all
   three branches, which is actively misleading. Fixed by adding
   `BRANCH_ENTRY` edges from a parent to the first statement of each of
   its branch groups (grouped by `scope_path` suffix), labeled
   `true`/`elsif`/`false`/`loop body`/etc.
2. Mermaid node IDs derived directly from `statement_id` can start with a
   digit (`"02_SIMPLE_..."`), which is unreliable across renderers. Every
   node id in this agent is prefixed `N_` to guarantee validity regardless
   of source content.

Also: `RAISE_APPLICATION_ERROR` (a standard Oracle builtin, called bare/
unqualified) was being drawn as an "external/unresolved" node. Fixed at
the source in Agent 2 (`_ORACLE_BUILTIN_PROCEDURES` allowlist) rather than
papered over here — a diagram consumer shouldn't have to know which calls
are "really" fine.

## Output

```
output/diagram/<run_version>/
  diagrams/component_overview.mmd
  diagrams/flow_{OBJECT_ID}.mmd
  diagrams_artifact.json
```
