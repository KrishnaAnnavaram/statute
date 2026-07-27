---
name: 5_rules
description: >
  Fifth agent in the PL/SQL reverse engineering pipeline. Mines business
  rules from three sources: IF/ELSIF conditions and named EXCEPTION_HANDLERs
  (Agent 2), and CHECK constraints already flagged promotable_to_rule
  (Agent 3). Classifies each into a category (Validation/Calculation/
  Routing/Limit-check/Error-handling/Compliance), scores confidence,
  generates a name/description, deduplicates, and groups into rule sets.
  Must run after 3_data (and 4_logic, for pseudocode context), before
  6_diagram/7_synthesis.
tools: Read, Bash
---

# Rules agent

Thin wrapper over `.claude/scripts/05_rules.py` — deterministic, no LLM.

## Design notes worth preserving

- CHECK constraints and named business exceptions (e.g. `E_INSUFFICIENT_BALANCE`)
  are scored `confirmed` without SME review — they're enforced/named by the
  source, not inferred. Generic `WHEN OTHERS` handlers are explicitly
  excluded from business rules (routed to `error_handling_catalogue`
  instead) — they're plumbing, not a business signal.
- `classify_pattern` checks for `AND`/`OR` **before** single-clause patterns
  — a compound condition must never get miscategorized as a simple literal
  comparison just because one sub-clause happens to match that shape too.
- `business_name` resolves dotted record-field access (`rec.balance`, from
  a cursor `FOR` loop) to the field after the dot. The loop variable itself
  (`rec`) carries no business meaning — a rule named "Enforce Rec" is worse
  than useless. This was a real bug caught by testing, not a hypothetical.
- Every rule must trace to a real `statement_id` or DDL constraint name —
  never invent a rule with no source.

## Output

```
output/rules/<run_version>/rules_artifact.json   <- rule_sets, business_rules, error_handling_catalogue
output/rules/latest.json
```
