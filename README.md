# statute

**Reverse-engineers an Oracle PL/SQL codebase into a Business Requirements
Document, a set of diagrams, and a queryable knowledge graph — deterministically,
with every statement traceable to a source line.**

No language model generates, summarises, judges or rewrites any of the output.
Structure comes from a formal Oracle PL/SQL grammar; SQL is decomposed with
sqlglot; every sentence in the BRD is assembled by rule from the resulting parse
trees. The same source always produces the same document. **Hallucination is not
reduced — it is structurally impossible**, because there is no model in the
generation path. That is what makes it safe for every claim to cite a file and
line a reviewer can open.

---

## Contents

- [What it produces](#what-it-produces)
- [Quick start](#quick-start)
- [The problem this solves](#the-problem-this-solves)
- [System design](#system-design)
- [The eight agents](#the-eight-agents)
- [Asking the knowledge graph questions](#asking-the-knowledge-graph-questions)
- [The annotation layer](#the-annotation-layer)
- [Repository layout](#repository-layout)
- [Testing](#testing)
- [Honest limitations](#honest-limitations)
- [Design references](#design-references)

---

## What it produces

From `src/` — seven files, 603 lines of PL/SQL — one run produces:

| Deliverable | Detail |
|---|---|
| **Business Requirements Document** | ~2,550 lines, 41 requirements, four parts by audience, clickable contents |
| **Machine-readable index** | `brd_index.json` — same content as structured data |
| **Gaps register** | 21 open matters ranked by severity |
| **Diagrams** | ERD, system data-flow map, entity state model, 5 process flows (Mermaid) |
| **Knowledge graph** | 353 nodes / 769 relationships, MERGE-based Cypher + CSVs for Neo4j |
| **Plain-English query interface** | 12 supported questions, answerable with or without Neo4j |

---

## Quick start

**Requirements:** Python 3.11+, `antlr4-python3-runtime`, `sqlglot`. No database,
no API key, no network access.

```bash
# Run all eight stages, in order
python .claude/scripts/01_inventory.py src
python .claude/scripts/02_parser.py
python .claude/scripts/03_data.py
python .claude/scripts/04_logic.py
python .claude/scripts/05_rules.py
python .claude/scripts/06_diagram.py
python .claude/scripts/07_synthesis.py
python .claude/scripts/08_graph.py
```

Each stage prints where it wrote and what the next stage is. Then:

```bash
# The document
cat output/final_report/<newest-run>/brd.md

# Ask the graph a question — no Neo4j needed
python .claude/scripts/08_graph.py --ask "what breaks if I change ACCOUNTS.BALANCE"
python .claude/scripts/08_graph.py --list-questions
```

```bash
# Everything, verified
for t in tests/test_*.py; do python "$t"; done     # 414 checks
python tests/evaluate_rules.py                      # rule extraction vs ground truth
```

---

## The problem this solves

An organisation has a working Oracle PL/SQL system and no reliable
documentation. The people who wrote it have gone. Before it can be modernised,
replaced or audited, somebody has to answer: **what does it actually do, and
what rules does it enforce?**

Harry Sneed's industrial account of a 6.4-million-line COBOL system is the
canonical version of this: two modernisation attempts failed — one automatic
conversion, one package replacement — before the team fell back on *rewriting
from a specification derived from the code*. That is the scenario this pipeline
serves, and it sets the design constraint: the output is consumed by **builders**,
not just readers. Numbered, traceable, verifiable, with explicit gaps.

### Why it stops at documentation

The obvious extension is generating the replacement code. Published results say
don't: extraction reaches roughly 90% precision and recall, while end-to-end code
generation lands near 9%. Extraction is a solved-enough problem; translation is
not. The pipeline deliberately stops where the evidence stops.

### Why there is no LLM in it

Two independent findings drove this. Empirically, no automated documentation
metric correlates meaningfully with expert judgement of quality (best reported
*r* = 0.34), and expert inter-rater agreement on hard material fell to ICC 0.12 —
so "the model checked it" is not a safety net. Practically, a fabricated business
rule in a specification is undetectable to the person relying on it. A
deterministic pipeline that misses a rule fails *visibly*; a generative one that
invents a rule fails *invisibly*. For this deliverable, the first failure mode is
strictly better.

---

## System design

### Eight stages, one artifact contract

```
  src/*.sql
     │
  ┌──▼───────────┐
  │ 1 Inventory  │  catalogue files, assign stable file_id
  └──┬───────────┘
  ┌──▼───────────┐
  │ 2 Parser     │  ANTLR4 → statements, control-flow graph, statement_id
  └──┬───────────┘
     ├─────────────────────┐
  ┌──▼───────────┐   ┌─────▼────────┐
  │ 3 Data       │   │ 4 Logic      │  pseudocode, complexity, slices
  │ DDL, ERD     │   └─────┬────────┘
  └──┬───────────┘         │
     └──────────┬──────────┘
  ┌────────────▼─┐
  │ 5 Rules      │  41 business rules, 9 mining sources
  └────────────┬─┘
  ┌────────────▼─┐
  │ 6 Diagrams   │  data flow, process flows, state models
  └────────────┬─┘
  ┌────────────▼─┐
  │ 7 BRD        │  the document + machine index + gaps
  └────────────┬─┘
  ┌────────────▼─┐
  │ 8 Graph      │  knowledge graph + query interface   (optional)
  └──────────────┘
```

### Design principle 1 — stable identity everywhere

Every artifact is keyed by identifiers that survive regeneration:

| Identifier | Form | Example |
|---|---|---|
| File | `{SLUG}__{8-char SHA256 of relative path}` | `05_MEDIUM_FUND_TRANSFER__5E3A3BBB` |
| Statement | `{file_id}__{object_id}__STMT_{seq:04d}` | `..._SP_TRANSFER_FUNDS__STMT_0012` |
| Rule | `BR-nnn` | `BR-014` |
| Column | `TABLE.COLUMN` | `ACCOUNTS.BALANCE` |

`file_id` is derived from the **path**, not content, so editing a file does not
change its identity. This is what makes the traceability matrix exact, the
diagrams cross-referenceable, and the annotation layer possible.

### Design principle 2 — versioned runs, pointer-on-success

Every stage writes `output/<stage>/<timestamp>/` and only then updates
`output/<stage>/latest.json`. A failed run cannot corrupt what downstream stages
read. Every artifact records the upstream run versions it consumed, so any
document can be traced to the exact inputs that produced it.

### Design principle 3 — each stage does one kind of work

Stages do not overlap. The parser does not interpret meaning. The rules agent
does not re-parse. The diagram agent draws only what earlier stages discovered.
When a defect appears, there is exactly one place it can live.

### Design principle 4 — confidence is data, never hidden

Nothing uncertain is silently dropped or silently asserted. A rule inferred from
code structure is marked `needs review`; a database constraint that is `DISABLED`
is published *with a warning that it is not enforced*; a diagram too large to
render legibly says so. All of it flows into the gaps register.

### Design principle 5 — separate the model from the rendering

Agents 6 and 8 build an in-memory model first and render last. This is why
Agent 6's node budget can work at all (there is something to count), why its
tests can assert meaning rather than string formatting, and why the knowledge
graph's local answers and its Neo4j answers cannot disagree — both are views over
one structure.

---

## The eight agents

### Agent 1 — Inventory

**Job:** walk the source tree, decide what each file is, give each a stable
identity.

Classifies every file by role (`schema_ddl`, `seed_data`, `procedure`,
`function`, `package`, `trigger`, `mixed`) using 25 content-based regex hints —
content, not filename, because a file called `utils.sql` containing
`CREATE TABLE` is DDL. Scores complexity, records line counts, encoding, hash and
size, and flags anything unreadable.

**Why it matters:** downstream routing depends on it. An earlier version
classified files with a `CREATE VIEW` as `mixed`, so they never reached Agent 3
and every table in them vanished from the data model.

**Output:** `inventory-artifact.json` — `file_index`, `file_metadata`, `summary`.

---

### Agent 2 — Parser

**Job:** turn PL/SQL text into structure. This is the only stage that reads
source characters.

Uses the **ANTLR4 grammar for Oracle PL/SQL** (from `antlr/grammars-v4`,
Apache 2.0, vendored). A real grammar, not regex — regex cannot survive nested
blocks, string literals containing keywords, or `CASE` inside `CASE`. Individual
DML statements are additionally decomposed with **sqlglot** in Oracle dialect to
recover tables, written columns and predicate columns.

Two passes: pass A discovers every object across the run so calls can be
resolved; pass B extracts statements and resolves references.

Produces a **nested statement tree** (each statement carries `parent_id` and
`scope_path`) and a **control-flow graph** with four typed edges — `SEQUENCE`,
`BRANCH_ENTRY`, `EXCEPTION_EDGE`, `LOOP_BACK_EDGE`.

**Why the flat-id-plus-hierarchy shape:** IDs are flat and sortable for joining;
structure lives in `parent_id`. Same pattern as OpenTelemetry spans, and it is
what lets later stages walk the tree without re-parsing.

**Output:** `parser_artifact.json` + one JSON per object under `raw_structure/`.

---

### Agent 3 — Data

**Job:** build the physical data dictionary, and close the loop back to Agent 2.

Parses DDL with the same grammar. Extracts tables, columns (including virtual and
IDENTITY), primary keys, foreign keys with `ON DELETE` behaviour, CHECK
constraints, unique constraints, indexes, sequences, synonyms, partitioning,
global temporary tables and `COMMENT ON` documentation.

**The distinguishing detail — real enforcement state.** Oracle constraints have
two independent axes: `STATUS` (ENABLED/DISABLED) and `VALIDATED`
(VALIDATED/NOT VALIDATED). A constraint can exist and not be enforced. The agent
records the true state and maps it to confidence, so the BRD can say *"the
database records this rule but is not applying it"* rather than asserting a
guarantee that does not exist.

Also resolves `%TYPE`/`%ROWTYPE`, cross-validates every table and column
reference from Agent 2 (resolving synonyms and views), tracks column usage, and
generates the **ERD**.

**Output:** `data_artifact.json` + `erd.mmd`.

---

### Agent 4 — Logic

**Job:** make control flow readable and measurable.

- **Pseudocode** — walks the `parent_id` tree, not the flat statement list, so
  `IF`/`ELSIF`/`ELSE` nesting survives translation.
- **Cyclomatic complexity** (McCabe 1976) — decision points + 1, threshold 10.
- **Cognitive complexity** (Campbell) — nesting-weighted, threshold 15.
- **Backward slices** (Weiser 1981) — for each variable, every statement that
  determines its value, including control ancestors.
- **Transaction analysis** — COMMIT-inside-loop, SAVEPOINT partial rollback,
  no-transaction-control, each with a severity and an explanation.
- **Processing shape** — `BATCH_PROCESSOR`, `SINGLE_RECORD_TRANSACTION`,
  `CALCULATION`, `QUERY_ONLY`, with the rationale for the classification.
- **CRUD matrix** — object × table × operations.

**Deliberately not done:** dead-code detection. PL/SQL objects are routinely
invoked by schedulers or code outside the repository, so "no internal callers" is
reported as *informational only*, never as a finding.

**Output:** `logic_artifact.json` + one record per object.

---

### Agent 5 — Rules

**Job:** find the business decisions and state them as requirements.

Mines **nine sources**:

| Source | What it captures |
|---|---|
| `conditional_branch` | Every IF / ELSIF / ELSE branch — one outcome per branch |
| `case_branch` | Every WHEN / ELSE of a CASE expression |
| `cursor_eligibility` | A cursor's WHERE clause — *which records* the process applies to |
| `named_exception` | A guarded RAISE, restated as the obligation it enforces |
| `predefined_exception` | An Oracle exception the database itself detected |
| `failure_isolation` | Per-record failure logged and skipped — a resilience requirement |
| `error_contract` | `WHEN OTHERS` raising a specific error callers depend on |
| `variable_derivation` | Business formulas, from Agent 4's backward slices |
| `ddl_*` | CHECK constraints, virtual columns, unique constraints, view filters |

**Exceptions become obligations.** SBVR is explicit that *"there are no
exceptions; instead, there are well stated business rules."* A guarded `RAISE`
merges with the `IF` that guards it and is phrased as what must hold — the IF
condition is the *violation*, so the rule is its negation.

**Measured, not asserted.** `tests/evaluate_rules.py` scores extraction against
hand-annotated ground truth using source-line proximity rather than phrasing.
Baseline was F1 0.593 — level with COBREX's published 0.59. See
[Honest limitations](#honest-limitations) for what the current number means.

**Output:** `rules_artifact.json` — rules, rule sets, error-handling catalogue.

---

### Agent 6 — Diagrams

**Job:** the visual layer. Builds a renderer-agnostic model, then emits Mermaid.

| Diagram | Built from |
|---|---|
| **ERD** | Agent 3 — *indexed here, never regenerated* |
| **System data-flow map** | Agent 4's CRUD matrix + Agent 2's calls + rule counts + complexity |
| **Process flow** (per object) | Agent 2's CFG ⋈ Agent 5's rules on `statement_id` |
| **Entity state model** | Agent 3's CHECK IN-list + the UPDATEs that write that column |
| **CRUD matrix** | Agent 4 — as a table, because tabular data belongs in a table |

**Labels carry meaning.** Decisions read `Balance below 100,000?` and branches
carry the rule they enact (`BR-041`). 100% of decisions and 100% of decision
branches resolve to business text.

**The node budget is real.** Contiguous straight-line runs collapse; decisions,
loops, error paths and terminals never do. Where structure genuinely cannot fit,
the diagram is emitted and **declared oversize** — which reaches the BRD — rather
than silently exceeding. An earlier collapse tier met the budget by merging
statements at lines 33 and 124 into one node, implying they run together; it was
removed, because a diagram that lies to hit a number is worse than a large one.

**Output:** `diagrams_artifact.json` + `diagrams/*.mmd`.

---

### Agent 7 — BRD Synthesis

**Job:** assemble the document four different readers can each use.

**Business language everywhere.** `lib_business_language.py` is the single
translation point:

```
PROC-.SP_TRANSFER_FUNDS   →  Transfer Funds
v_from_balance < p_amount →  From Balance is below Amount
e_insufficient_balance    →  Insufficient Balance
NUMBER(18,2)              →  Decimal number (18 digits, 2 decimal places)
```

The machine identifier is carried *alongside* the prose, never substituted for
it. Pseudocode and diagrams stay technical by design — only surrounding prose is
held to the readable bar.

**Four parts, by audience:**

| Part | For | Contains |
|---|---|---|
| **I — Business View** | Sponsors | Summary, scope **in and out**, glossary, program units, data flow, CRUD matrix |
| **II — Rules and Behaviour** | Analysts | Rules catalogue, entity state models, error contracts |
| **III — Build Specification** | Developers | Data model with target types, interface contracts, process specs, operational characteristics |
| **IV — Assurance** | Auditors, build leads | Traceability matrix, gaps register, rebuild checklist |

**Every rule is stated three ways** — plain terms, the exact source expression,
and a formal statement using SBVR modality. A database constraint that is ENABLED
and VALIDATED makes violation *impossible* → *"it is necessary that"*. A code
guard exists because violation is *possible* → *"it is obligatory that"*.

**The traceability matrix is published because ours is exact.** Twenty years of
information-retrieval traceability research fights for 19–32% precision on
*inferred* links; these are constructed from `statement_id`.

**Output:** `brd.md`, `brd_index.json`, `gaps_register.json`.

---

### Agent 8 — Knowledge Graph *(optional)*

**Job:** make everything queryable. No other stage depends on it; the JSON
artifacts remain the source of truth.

**353 nodes across 13 labels, 769 relationships across 22 types.**

Three modelling decisions matter:

- **`Column` is a node**, not a property of `Table`. It is read, written,
  constrained and indexed — four independent relationships. As a property,
  impact analysis is unaskable.
- **`Statement` is a node**, giving a **Code Property Graph** layer
  (Yamaguchi et al., IEEE S&P 2014). Agent 2's statement tree is an AST, its
  control-flow graph is a CFG, Agent 4's slices are dependence facts; joining
  them answers questions none answers alone.
- **`BlindSpot` is a node.** Dynamic SQL, external callers, unresolved calls and
  trigger side effects are exported as queryable nodes. The impact-analysis
  literature is unanimous that no automated approach is complete — a graph that
  looks authoritative is more dangerous than a document that looks uncertain.

Ships **concepts** (derived-view Cypher you run once to enrich the graph) and
**constraints** (validation Cypher that should return nothing), after
jQAssistant, so the graph extends without touching the extractor.

**Output:** `import.cypher` (MERGE-based, idempotent), `nodes/*.csv`,
`rels/*.csv`, `README.md`, `graph_artifact.json`.

---

## Asking the knowledge graph questions

```bash
python .claude/scripts/08_graph.py --list-questions
python .claude/scripts/08_graph.py --ask "what breaks if I change ACCOUNTS.BALANCE"
python .claude/scripts/08_graph.py --ask "..." --json     # for scripts
```

```
Subject : ACCOUNTS.BALANCE — NUMBER(18,2) — NOT NULL
Results : 10

  BR-014 Restrict Account Status to allowed values  constrains this table  business rule
  Check Minimum Balance — line 21                   reads                  SELECT_INTO
  Process Monthly Interest Credit — line 58         writes                 UPDATE
  Transfer Funds — line 95                          writes                 UPDATE
  ...

Equivalent Cypher: MATCH (c:Column {column_id: $column}) ...
```

Works **with or without Neo4j** — the same in-memory model backs both the local
answer and the export, so they cannot disagree. Every answer ships the equivalent
Cypher.

**It refuses rather than guesses.** Questions are matched against a named intent
catalogue; no model generates Cypher. An unmatched question is reported as a miss
with the list of what *is* supported. Total precision, imperfect recall — the
correct trade when a wrong impact answer is worse than none.

To load into Neo4j:

```bash
cd output/graph/<newest-run>/
cat import.cypher | cypher-shell -u neo4j -p <password>
```

---

## The annotation layer

Static analysis can prove a 365-day threshold exists. It can never discover that
the threshold is **mandated by regulation** rather than chosen. That sentence is
the most valuable one in the document, and there is nowhere in a
regenerate-from-scratch pipeline for it to live — which is why every commercial
tool in this space ships a curation workbench.

Create `brd_annotations.json` beside the source:

```json
{
  "annotations": {
    "BR-001": {
      "note": "365-day threshold is set by regulation, not policy.",
      "owner": "Head of Retail Operations",
      "priority": "Must have"
    },
    "table:ACCOUNTS": { "note": "Master record for every customer account." },
    "term:ACCOUNTS.BALANCE": { "note": "Cleared balance, excluding pending items." },
    "executive_summary": { "note": "Core retail ledger, in service since 2004." }
  }
}
```

Keyed by stable ID, merged at synthesis time, **never written by the pipeline**.
Machine facts regenerate every run; your notes persist.

---

## Repository layout

```
.claude/
  agents/                    one specification per agent, with design rationale
  scripts/
    01_inventory.py … 08_graph.py
    lib_business_language.py   identifier → business language (Agents 7, 8)
    lib_graph_model.py         the in-memory property graph (Agent 8)
    lib_graph_language.py      plain-English intent catalogue (Agent 8)
    vendor/plsql_grammar/      vendored ANTLR4 Oracle PL/SQL grammar
src/                         the PL/SQL under analysis
tests/
  test_*.py                  414 checks across 8 suites
  evaluate_rules.py          rule extraction vs hand-annotated ground truth
  fixtures/ground_truth/     annotated rules, two of them annotated blind
output/                      versioned runs, one directory per stage (gitignored)
tools_antlr_build/           grammar regeneration
```

---

## Testing

```bash
for t in tests/test_*.py; do python "$t"; done
```

| Suite | Checks | What it guards |
|---|---|---|
| `test_data` | 76 | Enforcement state, type mapping, cross-validation |
| `test_synthesis` | 86 | Readability, navigation, build-completeness, traceability, honesty |
| `test_graph` | 68 | Schema, coverage, loadability, **refusal to guess** |
| `test_diagram` | 52 | Collapse invariants, label coverage, budget declaration |
| `test_logic` | 46 | Complexity, slicing, transaction hazards |
| `test_rules` | 33 | Obligation form, branch decomposition, dedup |
| `test_parser` | 31 | Grammar, CFG edges, sqlglot decomposition |
| `test_inventory` | 22 | Routing, stable IDs, golden diff |
| **Total** | **414** | |

Tests assert **against models, not formatted strings**, which is what lets them
check meaning. The negative tests matter most in `test_graph` — an interface that
answers confidently and wrongly is worse than one that refuses.

Separately, `tests/evaluate_rules.py` measures rule extraction against
hand-annotated ground truth and reports precision, recall and F1 against
published baselines (COBREX 0.59, COBRAIN 0.73, A-COBREX P 0.62 / R 0.74).

---

## Honest limitations

**The rule-extraction F1 is a tuned number.** Ground truth covers 4 of the
corpus's 5 procedures, and each was eventually used to fix the extractor. The
defensible generalisation estimates are the two **blind** measurements taken
before those failures were addressed: **F1 0.588**, and **recall 0.400** on a
procedure containing a construct the others lacked. Running against genuinely
foreign PL/SQL is the next real test.

**Coverage metrics do not prove usefulness.** The quality gates prove the output
is complete, traceable and internally consistent. They do not prove a person
finds it useful — and the strongest study available found *no* automated
documentation metric correlates meaningfully with expert judgement.

**Concepts cannot be recovered from code.** Biggerstaff's concept assignment
problem: a person understands a program by relating it to knowledge that exists
outside the program text. `v_days_inactive > 365` becomes "Validate Days Inactive
above 365" — a lexical transformation. The concept, *dormancy policy*, is
nowhere in the source. The annotation layer exists because of this, not despite
it.

**These are Solution/Functional requirements.** By BABOK's own classification,
the document describes what the system *does*, not why the business wanted it.
The scope chapter says so plainly.

**The graph is a lower bound on dependencies, never an upper bound.** Dynamic
SQL, schedulers, external callers and trigger side effects are invisible to
static analysis. They are exported as `BlindSpot` nodes rather than left for
someone to discover the hard way.

**Detailed flowcharts have weak empirical support.** Shneiderman et al. (1977)
found no measurable benefit from statement-level flowcharts for programmers. The
counter-argument here is that our reader cannot read PL/SQL, so the diagram is
not redundant for them — but that is an argument, not evidence, which is why
Agent 6 draws decisions and outcomes rather than every statement.

---

## Design references

Each agent's specification in `.claude/agents/` records the works it applies and
how. The load-bearing ones:

**Standards** — ISO/IEC/IEEE 29148:2018 (requirement attributes), OMG SBVR 1.5
(alethic vs deontic modality), IIBA BABOK v3 (scope, glossary, classification),
OMG KDM / ISO 19506 (layered knowledge representation), EARS (Rolls-Royce).

**Foundational** — Chikofsky & Cross (1990) redocumentation vs design recovery;
Biggerstaff, Mitbander & Webster (1993) the concept assignment problem; Weiser
(1981) program slicing; McCabe (1976) cyclomatic complexity.

**Extraction and documentation** — Cosentino et al. (WCRE 2013) model-based rule
extraction from COBOL; Sneed, *From COBOL to Business Rules*; Aghajani et al.
(ICSE 2019, 2020) documentation defects and practitioner priorities; Lethbridge,
Singer & Forward (2003) how engineers actually use documentation.

**Visualisation** — Moody (2009) *The Physics of Notations*; Shneiderman (1996)
overview-first, zoom-and-filter; Purchase (1997, 2002) graph drawing aesthetics;
Shneiderman et al. (1977) on flowchart utility.

**Graphs** — Yamaguchi et al. (IEEE S&P 2014) Code Property Graphs; jQAssistant
(scan → graph → concepts + constraints); Lehnert, *A review of software change
impact analysis*.

---

## Licence

See `LICENSE`. The vendored ANTLR4 Oracle PL/SQL grammar is from
`antlr/grammars-v4` under Apache 2.0; see `.claude/scripts/vendor/` for its
notice and the post-generation patch this project applies.
