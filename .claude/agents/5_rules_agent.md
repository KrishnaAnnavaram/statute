---
name: 5_rules
description: >
  Fifth agent in the PL/SQL reverse engineering pipeline. Mines business rules
  from nine sources spanning Agent 2 (branch conditions, CASE expressions,
  cursor WHERE clauses, RAISE sites, exception handlers), Agent 3 (CHECK
  constraints, virtual columns, unique constraints/indexes, view filters), and
  Agent 4 (backward variable slices). Restates exceptions as positive
  obligations per SBVR, classifies each rule into a category
  (Validation/Calculation/Routing/Limit-check/Error-handling/Compliance),
  derives confidence from real enforcement state, names each rule so it is
  distinguishable from its siblings, deduplicates, and groups into rule sets.
  Must run after 3_data and 4_logic (whose slices it consumes), before
  6_diagram/7_synthesis.
tools: Read, Bash
---

# Rules agent

Thin wrapper over `.claude/scripts/05_rules.py` — deterministic, no LLM.

## Where rules come from

| Source kind | Origin | What it captures |
|---|---|---|
| `conditional_branch` | Agent 2 | Each IF / ELSIF / ELSE branch — one business outcome per branch |
| `case_branch` | Agent 2 | Each WHEN / ELSE of a CASE expression |
| `cursor_eligibility` | Agent 2 | A cursor's WHERE clause — *which* records the process applies to |
| `named_exception` | Agent 2 | A guarded RAISE, restated as the obligation it enforces |
| `predefined_exception` | Agent 2 | An Oracle predefined exception the database detected |
| `failure_isolation` | Agent 2 | Per-record failure logged and skipped — a resilience requirement |
| `error_contract` | Agent 2 | `WHEN OTHERS` raising a specific application error callers depend on |
| `variable_derivation` | Agent 4 | Business formulas, from backward slices |
| `ddl_*` | Agent 3 | CHECK constraints, virtual columns, unique constraints/indexes, view filters |

## Design notes worth preserving

- **Exceptions are restated as obligations.** SBVR is explicit that an
  exception is not itself a business rule: *"there are no exceptions; instead,
  there are well stated business rules."* A guarded `RAISE` merges with the IF
  that guards it (same `raw_key`) and is phrased as what must hold, not as
  what is raised. The IF condition is the **violation**, so the qualifier in
  the rule name is inverted (`p_amount <= 0` → "Validate Amount above 0").
- **Every branch is a rule.** Emitting only the leading IF cost 2 of 5 rules on
  the dormant-account procedure; leaving a CASE whole cost 6 of 10 on the
  minimum-balance one. Both were caught by ground-truth measurement, not review.
- **`WHEN OTHERS` is three different things.** Logging a per-row failure and
  continuing is a resilience requirement; re-raising a specific application
  error is a contract callers depend on; a bare rollback-and-reraise is
  plumbing and is routed to `error_handling_catalogue`, not the BRD.
- **Confidence comes from enforcement state, not from existence.** A DISABLED
  constraint is still surfaced (hiding it would lose documented intent) but is
  scored `low` and flagged for SME review, and its EARS statement says plainly
  that the database is not enforcing it. `ENABLE NOVALIDATE` is never
  `confirmed` — existing rows may violate it.
- **Slices include transitive dependencies.** A derivation rule is emitted only
  when the deriving statement actually *assigns* the slice variable; without
  that check `v_new_balance` claimed the formula that computes
  `v_interest_amount`, duplicating one rule under two names.
- **Names must distinguish siblings.** Subject and qualifier are derived from
  the *same* comparison, or they disagree ("Calculate Amount at or above
  Amount"). In a compound condition only an equality against a literal is used
  as a qualifier — an inequality implies the whole rule is that one threshold
  and silently drops the rest.
- **`business_name` resolves dotted record-field access** (`rec.balance`, from
  a cursor `FOR` loop) to the field after the dot. A rule named "Enforce Rec"
  is worse than useless. A real bug caught by testing.
- **The developer's own words win.** A `RAISE_APPLICATION_ERROR` message
  ("Principal amount must be greater than zero") is the clearest statement of
  a rule anywhere in the source and is carried through verbatim.
- **Every rule traces to a real `statement_id` or DDL constraint name.** Never
  invent a rule with no source.

## Measurement

`tests/evaluate_rules.py` scores extraction against hand-annotated ground truth
in `tests/fixtures/ground_truth/`, matching on source-line proximity rather
than phrasing. Two of the four annotated procedures were annotated *blind* —
without running the extractor — because a suite tuned and measured on the same
procedures proves nothing about generalisation.

## Output

```
output/rules/<run_version>/rules_artifact.json   <- rule_sets, business_rules, error_handling_catalogue
output/rules/latest.json
```
