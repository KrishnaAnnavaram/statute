# Architecture Decision Records

Format: [Michael Nygard's ADR template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) — Title, Status, Context, Decision, Consequences.

> **Grounding note.** These decisions are **reconstructed from the implementation and from rationale recorded in code comments, module docstrings and `.claude/agents/*.md` specifications.** No ADR file existed in the repository before this documentation package. Where the reasoning is stated in the repository, it is quoted and cited. Where it is not, the record says so.

## Contents

- [ADR-001 No language model in the generation path](#adr-001-no-language-model-in-the-generation-path)
- [ADR-002 Filesystem-mediated pipeline with no orchestrator](#adr-002-filesystem-mediated-pipeline-with-no-orchestrator)
- [ADR-003 Path-derived stable identifiers](#adr-003-path-derived-stable-identifiers)
- [ADR-004 Versioned runs with pointer-after-write](#adr-004-versioned-runs-with-pointer-after-write)
- [ADR-005 Formal grammar over regular expressions](#adr-005-formal-grammar-over-regular-expressions)
- [ADR-006 Two-axis constraint enforcement model](#adr-006-two-axis-constraint-enforcement-model)
- [ADR-007 Separate the diagram model from the renderer](#adr-007-separate-the-diagram-model-from-the-renderer)
- [ADR-008 Stop at documentation, do not generate code](#adr-008-stop-at-documentation-do-not-generate-code)
- [ADR-009 Deterministic intent catalogue over generated Cypher](#adr-009-deterministic-intent-catalogue-over-generated-cypher)
- [ADR-010 Human annotations in a read-only sidecar](#adr-010-human-annotations-in-a-read-only-sidecar)
- [ADR-011 Single collapse tier in diagram reduction](#adr-011-single-collapse-tier-in-diagram-reduction)

---

## ADR-001 No language model in the generation path

**Status:** Accepted · **Evidence:** every stage docstring; enforced by `tests/test_synthesis.py`

**Context.** The system produces a specification that a team may rebuild from. Generative approaches are the obvious way to produce readable prose from code structure.

**Problem.** A fabricated business rule in a specification is undetectable by the person relying on it.

**Options.**
1. LLM generates prose from structured facts
2. LLM generates, deterministic layer validates
3. Fully deterministic assembly

**Decision.** Option 3. No model call anywhere.

**Reason (stated in the repository).** `README.md`: *"A deterministic pipeline that misses a rule fails visibly; a generative one that invents a rule fails invisibly."* Two supporting findings are cited: no automated documentation metric correlates meaningfully with expert judgement (best reported *r* = 0.34), and expert inter-rater agreement fell to ICC 0.12 on hard material — so model self-checking is not a safety net.

**Consequences.**
- ✅ Output is a pure function of input; hallucination is structurally impossible
- ✅ Every statement can cite a file and line
- ✅ No API keys, cost, rate limits or network dependency
- ❌ Prose quality is bounded by template and heuristic quality
- ❌ Naming heuristics required substantial iteration (Agent 05 `describe_comparison`)

---

## ADR-002 Filesystem-mediated pipeline with no orchestrator

**Status:** Accepted · **Evidence:** absence of any orchestration module; each script has its own `main()`

**Context.** Eight stages with a dependency order.

**Options.** (1) Workflow engine · (2) Single process with in-memory hand-off · (3) Independent CLI programs chained by artefacts on disk.

**Decision.** Option 3.

**Reason.** `Architectural inference based on the following repository evidence:` no framework import exists; every stage is independently runnable and independently testable; each prints the next command. **No repository comment states this reasoning explicitly.**

**Consequences.**
- ✅ Any stage can be re-run in isolation; artefacts are inspectable JSON
- ✅ Zero orchestration dependency
- ❌ Sequencing is the operator's responsibility — no automation enforces order
- ❌ No parallelism, though Agents 03 and 04 are independent
- ❌ No cross-stage failure propagation

---

## ADR-003 Path-derived stable identifiers

**Status:** Accepted · **Evidence:** `01_inventory.py:133` `make_file_id`

**Context.** Rules, statements, diagrams and graph nodes must be joinable across regenerations.

**Options.** (1) Content hash · (2) Sequential integer · (3) Path-derived slug + path hash.

**Decision.** Option 3 — `SLUG(rel_path) + "__" + SHA256(rel_path)[0:8]`.

**Reason.** A content hash changes when a file is edited, breaking every downstream reference. A sequence is unstable under file addition or removal.

**Consequences.**
- ✅ Editing a file preserves its identity — the enabling condition for the traceability matrix and the annotation layer
- ✅ `statement_id` inherits stability by embedding `file_id`
- ❌ **Moving or renaming a file changes its identity** and orphans annotations keyed to it
- ❌ Slug collisions require explicit handling

---

## ADR-004 Versioned runs with pointer-after-write

**Status:** Accepted · **Evidence:** `generate_run_version` in all eight scripts; `latest.json` written after the artefact

**Context.** A failed stage must not corrupt downstream input.

**Decision.** Write `output/<stage>/<timestamp>/`, then update `output/<stage>/latest.json`.

**Consequences.**
- ✅ A crash mid-write leaves an orphan directory; `latest.json` still points at the last good run
- ✅ Immutable audit trail; any document traceable to exact inputs
- ❌ **Unbounded disk growth** — 17 `final_report` runs accumulated in one development session
- ❌ No concurrency control; the last `latest.json` write wins

---

## ADR-005 Formal grammar over regular expressions

**Status:** Accepted · **Evidence:** `.claude/scripts/vendor/plsql_grammar/`, `02_parser.py:38`

**Context.** PL/SQL must be converted to structure.

**Decision.** Vendor the ANTLR4 Oracle PL/SQL grammar from `antlr/grammars-v4` (Apache 2.0).

**Reason (stated in the repository).** `README.md`: *"regex cannot survive nested blocks, string literals containing keywords, or `CASE` inside `CASE`."*

**Consequences.**
- ✅ Correct handling of nesting and literals
- ✅ Shared by Agents 02 and 03, so code and DDL parse consistently
- ❌ Large vendored codebase
- ❌ **Generated Python emits `this.` instead of `self.` and must be patched after every regeneration** (`vendor/plsql_grammar/NOTICE.md`)
- ❌ Adds an unpinned third-party runtime dependency

---

## ADR-006 Two-axis constraint enforcement model

**Status:** Accepted · **Evidence:** `03_data.py` `parse_constraint_state`, `enforcement_summary`; `05_rules.py:176`

**Context.** A constraint can exist in the schema and not be enforced.

**Decision.** Model `STATUS` × `VALIDATED` as independent axes producing three confidence levels, and carry them through to the BRD.

**Reason (stated in the repository).** Agent 03's specification: a DISABLED constraint is still surfaced, because dropping it *"would hide a documented business intent from the BRD entirely"* — but it is scored low, flagged for review, and its statement says the database is not enforcing it.

**Consequences.**
- ✅ The BRD never asserts a guarantee the database is not providing
- ✅ Drives SBVR modality selection in Agent 07
- ❌ Agent 05 keys on the confidence **string**, creating a brittle coupling

---

## ADR-007 Separate the diagram model from the renderer

**Status:** Accepted · **Evidence:** `06_diagram.py` `DiagramSpec` / `MermaidRenderer`; `lib_graph_model.py`

**Context.** The predecessor formatted Mermaid strings inline while walking the CFG.

**Problem (stated in the repository).** Agent 06's docstring: *"there was nothing to count, so the documented `--max-nodes` budget was declared and never implemented; nothing but strings to assert on, so 7 tests could only check syntax; and no way to change renderer."*

**Decision.** Build a renderer-agnostic model; render last.

**Consequences.**
- ✅ Node budget became enforceable
- ✅ Tests assert meaning (52 checks, up from 7)
- ✅ A Graphviz renderer would be a drop-in addition
- ✅ Reused in Agent 08 — local answers and Neo4j answers cannot disagree
- ❌ Extra indirection

---

## ADR-008 Stop at documentation, do not generate code

**Status:** Accepted · **Evidence:** absence of any code-generation stage; `README.md` rationale

**Reason (stated in the repository).** *"extraction reaches roughly 90% precision and recall, while end-to-end code generation lands near 9%. Extraction is a solved-enough problem; translation is not."*

**Consequences.**
- ✅ Scope matches demonstrated capability
- ✅ Human judgement stays where evidence says it is required
- ❌ The consumer must still perform the rebuild
- ❌ Target-type mapping assumes PySpark without a recorded requirement

---

## ADR-009 Deterministic intent catalogue over generated Cypher

**Status:** Accepted · **Evidence:** `lib_graph_language.py` module docstring and `INTENTS`

**Reason (stated in the repository).** *"a fabricated Cypher query returns a plausible, wrong answer, and the user has no way to tell… an impact-analysis answer that silently omits a caller is exactly the failure mode that makes a modernization project fail."*

**Decision.** 12 named intents, each with trigger patterns, a resolver and equivalent Cypher. Unmatched questions are refused with the supported list.

**Consequences.**
- ✅ Total precision — an answer is always correct or absent
- ✅ Works offline; answers ship their Cypher
- ❌ **Imperfect and unmeasured recall** — a valid question may be refused
- ❌ Each new question requires code

---

## ADR-010 Human annotations in a read-only sidecar

**Status:** Accepted · **Evidence:** `07_synthesis.py` `load_annotations` docstring

**Context.** Domain intent is not recoverable from code (Biggerstaff's concept assignment problem), yet the document regenerates on every run.

**Decision.** `brd_annotations.json`, keyed by stable ID, merged at render time, **never written by the pipeline**.

**Reason (stated in the repository).** *"Static analysis can prove that a threshold of 365 days exists; it can never discover that the threshold is mandated by regulation rather than chosen… machine facts regenerate every run; this file is never written by the pipeline, only read."*

**Consequences.**
- ✅ Human knowledge survives regeneration
- ✅ Clean separation of machine fact from human meaning
- ❌ **Content is inserted verbatim with no sanitisation** — markdown injection is possible
- ❌ Annotations keyed to a moved file's ID are silently orphaned (see ADR-003)
- ❌ No tooling assists authoring; no ownership process is documented

---

## ADR-011 Single collapse tier in diagram reduction

**Status:** Accepted — supersedes a removed two-tier design · **Evidence:** `06_diagram.py` `collapse_runs` comment

**Context.** Diagrams must fit a node budget without losing structure.

**Problem (stated in the repository).** A second collapse tier *"merged every collapsible child of a parent regardless of adjacency, fusing lines 33 and 124 into one node and implying they run together — the diagram met its budget by misrepresenting the flow."*

**Decision.** One tier: merge **contiguous** runs only. If the budget is still unreachable, declare the diagram oversize rather than collapse further.

**Consequences.**
- ✅ Diagrams never imply an ordering that does not exist
- ✅ Structure (decisions, loops, error paths, terminals) always survives
- ❌ One diagram in the reference corpus exceeds the budget (45 vs 40) — declared, by design

---

*Decisions reconstructed during documentation. Where the repository records reasoning it is quoted and cited; ADR-002 is explicitly an architectural inference.*
