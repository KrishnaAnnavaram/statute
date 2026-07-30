# Known Gaps and Open Questions

Two kinds of entry: **gaps** — verified absences or defects found in the repository — and **open questions** — things the repository cannot answer, requiring stakeholder input.

## Contents

- [1. Implementation gaps found while documenting](#1-implementation-gaps-found-while-documenting)
- [2. Operational and engineering gaps](#2-operational-and-engineering-gaps)
- [3. Evaluation gaps](#3-evaluation-gaps)
- [4. Security gaps](#4-security-gaps)
- [5. Open questions requiring stakeholder confirmation](#5-open-questions-requiring-stakeholder-confirmation)
- [6. Prioritised recommendations](#6-prioritised-recommendations)

---

## 1. Implementation gaps found while documenting

### GAP-D01 — `TRANSITIONS_TO` graph edges are never emitted

**Severity: medium** · `Confirmed from implementation.`

Agent 06 derives entity state transitions with guards and rule IDs, and publishes them in the BRD. Agent 08 creates `State` nodes and `HAS_STATE` edges, but the loop that would derive transition edges contains only a `pass`:

```python
# lib_graph_model.py
for f, meta in (diagrams.get("diagram_index") or {}).items():
    if meta.get("type") != "state":
        continue
    # Transitions are re-derived from the diagram's own record so the graph
    # and the BRD agree on the lifecycle.
    for note in meta.get("notes", []) or []:
        pass  # notes surface as BlindSpot/Gap rather than edges
```

**Verified in the live artefact:** `State` nodes = 3, `HAS_STATE` = 3, `TRANSITIONS_TO` = **absent**.

**Impact.** A computed finding is discarded. The lifecycle is queryable in the BRD but not in the graph. The comment describes behaviour that is not implemented.

### GAP-D02 — Condition text is re-derived three times

**Severity: low (technical debt)** · `Confirmed from implementation.`

Agent 02 stores no condition text on `IF`/`CASE` records — only `nesting_depth`. Agents 04, 05 and 06 each independently re-read the original `.sql` file and re-slice the condition, with their own `source_lines`/`raw_snippet` implementations.

**Impact.** Three implementations of one idea; three places to fix a slicing bug; the original source must remain available at its recorded `abs_path` for three later stages.

### GAP-D03 — Dangling graph edges are dropped silently

**Severity: low** · `Confirmed from implementation.`

`Graph.rel()` refuses to create an edge whose endpoints are absent. This is correct — it prevents phantom columns from Agent 02's `reads[]`, which mixes columns and parameters — but **no count is reported**, so genuine data loss would be invisible.

### GAP-D04 — `reads[]` mixes columns and parameters

**Severity: low** · `Confirmed from implementation` — live artefact shows `p_from_account` inside a `SELECT_INTO` `reads[]` list. Every consumer must filter; only Agent 08 does so structurally.

---

## 2. Operational and engineering gaps

### GAP-O01 — No dependency manifest

**Severity: high** · `Confirmed from configuration.`

No `requirements.txt`, `pyproject.toml`, `Pipfile`, `setup.py` or lockfile exists. Two third-party runtime dependencies (`antlr4-python3-runtime`, `sqlglot`) must be installed from knowledge. **No version is pinned or recorded anywhere.**

**Impact.** A fresh clone cannot be reliably set up. A breaking upstream release cannot be diagnosed by comparing versions. This is the single largest operational risk in the repository.

### GAP-O02 — No CI/CD

**Severity: medium** · No `.github/workflows` or any pipeline definition. 414 tests exist and run only when a human runs them.

### GAP-O03 — No containerisation

**Severity: low** · No Dockerfile. Environment reproducibility depends on the operator's local Python.

### GAP-O04 — No logging framework

**Severity: medium** · Zero uses of `logging`. All diagnostics are `print()` to stdout/stderr. No levels, no structured fields, no correlation ID beyond `run_version`, no export.

### GAP-O05 — Unbounded run-directory growth

**Severity: low** · Nothing prunes `output/`. Observed: 17 `final_report` runs from a single development session. Compounded by the risk of an operator opening a stale run — which has occurred.

### GAP-O06 — No concurrency control

**Severity: low** · Two concurrent runs of the same stage produce two directories; the last `latest.json` write wins. No locking.

### GAP-O07 — No formal artefact schemas

**Severity: medium** · Artefacts declare `schema_version` but no JSON Schema exists. Shape is enforced only by tests and by defensive `.get()` reads in consumers.

---

## 3. Evaluation gaps

### GAP-E01 — Rule-extraction F1 is contaminated

**Severity: high** · `Confirmed from existing documentation.`

Ground truth covers 4 of the corpus's 5 procedures, and each was eventually used to fix the extractor. The reported 1.000 is not a generalisation estimate. The defensible figures are the two blind measurements: **F1 0.588** and **recall 0.400**.

### GAP-E02 — Seven of eight agents have no evaluation

**Severity: medium** · Only Agent 05 has a harness. There is no measured accuracy for file classification, parsing, schema recovery, complexity computation, diagram usefulness, document usefulness or question recall.

**Highest-value missing evaluation:** file-role classification (Agent 01). A misclassification silently removes a file from the data model — a defect that has already occurred.

### GAP-E03 — Quality gates measure completeness, not usefulness

**Severity: medium** · Agents 06 and 07 publish coverage gates (label coverage, traceability percentage, vacuous-statement count). The repository itself notes that no automated documentation metric correlates meaningfully with expert judgement.

### GAP-E04 — Single-domain corpus

**Severity: high** · 5 objects, 15 tables, one banking schema. Agent 05's `CATEGORY_FIELD_SIGNALS` is banking vocabulary. The system has never been run against foreign PL/SQL.

---

## 4. Security gaps

### GAP-S01 — Annotation content is not sanitised

**Severity: medium** · `Confirmed from implementation.` `brd_annotations.json` text is inserted into `brd.md` verbatim. Arbitrary markdown — including links and HTML that markdown renderers accept — can be injected by whoever edits the file.

### GAP-S02 — Highly sensitive output with no classification mechanism

**Severity: medium** · `brd.md` and the graph export contain the complete business logic, schema, interface contracts and error contracts. No classification marking, redaction option or access control exists.

### GAP-S03 — Local paths embedded in artefacts

**Severity: low** · `abs_path` in `file_metadata` exposes local directory structure in a shareable artefact.

### GAP-S04 — Cypher escaping unaudited

**Severity: low** · `cypher_value` escapes `\`, `"` and newlines. No injection audit against adversarial schema or identifier names was found.

### GAP-S05 — No threat model

**Severity: low** · `Not found in the current repository.` No threat model or security review document exists.

---

## 5. Open questions requiring stakeholder confirmation

| # | Question | Why it cannot be answered from the repository |
|---|---|---|
| Q1 | Why does Agent 02 not store condition text? | No rationale recorded; three agents re-derive it |
| Q2 | Why is `TRANSITIONS_TO` unimplemented? | The loop exists with a `pass` and a comment describing behaviour that is absent |
| Q3 | What Python version and dependency versions are supported? | 3.11+ inferred from syntax only; no manifest |
| Q4 | Are complexity thresholds (10, 15) organisational standards? | Constants with no cited source |
| Q5 | Why is PySpark the assumed rebuild target? | `pyspark_type` computed with no recorded requirement |
| Q6 | What retention policy applies to run directories? | None implemented or documented |
| Q7 | Who owns `brd_annotations.json` operationally? | No process documented |
| Q8 | Should the BRD carry a classification marking? | No requirement recorded |
| Q9 | What is the largest codebase run through this? | Only a 7-file corpus is present |
| Q10 | What intent-match recall is acceptable for Agent 08? | Stated as "imperfect" by design, never quantified |
| Q11 | Is symlink following intended in Agent 01? | No policy, no test |
| Q12 | What should happen when ANTLR and sqlglot disagree? | No reconciliation logic or test |

---

## 6. Prioritised recommendations

Ordered by risk reduction per unit of effort. **None of these are implemented** — they are recommendations, not features.

| Priority | Recommendation | Addresses |
|---|---|---|
| **1** | Add `requirements.txt` or `pyproject.toml` with pinned versions | GAP-O01 |
| **2** | Run the pipeline against foreign, non-banking PL/SQL and re-measure | GAP-E04, GAP-E01 |
| **3** | Implement `TRANSITIONS_TO`, or delete the misleading comment | GAP-D01 |
| **4** | Add CI running the 414 tests on push | GAP-O02 |
| **5** | Add a labelled corpus for file-role classification accuracy | GAP-E02 |
| **6** | Sanitise or escape annotation content | GAP-S01 |
| **7** | Store condition text in Agent 02; remove three duplicate implementations | GAP-D02 |
| **8** | Publish JSON Schemas for each artefact | GAP-O07 |
| **9** | Add run-directory retention/pruning | GAP-O05 |
| **10** | Report a count when dangling edges are dropped | GAP-D03 |

---

*Gaps verified against the repository during documentation. Open questions are explicitly outside what the code can answer.*
