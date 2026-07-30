# System Overview

A short orientation document. For full detail see [complete-system-technical-documentation.md](complete-system-technical-documentation.md); for per-stage detail see the [agent documents](agents/).

## Contents

- [1. What it is in one paragraph](#1-what-it-is-in-one-paragraph)
- [2. The five things worth knowing first](#2-the-five-things-worth-knowing-first)
- [3. What goes in, what comes out](#3-what-goes-in-what-comes-out)
- [4. The eight stages at a glance](#4-the-eight-stages-at-a-glance)
- [5. How to read the rest of the documentation](#5-how-to-read-the-rest-of-the-documentation)

---

## 1. What it is in one paragraph

**STATUTE** — *Structured Translation & Analysis Tool for Undocumented Transactional Engines* — takes a directory of Oracle PL/SQL files and produces a Business Requirements Document, a set of Mermaid diagrams, and a queryable knowledge graph. It is eight independent Python command-line programs chained by versioned JSON artefacts on the local filesystem. It calls no language model, opens no network connection, reads no environment variable and connects to no database. Every sentence in the document it produces is assembled by rule from a parse tree, which is why every statement can cite a file and a line number.

---

## 2. The five things worth knowing first

1. **"Agent" means pipeline stage, not autonomous LLM agent.** The eight `.claude/agents/*.md` files are specifications for the development harness; the pipeline is the eight Python scripts.

2. **There is no orchestrator.** A human runs eight commands in order. Each stage prints the next command. `Architectural inference based on the following repository evidence:` no orchestration module or workflow framework exists anywhere.

3. **The filesystem is the state.** Each stage writes `output/<stage>/<timestamp>/` and only then updates `output/<stage>/latest.json`. A crashed run leaves an orphan directory; the pointer still names the last good run.

4. **Stable identifiers are the architecture.** `file_id` is derived from the file *path*, not its contents, so editing a file preserves its identity. `statement_id` embeds `file_id`. That chain is what makes the traceability matrix exact and the annotation layer possible.

5. **The system is deliberately honest about what it cannot know.** Disabled constraints are published *with* a warning. Uncertain rules are marked *needs review*. Diagrams that could not fit declare it. The graph exports its own blind spots as queryable nodes. 21 gaps are recorded on the reference corpus.

---

## 3. What goes in, what comes out

**In:** a directory of `.sql` files. Optionally, `brd_annotations.json` — human knowledge keyed by stable ID, read but never written.

**Out**, on the reference corpus (7 files, 603 lines of code):

| Deliverable | Detail |
|---|---|
| `brd.md` | ~2,550 lines, 41 requirements, four parts by audience, clickable contents |
| `brd_index.json` | The same content as structured data |
| `gaps_register.json` | 21 open matters ranked by severity |
| `diagrams/*.mmd` | 7 figures — data-flow map, entity state model, 5 process flows |
| `erd.mmd` | Entity relationship diagram (produced by Agent 03) |
| `import.cypher` + CSVs | 353-node / 769-relationship knowledge graph |
| `--ask` interface | 12 questions answerable with or without Neo4j |

---

## 4. The eight stages at a glance

| # | Stage | One-line job | Third-party deps |
|---|---|---|---|
| 1 | [Inventory](agents/agent-01-inventory.md) | Classify files, assign stable `file_id` | none |
| 2 | [Parser](agents/agent-02-parser.md) | ANTLR4 → statements + control-flow graph | ANTLR4, sqlglot |
| 3 | [Data](agents/agent-03-data.md) | DDL → schema + **real enforcement state** + ERD | ANTLR4 |
| 4 | [Logic](agents/agent-04-logic.md) | Pseudocode, complexity, backward slices, CRUD | none |
| 5 | [Rules](agents/agent-05-rules.md) | 9 sources → business rules with confidence | none |
| 6 | [Diagram](agents/agent-06-diagram.md) | Renderer-agnostic model → Mermaid | none |
| 7 | [Synthesis](agents/agent-07-synthesis.md) | The BRD + machine index + gaps | none |
| 8 | [Graph](agents/agent-08-graph.md) | Property graph + plain-English Q&A *(optional)* | none |

Only Agents 02 and 03 have third-party dependencies. The other six use the standard library only.

---

## 5. How to read the rest of the documentation

| If you are… | Start here |
|---|---|
| Orienting yourself | This document, then [the master document](complete-system-technical-documentation.md) §1–§11 |
| Taking over maintenance | [Master document](complete-system-technical-documentation.md) §36, then the agent document for the stage you are changing |
| Reviewing architecture | [architecture-decisions.md](architecture-decisions.md) — 11 ADRs |
| Assessing risk | [known-gaps-and-open-questions.md](known-gaps-and-open-questions.md) |
| Verifying a claim | [traceability-matrix.md](traceability-matrix.md) |
| Checking what influenced the design | [references.md](references.md) |
| Judging documentation quality | [documentation-review-report.md](documentation-review-report.md) |

---

*See the [master document](complete-system-technical-documentation.md) for full architecture, workflow, formulas, security and operations detail.*
