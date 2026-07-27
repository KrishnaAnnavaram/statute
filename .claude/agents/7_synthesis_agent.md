---
name: 7_synthesis
description: >
  Seventh and final documentation agent in the PL/SQL reverse engineering
  pipeline. Reads all prior artifacts, runs a gap-detection pass across
  every one of them, then assembles brd.md. Every business rule gets a
  formal EARS-syntax statement alongside its plain-English description.
  Must run last.
tools: Read, Bash
---

# Synthesis agent

Thin wrapper over `.claude/scripts/07_synthesis.py` — deterministic, no LLM.

## BRD-authoring standards this agent is built on (researched, not assumed)

- **Chapter structure**: adapted from `reference/.claude/skills/section-assembler/SKILL.md`
  — proven for exactly this reverse-engineering-to-BRD scenario.
- **EARS syntax** (`IF <condition>, THEN the system SHALL <response>`) —
  developed at Rolls-Royce, the industry-standard technique for writing
  unambiguous, testable requirement statements. Every business rule gets
  one, alongside its plain-English description — never instead of it.
- **Requirement quality bar**: atomic / unambiguous / testable / traceable
  / complete / consistent — IIBA BABOK v3 + ISO/IEC/IEEE 29148.
- **Confidence is never hidden.** Low-confidence rules are included in the
  BRD, always visibly marked (⚠), never silently dropped.

## Real bug found and fixed during testing (not hypothetical)

The Object Inventory table (Chapter 2.1) initially had empty Type and
Complexity columns — the data existed in Agent 2's `raw_structure` files
and Agent 4's `program_logic` records, it just wasn't being read into the
table. Fixed by threading `parser_root`/`logic_dir` into `write_brd` and
reading both per object.

Also (in `05_rules.py`, surfaced by inspecting this agent's actual BRD
output): a null/negative guard clause like `p_annual_rate IS NULL OR
p_annual_rate < 0` was misclassified as `CALCULATION` because the field
name matched a calculation keyword — a NULL_CHECK anywhere in a condition
now always forces `VALIDATION`, regardless of field name or whether it's
combined with other guards via `OR`.

## Output

```
output/final_report/<run_version>/
  brd.md               <- primary deliverable
  gaps_register.json
run output tests confirm: every BR-xxx id referenced in brd.md exists in
rules_artifact.json — no invented content.
```
