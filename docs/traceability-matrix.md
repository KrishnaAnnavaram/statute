# Traceability Matrix

Every substantive claim in this documentation package, mapped to its repository evidence.

**Evidence types:** `Confirmed from implementation` · `Confirmed from configuration` · `Confirmed from tests` · `Confirmed from existing documentation` · `Confirmed from stakeholder` · `Measured` · `Architectural inference` · `Not found in the current repository`

> **One claim in this package is not derived from the repository.** The expansion of the project name — **STATUTE** = *Structured Translation & Analysis Tool for Undocumented Transactional Engines* — appears nowhere in the code, comments, specifications or the original README. It was supplied directly by the project owner and is labelled `Confirmed from stakeholder` throughout. It is recorded here so a future reader knows it cannot be verified against the code.

## Contents

- [1. System-wide claims](#1-system-wide-claims)
- [2. Per-agent claims](#2-per-agent-claims)
- [3. Formulas and thresholds](#3-formulas-and-thresholds)
- [4. Claims that are inferences, not facts](#4-claims-that-are-inferences-not-facts)
- [5. Verified absences](#5-verified-absences)

---

## 1. System-wide claims

| Claim | Evidence location | Type | Confidence |
|---|---|---|---|
| Eight pipeline stages | `.claude/scripts/0[1-8]_*.py` | Confirmed from implementation | High |
| Three shared libraries | `lib_business_language.py`, `lib_graph_model.py`, `lib_graph_language.py` | Confirmed from implementation | High |
| ~9,142 lines of Python | `wc -l .claude/scripts/*.py` | Measured | High |
| Two third-party dependencies only | Import analysis: `antlr4`, `sqlglot` | Confirmed from implementation | High |
| Zero model calls | No model client import anywhere | Confirmed from implementation | High |
| Zero network calls | No `requests`/`urllib`/`http` import | Confirmed from implementation | High |
| Zero environment variables | No `os.environ`/`getenv` use | Confirmed from implementation | High |
| Zero database drivers | No `neo4j`/`psycopg`/`sqlalchemy`/`cx_Oracle` import | Confirmed from implementation | High |
| Zero uses of `logging` | Repository-wide grep | Confirmed from implementation | High |
| Versioned runs, pointer-after-write | `generate_run_version` + `latest.json` in all 8 `main()` | Confirmed from implementation | High |
| 414 test checks across 8 suites | All suites executed | Confirmed from tests | High |
| One evaluation harness | `tests/evaluate_rules.py` | Confirmed from tests | High |
| `reference/` is not part of the system | `.gitignore` | Confirmed from configuration | High |
| Reference corpus: 7 files, 603 code lines | `output/inventory/<run>/inventory-artifact.json` | Measured | High |
| Output: 41 rules, 353 graph nodes, 769 relationships | Live artefacts | Measured | High |

---

## 2. Per-agent claims

### Agent 01 — Inventory

| Claim | File | Function / line | Type |
|---|---|---|---|
| `file_id` = slug + SHA-256 of **path** | `01_inventory.py` | `make_file_id` L133 | Confirmed from implementation |
| Role classification is content-driven | `01_inventory.py` | `classify_file_role` L214 | Confirmed from implementation |
| 25 content hints | `01_inventory.py` | `extract_content_hints` L289 | Confirmed from implementation |
| Encoding fallback on read | `01_inventory.py` | `read_file_safe` L156 | Confirmed from implementation |
| Exits 1 on invalid directory | `01_inventory.py` | L589–594 | Confirmed from implementation |
| 22 test checks; golden-fixture diff | `tests/test_inventory.py` | — | Confirmed from tests |

### Agent 02 — Parser

| Claim | File | Function / line | Type |
|---|---|---|---|
| ANTLR4 vendored grammar | `02_parser.py` | `_VENDOR_DIR` L38 | Confirmed from implementation |
| sqlglot for DML decomposition | `02_parser.py` | `enrich_with_sqlglot` | Confirmed from implementation |
| Two-pass design | `02_parser.py` | `discover_objects` → `extract_statements` | Confirmed from implementation |
| Routing constants | `02_parser.py` | L62–63 | Confirmed from implementation |
| Builtin allowlist | `02_parser.py` | `_ORACLE_BUILTIN_PROCEDURES` L622 | Confirmed from implementation |
| Four CFG edge types | `02_parser.py` | `build_cfg` | Confirmed from implementation |
| No condition text stored on `IF` | Live artefact — `IF` carries only `nesting_depth` | — | Confirmed from implementation |
| Grammar requires `this.`→`self.` patch | `vendor/plsql_grammar/NOTICE.md` | — | Confirmed from existing documentation |
| 31 test checks | `tests/test_parser.py` | — | Confirmed from tests |

### Agent 03 — Data

| Claim | File | Function / line | Type |
|---|---|---|---|
| Two-axis enforcement model | `03_data.py` | `parse_constraint_state`, `enforcement_summary` | Confirmed from implementation |
| Content-driven DDL routing | `03_data.py` | `DDL_ROLES` L132, `DDL_CONTENT_HINTS` L143 | Confirmed from implementation |
| `original_text_of` preserves whitespace | `03_data.py` | `original_text_of` | Confirmed from implementation |
| Oracle → normalized → PySpark type triple | `03_data.py` | `map_oracle_type` | Confirmed from implementation |
| FK field is `references_table` | Live artefact | — | Confirmed from implementation |
| Owns the ERD | `03_data.py` writes `erd.mmd`; Agent 06 only indexes it | — | Confirmed from implementation |
| 76 test checks | `tests/test_data.py` | — | Confirmed from tests |

### Agent 04 — Logic

| Claim | File | Function / line | Type |
|---|---|---|---|
| Cyclomatic = decisions + 1 | `04_logic.py` | `compute_cyclomatic` | Confirmed from implementation |
| Cognitive complexity, nesting-weighted | `04_logic.py` | `compute_cognitive` | Confirmed from implementation |
| Backward slices with control ancestors | `04_logic.py` | `slice_for_variable` | Confirmed from implementation |
| Transaction hazard analysis | `04_logic.py` | `analyse_transactions` | Confirmed from implementation + live artefact |
| Dead code explicitly NOT detected | `.claude/agents/4_logic_agent.md`; artefact `note_on_no_internal_callers` | — | Confirmed from existing documentation |
| 46 test checks | `tests/test_logic.py` | — | Confirmed from tests |

### Agent 05 — Rules

| Claim | File | Function / line | Type |
|---|---|---|---|
| Nine mining sources | `05_rules.py` | `mine_from_*` + `source.kind` values | Confirmed from implementation |
| Enforcement → confidence mapping | `05_rules.py` | `_ENFORCEMENT_TO_CONFIDENCE` L176 | Confirmed from implementation + tests |
| Derivation threshold = 2 | `05_rules.py` | L603 | Confirmed from implementation |
| `_assigns_variable` guard | `05_rules.py` | `_assigns_variable` | Confirmed from implementation |
| Dedup prefers obligations | `05_rules.py` | `deduplicate` | Confirmed from tests |
| Degrades without Agent 04 | `05_rules.py` | `main` try/except | Confirmed from implementation |
| F1 0.593 → 1.000; blind 0.588 / recall 0.400 | `BASELINE.json`, `README.md` | — | Confirmed from tests + documentation |
| 33 test checks | `tests/test_rules.py` | — | Confirmed from tests |

### Agent 06 — Diagram

| Claim | File | Function / line | Type |
|---|---|---|---|
| Model-then-render split | `06_diagram.py` | `DiagramSpec`, `MermaidRenderer` | Confirmed from implementation |
| Node budget = 40 | `06_diagram.py` | `DEFAULT_NODE_BUDGET` L99 | Confirmed from implementation |
| Never-collapse invariant | `06_diagram.py` | `_NEVER_COLLAPSE` | Confirmed from implementation + tests |
| Second collapse tier removed | `06_diagram.py` | `collapse_runs` comment | Confirmed from implementation |
| Stage fails on validation problem | `06_diagram.py` | `main` `sys.exit(1)` | Confirmed from implementation |
| 100% decision labels / branch traceability | Live `diagrams_artifact.json` `quality` | — | Measured |
| 52 test checks | `tests/test_diagram.py` | — | Confirmed from tests |

### Agent 07 — Synthesis

| Claim | File | Function / line | Type |
|---|---|---|---|
| SBVR alethic vs deontic | `07_synthesis.py` | `rule_modality`, `_DDL_KINDS` | Confirmed from implementation + tests |
| Verification method derived | `07_synthesis.py` | `verification_method` | Confirmed from implementation + tests |
| Provenance regex defect (`[^.]*?`) | `07_synthesis.py` | `_PROVENANCE_TAIL` + test | Confirmed from tests |
| `NO` abbreviation defect | `lib_business_language.py` | `ABBREVIATIONS` comment | Confirmed from implementation |
| Operator/identifier ordering defect | `lib_business_language.py` | `humanise_condition` comment | Confirmed from implementation |
| Annotations read-only | `07_synthesis.py` | `load_annotations` docstring | Confirmed from implementation |
| Determinism statement enforced | `tests/test_synthesis.py` | honesty group | Confirmed from tests |
| 86 test checks | `tests/test_synthesis.py` | — | Confirmed from tests |

### Agent 08 — Graph

| Claim | File | Function / line | Type |
|---|---|---|---|
| One model, two views | `lib_graph_model.py` used by export and `--ask` | — | Confirmed from implementation |
| Node-vs-property rule | `lib_graph_model.py` | module docstring | Confirmed from implementation |
| Code Property Graph layer | `lib_graph_model.py` | CFG edge mapping | Confirmed from implementation |
| Statement-level column edges | `lib_graph_model.py` | DML loop | Confirmed from implementation |
| Endpoint guard | `lib_graph_model.py` | `Graph.rel` | Confirmed from implementation + tests |
| Refusal over generation | `lib_graph_language.py` | module docstring, `ask` | Confirmed from implementation + tests |
| Advertised-question invariant | `tests/test_graph.py` | `test_advertised_questions_are_answerable` | Confirmed from tests |
| **`TRANSITIONS_TO` not emitted** | `lib_graph_model.py` `pass`; live artefact | — | Confirmed from implementation |
| 68 test checks | `tests/test_graph.py` | — | Confirmed from tests |

---

## 3. Formulas and thresholds

| Formula / threshold | Value | Location | Type |
|---|---|---|---|
| `file_id` composition | slug + SHA256(path)[0:8] | `01_inventory.py:133` | Confirmed from implementation |
| `statement_id` composition | `file_id__object_id__STMT_nnnn` | `02_parser.py` `extract_statements` | Confirmed from implementation |
| Cyclomatic complexity | *M = D + 1* | `04_logic.py` `compute_cyclomatic` | Confirmed from implementation |
| `CYCLOMATIC_THRESHOLD` | 10 | `04_logic.py:71` | Confirmed from implementation |
| `COGNITIVE_THRESHOLD` | 15 | `04_logic.py:73` | Confirmed from implementation |
| `_DERIVATION_COMPLEXITY_THRESHOLD` | 2 | `05_rules.py:603` | Confirmed from implementation |
| `DEFAULT_NODE_BUDGET` | 40 | `06_diagram.py:99` | Confirmed from implementation |
| `LINE_TOLERANCE` | 2 | `tests/evaluate_rules.py:45` | Confirmed from tests |
| Enforcement → (signal, confidence, review) | 3 mappings | `05_rules.py:176` | Confirmed from implementation |
| Clause scoring weights | 2 and 1 | `05_rules.py` `describe_comparison` | Confirmed from implementation |
| Precision / Recall / F1 | standard | `tests/evaluate_rules.py` | Confirmed from tests |
| Hot-column concept | > 2 dependent units | `08_graph.py` `CONCEPTS` | Confirmed from implementation |

**These five constants plus `LINE_TOLERANCE` are the complete set of numeric thresholds in the repository.** Verified by grep for constant assignments.

---

## 4. Claims that are inferences, not facts

Labelled throughout as `Architectural inference`. Listed here so a reviewer can challenge them directly.

| Inference | Supporting evidence | Confidence |
|---|---|---|
| The architecture is a filesystem-mediated batch pipeline | Each script has an independent `main()`; no module imports another stage; `load_run` reads artefacts | High |
| There is no orchestrator | Absence of any orchestration module, workflow definition, or framework import | High |
| Python floor is 3.11+ | `X \| Y` union type-hint syntax; no manifest declares it | Medium |
| Agent 01 time complexity O(N × L) | Reading `discover` and `process_file`; no profiling data exists | Medium |
| Agent 04 slicing complexity O(V × S) | Reading `slice_for_variable`; no profiling data | Medium |
| Agent 08 traversal is O(E) per hop | `Graph.out`/`inn` perform linear scans over the relationship list | High |
| Agents 03 and 04 could run in parallel | Neither reads the other's output | High |
| Regex classification chosen to avoid inverting the dependency on Agent 02 | Agent 02 depends on Agent 01's routing; no comment states this | Low |

---

## 5. Verified absences

Everything below was checked and is **not present**. Each is stated as `Not found in the current repository.` in the documents.

| Absent | How verified |
|---|---|
| Any LLM / model client | Import analysis across all scripts |
| Prompts, prompt templates, system prompts | No prompt file; no model to receive one |
| Temperature, token limits, structured-output parsers | No model |
| Prompt-injection controls | No model |
| Orchestrator, workflow engine, DAG definition | No such module or config |
| Shared state object, session, thread, checkpointer | No state class |
| Environment variables, `.env`, config files | Grep + filesystem check |
| Secrets, credentials, tokens, API keys | Grep |
| Network libraries | Import analysis |
| Database drivers / connections | Import analysis |
| `logging` module, log levels, structured logs | Grep |
| Metrics backend, dashboards, alerting | Filesystem check |
| Trace identifiers | Grep |
| Dockerfile, docker-compose | Filesystem check |
| CI/CD pipeline definitions | Filesystem check |
| `requirements.txt`, `pyproject.toml`, lockfile | Filesystem check |
| Test framework config (pytest/tox/unittest) | Filesystem check |
| JSON Schema files for artefacts | Filesystem check |
| Threat model / security review document | Filesystem check |
| Authentication / authorization code | Import + grep |
| `subprocess` / `os.system` / `eval` / `exec` in pipeline scripts | Import analysis |

---

*Compiled during repository inspection. Any claim not appearing here should be treated as unsupported and challenged.*
