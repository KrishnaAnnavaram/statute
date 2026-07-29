---
name: 7_synthesis
description: >
  Seventh and final documentation agent. Assembles every upstream artifact into
  a Business Requirements Document written for four audiences at once — a
  business sponsor, a business analyst, a build team, and a machine. Translates
  every machine identifier into business language, states rules with SBVR
  modality (necessary vs obligatory) alongside plain English, publishes an exact
  requirements traceability matrix, documents interface contracts and
  transaction behaviour, and merges human annotations that survive regeneration.
  Emits brd.md, brd_index.json and gaps_register.json. Must run last.
tools: Read, Bash
---

# BRD synthesis agent

Thin wrapper over `.claude/scripts/07_synthesis.py` — deterministic, no LLM.
Business-language translation lives in `.claude/scripts/lib_business_language.py`.

## What changed and why

The predecessor produced a competent reverse-engineering report and titled it a
Business Requirements Document. Measured defects in that output:

| Defect | Evidence |
|---|---|
| Summarised the analysis, not the business | *"124 statements parsed"* opened the document |
| No scope statement | The word "scope" appeared **nowhere** |
| Identifiers in prose | *"PROC-.SP_TRANSFER_FUNDS is a procedure classified as SINGLE_RECORD_TRANSACTION"* |
| Findings discarded | A **high-severity** transaction hazard and all **20** interface parameters were computed and dropped |
| No traceability matrix | Despite every join being available and exact |
| No glossary, no navigation, no audience guidance | — |

## Document structure

Four parts, ordered by audience rather than by pipeline stage — documentation
needs are task-dependent (Aghajani et al., ICSE 2020).

| Part | For | Contains |
|---|---|---|
| **I — Business View** | Sponsors | Executive summary, scope (in *and* out), glossary, capability catalogue, data-flow figure, CRUD matrix |
| **II — Rules and Behaviour** | Analysts | Rules catalogue, entity lifecycles, error contracts |
| **III — Build Specification** | Developers | Data model with rebuild types, interface contracts, per-capability process specs, operational characteristics |
| **IV — Assurance** | Auditors, build leads | Traceability matrix, gaps register, rebuild checklist |

Plus Document Control with a sign-off block, a clickable contents page, and
three appendices (method, reference scheme, standards).

## Design notes worth preserving

- **One translation point.** `lib_business_language` converts every identifier;
  no chapter formats its own. The machine identifier is carried *alongside*
  prose, never substituted for it, so one sentence serves a sponsor and a
  builder while a machine can still recover the join key.
- **Dual presentation of every rule.** Plain terms ("From Balance is below
  Amount"), the exact source expression in a code span, and a formal statement.
  A specification only a developer can check is not reviewable.
- **SBVR modality, not uniform EARS.** A database constraint that is ENABLED and
  VALIDATED makes violation *impossible* → *"it is necessary that"*. A code
  guard exists precisely because violation is *possible* → *"it is obligatory
  that"*. We computed this distinction upstream and previously flattened it.
- **Verification method is derived.** Schema-enforced rules → Inspection.
  Code-enforced rules → Test. Two of 29148's eleven attributes are derivable;
  the rest (Owner, Priority) appear as **visible blanks**, because an empty
  column is an action item and a missing one is invisible.
- **Traceability is published because ours is exact.** IR-based traceability
  research reaches 19–32% precision on *inferred* links; ours are constructed
  from `statement_id`. This is the one place the pipeline categorically beats
  the state of the art, and it was previously unshipped.
- **Annotations survive regeneration.** `brd_annotations.json` is keyed by
  stable id and merged at synthesis time — never written by the pipeline.
  Machine facts regenerate; human meaning persists. Every commercial tool in
  this space ships a curation loop, because the domain knowledge that makes a
  rule *mean* something is not recoverable from code (Biggerstaff's concept
  assignment problem).
- **Provenance stripped from prose.** Upstream descriptions embed *"Implemented
  in PROC-.SP_A, line 33"*; that is already a labelled attribute beside the
  rule, so repeating it inside the sentence is noise as well as unreadable.
  (The original stripper used `[^.]*?`, which can never span an object id —
  object ids contain a period.)
- **Fenced blocks stay technical.** Pseudocode and diagrams are for the build
  team and must remain faithful to source; only the surrounding prose is held
  to the business-readability bar.
- **`NO` is not an abbreviation.** Expanding it turned "no preceding condition
  matched" into "Number Preceding Condition Matched". Ordinary English words
  must stay out of the abbreviation table.
- **Confidence is never hidden.** Low-confidence rules are included and visibly
  marked, never silently dropped.

## Honest limits, stated in the document itself

- The document is titled a **Business Requirements Document**. Note for accuracy:
  by BABOK's classification its contents are Solution/Functional requirements —
  they describe what the system does, not why the business wanted it. The scope
  chapter states this plainly so no reader is misled by the title.
- Chikofsky & Cross (1990) separate redocumentation from design recovery; each
  part declares which it is so a reader can calibrate trust.
- The document states plainly that no AI model wrote or judged any of its
  content, which is what makes every sentence traceable to a line number.

## Output

```
output/final_report/<run_version>/brd.md              <- the document
output/final_report/<run_version>/brd_index.json      <- same content, structured
output/final_report/<run_version>/gaps_register.json  <- open matters
output/final_report/latest.json
```

Optional input: `brd_annotations.json` in the working directory (path settable
via `--annotations`). Read only, never written.
