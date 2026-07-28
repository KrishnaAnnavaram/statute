---
name: 3_data
description: >
  Third agent in the PL/SQL reverse engineering pipeline. Parses every DDL
  file using the same vendored ANTLR grammar as Agent 2 and builds the
  complete physical data dictionary: tables, columns (incl. virtual/computed
  and IDENTITY), constraints WITH their real Oracle enforcement state
  (ENABLED/DISABLED, VALIDATED/NOT VALIDATED), ON DELETE actions, views,
  indexes, sequences, synonyms, partitioning, global temporary tables, and
  COMMENT ON documentation. Closes the loop back to Agent 2: resolves
  %TYPE/%ROWTYPE, cross-validates every table/column reference (resolving
  synonyms and views), and tracks column usage. Harvests business-rule
  candidates from four DDL sources with honest confidence, and generates the
  ERD. Must run after 2_parser, before 4_logic/5_rules/6_diagram.
tools: Read, Bash
---

# Data agent

Thin wrapper over `.claude/scripts/03_data.py` — deterministic, no LLM. Uses
the same ANTLR grammar Agent 2 vendored, just different entry rules
(`create_table`, `create_view`, `create_index`, `create_sequence`,
`create_synonym`, `comment_on_*`).

Artifact `schema_version: 2.0`.

## The correctness principle this agent is built around

**A constraint existing in the DDL does not mean the database is enforcing
it.** Oracle tracks `STATUS` (ENABLED/DISABLED) and `VALIDATED` independently,
and legacy schemas routinely leave constraints DISABLEd after a bulk load or
migration that nobody reverted. This agent parses that state and propagates it:

| Enforcement state | `is_enforced` | Rule confidence | In the BRD |
|---|---|---|---|
| `ENABLE VALIDATE` (Oracle default) | true | `confirmed` | stated as a guarantee |
| `ENABLE NOVALIDATE` | true | `high` + SME review | enforced for new rows only |
| `DISABLE` | **false** | `low` + SME review | "INTENDED to ensure… but NOT enforced", raised as a **high-severity gap** |

A DISABLED constraint is never dropped (that would hide documented business
intent) and never presented as an active rule (that would be a false
statement about the system). This flows end-to-end into `brd.md`.

## Extraction scope

Tables (+ global temporary, + partitioning strategy/keys), columns (+ virtual
column formulas, + IDENTITY generation, + literal-vs-function defaults, + enum
values), all four constraint kinds with enforcement state and `ON DELETE`
action, views (+ their filter predicate — often *the* business rule), indexes
(a UNIQUE index is a de facto rule even with no UNIQUE constraint), sequences
(full metadata incl. max/min/cycle/cache), synonyms, and `COMMENT ON`
table/column documentation.

## Two real bugs this redesign surfaced (both found by running, not reading)

1. **Routing bug, pipeline-wide.** A schema file containing a `CREATE VIEW`
   necessarily contains a `SELECT`, which makes Agent 1 classify the whole
   file `mixed` — and `mixed` was routed only to Agent 2. Every table in such
   a file was invisible to this agent. Routing is now **content-driven**
   (`DDL_CONTENT_HINTS`), not role-driven. Agent 2 and Agent 3 extract
   disjoint constructs and may both read the same file.
2. **ANTLR `getText()` destroys whitespace.** It returns
   `SELECTid,statusFROMprobe_t`, which sqlglot cannot parse — so view filter
   predicates silently came back empty. `original_text_of()` slices the token
   stream instead (whitespace is on the hidden channel, not discarded), the
   same technique `02_parser.py` uses for DML.

## Necessary companion changes in other agents

- **Agent 5** consumes the new unified `ddl_rule_candidates` feed (five source
  kinds) and maps enforcement state to rule confidence. Without this a
  disabled constraint would silently vanish rather than surface as a gap.
- **Agent 7** maps `constraint_not_enforced` → high-severity gap, renders
  rule provenance generically (`format_rule_source`), and never writes an
  unconditional "SHALL" for an unenforced constraint.

## Output

```
output/data/<run_version>/
  data_artifact.json   <- tables, views, indexes, synonyms, sequences,
                          column_catalogue (flat, with used_by_objects),
                          ddl_rule_candidates, inferred_relationships,
                          type_reference_resolutions, sequence_usages, issues
  erd.mmd              <- Mermaid ERD (ON DELETE annotated, inferred rels dashed)
  run_meta.json        <- upstream: inventory_run_version, parser_run_version
output/data/latest.json
```

## Known remaining scope boundary

Materialized views are not yet extracted (plain views are). Index-organized
tables, clusters, and object/XMLType tables are recognized by the grammar but
their table-level structure is not modeled.
