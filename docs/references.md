# References

Classified as the documentation brief requires: what the repository already cites, what demonstrably influenced the code, what was found while researching this documentation, and what was used only to shape these documents.

## Contents

- [1. Declared in the repository](#1-declared-in-the-repository)
- [2. Directly influenced the implementation](#2-directly-influenced-the-implementation)
- [3. Discovered during documentation research](#3-discovered-during-documentation-research)
- [4. Used only to improve documentation format](#4-used-only-to-improve-documentation-format)
- [5. Software and licences](#5-software-and-licences)

---

## 1. Declared in the repository

Agents 03–08 each declare a `DESIGN_REFERENCES` constant in code, emitted into their artefacts. **Agents 01 and 02 declare none.** `Confirmed from implementation.`

| Agent | `DESIGN_REFERENCES` entries | Location |
|---|---|---|
| 01 Inventory | 0 | — |
| 02 Parser | 0 | — |
| 03 Data | **7** | `03_data.py:68` |
| 04 Logic | 3 | `04_logic.py:45` |
| 05 Rules | 2 | `05_rules.py` |
| 06 Diagram | 2 | `06_diagram.py` |
| 07 Synthesis | 2 (module docstring lists 9 works) | `07_synthesis.py` |
| 08 Graph | 4 | `08_graph.py` |

Additional in-repository sources: the eight `.claude/agents/*.md` specifications, `.claude/skills/*/SKILL.md`, `.claude/scripts/vendor/plsql_grammar/NOTICE.md`, and the project `README.md`.

---

## 2. Directly influenced the implementation

Each of the following is named in code, in a `DESIGN_REFERENCES` block, or in an agent specification, **and** a corresponding implementation is present.

### Metrics and program analysis

| Work | Applied in | Implementation evidence |
|---|---|---|
| **McCabe (1976)**, cyclomatic complexity | Agent 04 | `compute_cyclomatic`; `CYCLOMATIC_THRESHOLD = 10` |
| **Campbell**, cognitive complexity | Agent 04 | `compute_cognitive`, `nesting_level_of`; `COGNITIVE_THRESHOLD = 15` |
| **Weiser (1981)**, program slicing | Agent 04 → 05 | `slice_for_variable`, `control_ancestors`; consumed by `mine_from_variable_slices` |
| **Yamaguchi, Golde, Arp & Rieck (2014)**, *Modeling and Discovering Vulnerabilities with Code Property Graphs*, IEEE S&P | Agent 08 | `Statement` nodes joined by CFG and dependence edges in `lib_graph_model.py` |
| **Lehnert**, *A review of software change impact analysis* | Agent 08 | `BlindSpot` nodes — no automated impact analysis is complete |

### Requirements and documentation standards

| Work | Applied in | Implementation evidence |
|---|---|---|
| **ISO/IEC/IEEE 29148:2018** | Agent 07 | Requirement attribute schema; unresolvable attributes rendered as visible blanks |
| **OMG SBVR 1.5** | Agents 05, 07 | `_raise_to_obligation`; `rule_modality` alethic vs deontic |
| **IIBA BABOK v3** | Agents 06, 07 | Diagram selection; scope, glossary, honest requirement classification |
| **Mavin et al., EARS** | Agent 07 | Formal requirement statements |
| **Chikofsky & Cross (1990)**, IEEE Software 7(1) | Agent 07 | Each BRD part declares redocumentation vs design recovery |
| **Biggerstaff, Mitbander & Webster (1993)**, concept assignment | Agent 07 | The stated reason the annotation layer exists |
| **Aghajani et al. (ICSE 2020)**, practitioners' perspective | Agent 07 | Audience-partitioned document structure |
| **Lethbridge, Singer & Forward (2003)** | Agent 07 | Regenerable documentation rationale |
| **Cosentino et al. (WCRE 2013)** | Agent 07 | Controlled vocabulary linking business terms to code |

### Visualisation

| Work | Applied in | Implementation evidence |
|---|---|---|
| **Moody (2009)**, *The "Physics" of Notations*, IEEE TSE 35(6) | Agent 06 | Semantic transparency, dual coding, complexity management, graphic economy |
| **Shneiderman (1996)**, *The Eyes Have It* | Agents 06, 07 | Overview → zoom → details-on-demand structure |
| **Shneiderman, Mayer, McKay & Heller (1977)**, CACM 20(6):373–381 | Agent 06 | Detailed flowcharts showed no measurable benefit → collapse straight-line runs |
| **Purchase (1997/2002)**, graph drawing aesthetics | Agent 06 | Edge crossings dominate comprehension → node budget |
| **VEIL** (arXiv 2511.05066) | Agent 06 | Nodes emitted in source order |

### Tooling precedent

| Work | Applied in | Evidence |
|---|---|---|
| **jQAssistant** (scan → graph → concepts + constraints) | Agent 08 | `CONCEPTS` and `CONSTRAINTS` shipped in the generated README |
| **Neo4j property-graph modelling guidance** | Agent 08 | Node-vs-property rule stated in `lib_graph_model.py` |
| **CAST Imaging / Thoughtworks CodeConcise** | Agent 08 spec | Cited as industry precedent for a graph knowledge base |

### Comparison baselines (evaluation only)

Cited in `tests/evaluate_rules.py` as published COBOL results, **not** as implemented techniques:
**COBREX** F1 0.59 · **COBRAIN** F1 0.73 · **A-COBREX** P 0.62 / R 0.74.

### Industrial motivation

**Sneed**, *From COBOL to Business Rules* — the 6.4 MLOC precedent cited in `README.md` as the motivating scenario.

---

## 3. Discovered during documentation research

Consulted while producing this package. **No claim is made that these influenced the implementation.**

| Work | Why consulted |
|---|---|
| [arc42 template](https://arc42.org/overview) — 12-section architecture documentation structure | Section ordering for the master document |
| [C4 model](https://c4model.com) — context, container, component, code | Diagram level selection; the system-context diagram is a C4 Level-1 view |
| [Michael Nygard, *Documenting Architecture Decisions*](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) | ADR format |
| [adr.github.io templates](https://adr.github.io/adr-templates/) | ADR template comparison |

---

## 4. Used only to improve documentation format

- **Mermaid diagram syntax** — every diagram in this package uses Mermaid so it renders in GitHub and VS Code without a toolchain, matching the pipeline's own output format.
- **GitHub-flavoured markdown anchors** — the same `anchor()` convention Agent 07 uses for the BRD contents page.

---

## 5. Software and licences

| Component | Licence | Notes |
|---|---|---|
| **ANTLR4 Oracle PL/SQL grammar** | Apache 2.0 | Vendored from `antlr/grammars-v4`; see `.claude/scripts/vendor/plsql_grammar/NOTICE.md`. Generated Python requires a `this.` → `self.` patch after regeneration. |
| **antlr4-python3-runtime** | BSD | **Unpinned — no manifest declares it.** |
| **sqlglot** | MIT | **Unpinned — no manifest declares it.** |
| **This project** | See `LICENSE` | |

> **Risk.** Two third-party runtime dependencies exist with no `requirements.txt`, `pyproject.toml` or lockfile. This is recorded as the largest supply-chain exposure in [known-gaps-and-open-questions.md](known-gaps-and-open-questions.md).

---

*Reference classification performed during documentation. Anything not evidenced in the repository is placed in section 3 or 4, never section 2.*
