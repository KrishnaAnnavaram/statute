---
name: 6_diagram
description: >
  Sixth agent in the PL/SQL reverse engineering pipeline. Produces the BRD's
  visual layer: a system data-flow map (programs x tables with C/R/U/D edges),
  a per-object process flow whose decisions are labelled with the business rule
  they enact, an entity state model derived from CHECK constraints and the
  UPDATEs that write them, and a CRUD matrix. Agent 3's ERD is indexed, not
  regenerated. Builds a renderer-agnostic DiagramSpec, applies a hard node
  budget, then renders Mermaid; nothing is truncated silently. Must run after
  2_parser, 3_data, 4_logic and 5_rules; before 7_synthesis.
tools: Read, Bash
---

# Visual model agent

Thin wrapper over `.claude/scripts/06_diagram.py` — deterministic, no LLM.

## Architecture

```
LOAD -> RESOLVE -> MODEL -> REDUCE -> ORDER -> RENDER -> VALIDATE -> WRITE
```

Everything up to ORDER is renderer-agnostic; RENDER is the only Mermaid-aware
code. This is the decision that makes everything else possible — the
predecessor formatted Mermaid strings inline while walking the CFG, so there
was nothing to count (the documented `--max-nodes` budget was declared and
never read), nothing but strings to assert on, and no way to change renderer.
Tests assert against `DiagramSpec`, not against formatted text.

## What it draws

| # | Diagram | Built from |
|---|---|---|
| D1 | ERD | **Agent 3** — indexed here, never regenerated |
| D2 | System data-flow map | Agent 4 CRUD matrix + Agent 2 calls + Agent 5 rule counts + Agent 4 complexity/shape |
| D3 | Process flow (per object) | Agent 2 CFG ⋈ Agent 5 rules on `statement_id` |
| D4 | Entity state model | Agent 3 CHECK `IN`-list + UPDATEs writing that column |
| D5 | CRUD matrix (markdown) | Agent 4 `crud_matrix` |

## Design notes worth preserving

- **The overview draws data, not calls.** The predecessor drew a call graph. On
  a codebase with no internal calls that is five disconnected boxes — measured
  here as 5 nodes, **0 edges**. Joining the CRUD matrix makes it answer the
  question a stakeholder actually asks.
- **Labels come from a strict ladder**: tier 1 Agent 5 rule text → tier 2 Agent 2
  structured fields → tier 3 `Type (line N)`. Tier-1 coverage on decisions is a
  published quality gate, not an implementation detail. Agent 2 stores only
  `nesting_depth` on an `IF`, so without Agent 5 there is no way to label a
  decision meaningfully — this dependency is load-bearing, not decorative.
- **A rule anchored at a statement may describe the branch starting there, not
  the statement.** Only a decision may take its label from a rule; otherwise an
  UPDATE that opens an ELSIF branch renders as a data store bearing the ELSIF's
  condition — wrong shape and wrong meaning at once. Branch rules go on the edge.
- **A decision's rule is not always on the decision's line.** Agent 5 merges a
  guarded `RAISE` into the `IF` that guards it but records the RAISE's line, so
  the lookup searches the statement's whole span.
- **Handler dispatch and loop entry are not decision branches.** The CFG calls
  them `BRANCH_ENTRY` too, but `WHEN E_INSUFFICIENT_BALANCE` is already fully
  informative and Agent 5 anchors that rule at the RAISE site by design. They
  are typed apart so the traceability metric measures the right thing rather
  than penalising correct behaviour.
- **Collapse has exactly one tier, deliberately.** Contiguous runs of
  straight-line statements merge into one node. An earlier second tier merged
  every collapsible child of a parent regardless of adjacency, fusing lines 33
  and 124 into one node and implying they run together — the diagram met its
  budget by misrepresenting the flow. Once contiguous runs are merged, shrinking
  further means deleting decisions or error paths, which the invariant forbids.
- **Never collapsed:** decisions, loops, error paths, terminals. Structure wins
  over the budget; the excess is **declared** (`oversize`) and reaches the BRD's
  gaps register. Silent truncation would be worse than a large diagram.
- **The state model is the only place this agent derives new knowledge**, so it
  carries the strictest evidence bar: a transition whose target cannot be read
  from source is dropped; one whose origin cannot be determined is drawn from
  the entry point and marked inferred. A fabricated state edge in a BRD is worse
  than no state diagram, because a reviewer cannot tell it is wrong. States that
  no code transitions into are reported as a note.
- **Nodes are emitted in source order** — Mermaid's layered layout depends on
  input order, so this is free quality (VEIL, 2025).
- **Short node ids** (`N1`, `N2`) with real statement ids kept in the artifact.
  The predecessor used ~110-character ids repeated twice per edge.
- **Validation fails the stage.** Undeclared budget overruns, edges to undeclared
  nodes, leaked internal identifiers (`STMT_`, `NESTED_BLOCK#`, `IF#`) and
  unbalanced quotes are errors, not warnings.

## Quality gates (enforced by tests/test_diagram.py)

| Metric | Gate | Current |
|---|---|---|
| Decision nodes with tier-1 labels | ≥ 90% | 100% |
| Decision branches carrying a BR-id | ≥ 80% | 100% |
| Tier-3 fallback labels | < 15% of nodes | 1/128 |
| Leaked internal identifiers | 0 | 0 |
| Budget | enforced or declared | declared once |

The field's own systematic reviews note that most reverse-engineering
visualization tools are never evaluated at all. These gates exist so this one
is not another of them.

## Output

```
output/diagram/<run_version>/diagrams_artifact.json   <- diagram_index, crud_matrix, quality, warnings
output/diagram/<run_version>/diagrams/*.mmd
output/diagram/latest.json
```

`warnings` (OVERSIZE, DETAIL_COLLAPSED, DIAGRAM_NOTE) flow into Agent 7's gaps
register so anything a diagram hid or could not fit reaches the reader.
