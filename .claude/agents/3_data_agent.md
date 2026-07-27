---
name: 3_data
description: >
  Third agent in the PL/SQL reverse engineering pipeline. Parses every DDL
  file Agent 2 routed as pass-through (schema_ddl/seed_data) using the
  same vendored ANTLR grammar, extracting a full per-table data
  dictionary: columns, types, defaults (literal vs. function_call),
  PK/FK/CHECK/UNIQUE constraints, and sequences. Closes the loop back to
  Agent 2: resolves every %TYPE/%ROWTYPE reference, cross-validates every
  table/column Agent 2 recorded a statement touching, and assigns each
  column a PySpark target type. CHECK constraints are promoted directly to
  candidate business rules; undocumented enums (comment-only, no CHECK)
  are mined from source comments and flagged for SME review. Also
  generates the ERD (entity-relationship diagram, Mermaid) — this agent
  owns the entity model, so the ERD is produced here, not by the Diagram
  Agent. Must run after 2_parser, before 4_logic/5_rules/6_diagram.
tools: Read, Bash
---

# Data agent

Thin wrapper over `.claude/scripts/03_data.py` — deterministic, no LLM,
same ANTLR grammar Agent 2 already vendored (different grammar entry
points: `create_table`, `create_sequence`, not the procedural rules).

## Design references (see `design_references` in the output artifact)

- Declared vs. naming-convention-inferred foreign keys are never merged
  into one confidence bucket — naming-convention FK detection has a real,
  studied false-positive rate (Jiang & Naumann, HPI).
- CHECK constraints are near-certain business rule signal, promoted
  without SME review — the same status this project's own
  `reference/.claude/skills/condition-classifier` gives COBOL 88-level
  conditions, for the identical reason: enforced by the source, not
  inferred from procedural logic.
- DDL extraction scope (tables w/ PK/UK/FK/CHECK, sequences, views,
  indexes, synonyms) matches Ora2Pg's documented scope — the most mature
  production Oracle-schema-extraction tool.
- Oracle `DATE` maps to Spark `TimestampType` (never narrowed to
  `DateType` — Oracle `DATE` always carries a time component, a documented
  migration gotcha); `NUMBER(p,s>0)` maps to `DecimalType(p,s)` — Apache
  Spark's JDBC `OracleDialect`.

## Real bugs this agent's testing surfaced (in itself and in Agent 2)

- **In Agent 2**: `SELECT ... INTO host_vars FROM ...` is a PL/SQL-only
  extension sqlglot doesn't understand — it was leaking `INTO` target
  variables into the `reads` column list, and the bug that caused it
  (`Into_clauseContext` sitting several ANTLR-tree levels below
  `Select_statementContext`, invisible to a direct-children-only search)
  also silently downgraded `SELECT_INTO` to plain `SELECT`.
- **In this agent**: cross-validation initially checked a statement's
  columns against each of its referenced tables *independently* — a
  column genuinely belonging to table B (e.g. an `INSERT` with a
  sub-`SELECT`) got misreported as unknown while being checked against
  table A. Fixed to check against the union of all tables the statement
  actually touches.
- Both fixes took real unknown-table/unknown-column counts on the actual
  `src/` codebase from 2/14 down to 0/0 — verified by rerunning, not
  assumed.

## Known, deliberate scope boundary

Views, indexes, and synonyms are parsed alongside tables/sequences in the
same DDL files and are confirmed (by test) to be safely ignored rather
than mis-parsed as tables — but they are not yet extracted into the data
dictionary. Extracting view definitions is the natural next increment.

## Output

```
output/data/<run_version>/
  data_artifact.json   <- tables, sequences, inferred_relationships,
                          type_reference_resolutions, sequence_usages, issues
  erd.mmd              <- Mermaid ERD
  run_meta.json        <- upstream: inventory_run_version, parser_run_version
output/data/latest.json
```

## Downstream consumers

| Agent | What they consume |
|---|---|
| `4_logic` | table/column names for pseudocode rendering |
| `5_rules` | `check_constraints` (promotable_to_rule), comment-only enums |
| `6_diagram` | (none directly — this agent already produces its own ERD) |
| `7_synthesis` | full data dictionary for the BRD's Data Model chapter |
