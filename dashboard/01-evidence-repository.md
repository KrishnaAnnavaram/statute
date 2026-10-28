# Appendix A — Repository Evidence

Supporting evidence for [00-statue-dashboard-research-report.md](00-statue-dashboard-research-report.md). Collected 2026-09-30 / 2026-10-01 (UTC). **Nothing in the repository was modified**: 181 files under `output/`, `.claude/scripts`, `tests/` and `src/` were hashed before and after all execution and were identical; `git status` showed only the new `dashboard/` folder. All execution wrote to a scratch directory outside the repository.

Script paths are relative to `.claude/scripts/`. **[V]** verified in code or by execution; **[I]** inferred.

## Contents

- [A1. Naming and identity](#a1-naming-and-identity)
- [A2. Documentation drift register](#a2-documentation-drift-register)
- [A3. Live execution trace](#a3-live-execution-trace)
- [A4. Observable signals catalogue (stdout, stderr, exit codes, files)](#a4-observable-signals-catalogue)
- [A5. Write order, atomicity and timing semantics](#a5-write-order-atomicity-and-timing-semantics)
- [A6. Failure probes](#a6-failure-probes)
- [A7. Tests and evaluation](#a7-tests-and-evaluation)
- [A8. Identifier schemes](#a8-identifier-schemes)
- [A9. MARS inspection facts](#a9-mars-inspection-facts)
- [A10. Branch state](#a10-branch-state)

---

## A1. Naming and identity

| Name | Where it appears |
|---|---|
| **STATUTE** (*Structured Translation & Analysis Tool for Undocumented Transactional Engines*) | README (lines 3, 240) and `docs/` only; introduced in commit `169ec0e`; appears in no code |
| "Statue" | the research brief only |
| `statute` | GitHub remote `KrishnaAnnavaram/statute`; local folder |
| `plsql_to_brd` | committed inventory `source_dir` and 7 × `abs_path`; OpenWiki `index.md:10`, `quickstart.md:4` (the directory does not exist; a sibling `plsql-to-brd` does) |
| "PL/SQL to BRD reverse-engineering pipeline" | initial commit; master doc; `01_inventory.py:24` ("SQL → BRD pipeline") |
| "PL/SQL Banking System" | default `--system-name` of 07 (`07_synthesis.py:1243`) — the BRD title |

Per-stage identifiers (a console must normalise these):

| Script | Agent `name` | Spec file | `run_meta.stage` / `pipeline_stage` | Output dir / main artifact | Script docstring title |
|---|---|---|---|---|---|
| `01_inventory.py` | `1_inventory_plsql` | `1_inventory_plsql_agent.md` | `01_inventory` | `inventory/inventory-artifact.json` | "Stage 0: INVENTORY" |
| `02_parser.py` | `2_parser` | `2_parser_agent.md` | `2_parser` | `parser/parser_artifact.json` | "Stage 2" |
| `03_data.py` | `3_data` | `3_data_agent.md` | `3_data` | `data/data_artifact.json` | "Stage 3" |
| `04_logic.py` | `4_logic` | `4_logic_agent.md` | `4_logic` | `logic/logic_artifact.json` | "Stage 4" |
| `05_rules.py` | `5_rules` | `5_rules_agent.md` | `5_rules` | `rules/rules_artifact.json` | "Stage 5" |
| `06_diagram.py` | `6_diagram` | `6_diagram_agent.md` ("Visual model agent") | `6_diagram` | `diagram/diagrams_artifact.json` | "Stage 6: VISUAL MODEL" |
| `07_synthesis.py` | `7_synthesis` | `7_synthesis_agent.md` | `7_synthesis` (brd_index has none) | `final_report/brd.md` | "Stage 7: BRD SYNTHESIS" (agent 2 calls it "BRD Generator") |
| `08_graph.py` | **`8_neo4j_graph`** | **`8_graph_agent.md`** | `8_graph` | `graph/graph_artifact.json` | "Stage 8: KNOWLEDGE GRAPH" |

`schema_version` by artifact: 2.0, 1.0, 2.0, 2.0, 1.0, 2.0, 2.0, 2.0. The `8_neo4j_graph` name comes from the reference COBOL harness (`reference/.claude/agents/8_neo4j_graph_c.agent.md`); the pipeline imports no Neo4j library.

---

## A2. Documentation drift register

Severity: **H** high, M medium, L low. "Doc" = documented claim; "Actual" = verified state.

| # | Category | Doc (file:line) | Actual (evidence) | Sev |
|---|---|---|---|---|
| 1 | Isolation / error handling | "Any stage re-runnable in isolation" (README:1304; ADR-002). No "source missing" case in README error table (1085-1095) | Committed `abs_path` → non-existent `…\plsql_to_brd\src`. Running 04 → 05 on committed artifacts: **exit 0, slices 25→0, rules 41→18, SME-review 3→14, no warning** (`04_logic.py:96-102`, `05_rules.py:65-71`, `06_diagram.py:192-198` swallow `OSError`); 02 (`:765`) and 03 (`:1270`) crash | **H** |
| 2 | Output correctness | "Diagrams never imply an ordering that doesn't exist" (README:1313, ADR-011); agent 4 calls sequential rendering of exclusive branches "actively misleading" | `02_parser.py:556-558` chains siblings sharing `parent_id` without grouping by arm; **18 of 86 SEQUENCE edges cross IF/ELSIF arms or handlers**; `flow_SP_PROCESS_MONTHLY_INTEREST_CREDIT.mmd` draws N7→N8→N9→N10 ("Set Interest Rate 3.0 → 3.5 → 4.0 → 4.5"); embedded in `brd.md`, emitted as graph `FOLLOWS`. No test asserts it | **H** |
| 3 | Spec / skill vs code | `1_inventory_plsql_agent.md:2-10, 53-66, 84-91, 109-116`; `file-catalog/SKILL.md:4-10, 68-70`; `reference-graph/SKILL.md:4-11, 101-152`: `object_registry`, typed `dependency_graph`, `issues[]`, `meta.*`, hard-fail invariant, `file_id` = dominant object id | `01_inventory.py:648-661` emits `pipeline_stage, schema_version, generated_at, source_dir, cli_args, summary, file_index, file_metadata` only; exits only at `:592, :595`; `file_id` = SLUG + SHA256(path)[:8] (`:130-152`). `tests/test_inventory.py:22-28` acknowledges the gap | **H** |
| 4 | Deliverable fact | 603 lines of code (README:125) | `brd.md:84` "7 files, **0 lines of code**" — `07_synthesis.py:1175` reads `total_lines_of_code`; 01 writes `total_code_lines` (`:464`) | **H** |
| 5 | Agent command | `1_inventory_plsql_agent.md:44-45, 53`: `--output OUTPUT_DIR/…`, default `./checkpoints/`, comma-separated excludes | `--output` skips `run_meta` + `latest.json` → 02 raises `FileNotFoundError` (tested); `--exclude "00_*,01_*"` excluded 0 files (`nargs="+"`, `:560-566`); `checkpoints/` comes from the archive | **H** |
| 6 | CI / secrets / LLM | "Verified absent: model calls · network · env vars · secrets · CI" (README:270, 1228, 1254, 1293; master:167, 669; known-gaps:71; traceability-matrix:190-203) | `src/.github/workflows/openwiki-update.yml` (commit `d0d7fbc`): daily cron, `contents/pull-requests: write`, secrets `OPENROUTER_API_KEY`, `OPENWIKI_LANGSMITH_API_KEY`, `LANGSMITH_API_KEY` (names only), model `z-ai/glm-5.2`, LangSmith tracing. Under `src/` → never discovered by GitHub; no `openwiki/update` branch exists | M |
| 7 | Provenance | "Run versioning + `upstream` provenance in every artefact" (README:1258; master:453, 673, 747) | inventory none (n/a); graph `{"run_selector":"latest"}` (`08_graph.py:378`), graph `run_meta` no upstream (`:395-397`); rules omit `logic_run_version` (`05_rules.py:1166-1167`) although 6 rules derive from logic slices | M |
| 8 | Workflow | "Each stage prints … the exact next command" (README:161, 925; system-overview:25; master:324, 399, 416; ADR-002) | Only `01_inventory.py:716-721` | M |
| 9 | Configuration | `--<stage>-root`, `--<stage>-run` (README:1112; master:805) | 07 (`:1234-1240`) and 08 (`:343-350`) have one `--run`; pinning one stage fails; `--diagram-run` rejected (tested) | M |
| 10 | Dependencies | 4 reads Agent 3 / runs after `3_data` (`4_logic_agent.md:5, 14`; `3_data_agent.md:14`; agent-04 doc) | `04_logic.py:805-811` has no data argument | M |
| 11 | Graph equivalence | "local answers and Neo4j answers cannot disagree" (README:349; graph README:65; `08_graph.py:33`) | `_impact` (`lib_graph_language.py:107-151`) adds statement rows, `CONSTRAINS_TABLE`, `POPULATES`, `REFERENCES`; its Cypher (`:288-293`) matches `[:CONSTRAINS]` (0 edges) → would miss BR-014 | M |
| 12 | Graph schema | 13 labels / 22 types; `ON_ERROR_REACHES` error-path layer | 26 types defined, 22 emitted; `CALLS`, `CONSTRAINS`, `POPULATES`, `ON_ERROR_REACHES` = 0; all 15 `EXCEPTION_EDGE`s (`from:"*"`) skipped at `lib_graph_model.py:192-193` | M |
| 13 | Orchestration | "No orchestrator"; "the only trigger is a human" (README:229, 255) | BRD: "orchestrated by an AI agent harness. The harness runs the stages and reviews the code" (`07_synthesis.py:516-518, 1001-1004`; `brd.md:82, 2508`) | M |
| 14 | Dependencies | "No version is pinned or recorded anywhere" (known-gaps:65) | `vendor/plsql_grammar/NOTICE.md` requires `antlr4-python3-runtime==4.13.2`; `PlSqlParser.py:16052` `checkVersion("4.13.2")`. Still no manifest | M |
| 15 | Two specifications | OpenWiki `business-rules.md:10`, `INSTRUCTIONS.md:73` present BR-01…BR-20 as stable IDs | Pipeline: BR-001…BR-041; OpenWiki BR-14 (savings-only crediting) ≠ pipeline BR-014 (status CHECK); OpenWiki orphan list omits `LOAN_MASTER`; 3 vs 1 inferred FKs | M |
| 16 | OpenWiki self-description | `src/CLAUDE.md:10`: scheduled workflow refreshes the wiki; `overview.md:81` "pipeline code not in this checkout"; `quickstart.md:52` "no automated test suite" | Workflow inert; `.last-update.json` shows `command:init`, `model:claude-opus-4-8`, `gitHead:169ec0e` — generated treating `src/` as root | M |
| 17 | Line citations | `docs/agents/agent-01-inventory.md:76-103, 211-222`; ADR-003 `01_inventory.py:133` | 10 of 11 wrong (`should_exclude` 411→316, `infer_complexity` 355→274, `generate_run_version` 401→304, `discover` 470→484; `compute_sha` → `compute_sha256` :121); ADR-003 actual 130 | M |
| 18 | Repo layout | `output/` "versioned runs (gitignored)" (README:299; master:198) | Commit `2418542` committed `output/` (81 files); `.gitignore:1-3` | M |
| 19 | Evaluation | "First blind held-out F1 **0.588**" (README:668, 1319; master:729, 888) | No fixture records 0.588; `BASELINE.json` F1 0.5926; harness now 1.000 on all four incl. `held_out` | L |
| 20 | Counts | Badge "414 tests" | 414 runtime `check()` PASS lines; 50 `def test_` functions | L |
| 21 | Internal contradiction | "76 checks — the largest suite" (README:531) | README:830: synthesis (86) is largest | L |
| 22 | Counts | "(11 more types)" (README:870) | 12 more | L |
| 23 | Counts | "docs/ 16 documents, 6,290 lines" (README:300, 1429) | 15 files, 5,945 lines | L |
| 24 | Stale spec numbers | `8_graph_agent.md:31` "Tests 56"; `6_diagram_agent.md:94` fallback "1/128" | 68 graph checks; `fallback_labels: 2`, `total_nodes: 132` | L |
| 25 | Stale spec | `7_synthesis_agent.md:46` sign-off block | Removed in `0881578` | L |
| 26 | Naming | "BRD Generator", "after 1_inventory" (`2_parser_agent.md:14-15, 148, 153, 175`) | Stage is `7_synthesis`; agent is `1_inventory_plsql`; consumer table omits 4, 5, 8 | L |
| 27 | Abandoned feature | "Zero LLM calls" (`01_inventory.py:8`) | `stage2_enrich_hint` "for downstream token budget planning" (batch 25, `:471-476`), golden-tested, consumed by nothing; leftover of archived `02_enrich.py` | L |
| 28 | Counts | "25 regex signals" (README:401) | 30 patterns (`01_inventory.py:50-88`) | L |
| 29 | Thresholds | "complete set … verified exhaustive" (README:1035) | inline thresholds at `01_inventory.py:288, 294, 297`, `05_rules.py:698` | L |
| 30 | Formula | Cyclomatic counts `n_case_when` (README:569, 1054) | `04_logic.py:206-210` counts CASE statements only; a 5-WHEN CASE expression counts 0 | L |
| 31 | Traceability | "Every rule cites file and line" (README:1242) | BR-014 `line: None` (`brd.md:2384`) | L |
| 32 | Example | "`Balance below 100,000?`" (README:735) | Actual label `rec.balance < 100000?`; two functions named `humanise_condition` | L |
| 33 | Citation | `this.`→`self.` patch "documented in NOTICE.md" | Not in NOTICE.md | L |
| 34 | Environment | Python 3.11+ "inferred from `X \| Y`" | That syntax needs 3.10 | L |
| 35 | Envelope | `design_references` "emitted into artefacts" (references.md:17) | 07 renders it only in `brd.md` Appendix C | L |
| 36 | `reference/` | "design guidance only" (master:204) | `05_rules.py:39-42` cites `reference/.claude/skills/…`; the paths are in the committed `rules_artifact.json` but gitignored | L |
| 37 | Gap wording | "`TRANSITIONS_TO` relationship described in the specification" | The `pass` loop is real (`lib_graph_model.py:340-346`) but `TRANSITIONS_TO` appears in no spec or code before docs commit `169ec0e` | L |
| 38 | Test claim | No-LLM "enforced by tests/test_synthesis.py" (master:101) | `test_synthesis.py:253` only checks the BRD contains a phrase | L |
| 39 | Layout | `src/` = "7 PL/SQL files" (README:294) | 43 tracked files (7 `.sql` + 36 OpenWiki/workflow/agent docs); harmless to stage 1 (`rglob("*.sql")`), but `DEFAULT_EXCLUDE_PATTERNS` (`:106-114`) don't exclude them and `src/CLAUDE.md` may be loaded by Claude when subagents read `src/` | L |
| 40 | Agent 4 output | `complexity_score` (`4_logic_agent.md:51`) | `complexity.{cyclomatic, cognitive}` (`04_logic.py:793`) | L |
| 41 | Error handling | README §22 "Missing optional artefact → degrade + record" | 06 records; 04, 05, 08 do not (A6 probes d, e6) | **H** |
| 42 | Parse failure | Agent 2: malformed object "written with `parse_status: failed`" | Written `success` with a degenerate tree; `failed` only on a Python exception; Pass A failures abort (A6 probe c) | **H** |

### Documented commands vs real CLI

| Command (source) | Works as written? |
|---|---|
| `pip install antlr4-python3-runtime sqlglot` (README:143) | Yes, unpinned (NOTICE requires 4.13.2) |
| `01_inventory.py src` … `08_graph.py` (README:151-158) | **Yes** — all exit 0; byte-identical to committed output except timestamps and paths |
| `cat output/final_report/latest.json` | Yes |
| `08_graph.py --ask "what breaks if I change ACCOUNTS.BALANCE"` | Yes — 10 results |
| `--list-questions`; `--ask … --json`; unmatched → exit 2 | Yes |
| `for t in tests/test_*.py; do python "$t"; done` | Yes (bash): 414 PASS, 0 FAIL |
| `python tests/evaluate_rules.py` | Yes: P/R/F1 1.000 (34/34); `--baseline`/`--compare` undocumented |
| Agent-1 `--output OUTPUT_DIR/…`, default `./checkpoints/` | Runs; **stage 2 cannot consume it** |
| Agent-1 comma-separated excludes | Accepted; excludes nothing |
| Agent-2 `02_parser.py --inventory-root --inventory-run --output-root` | Yes |
| `--<stage>-run` | Stages 2–6 only |

### `run_meta` shape by stage (no document defines a contract)

| Stage | `stage` | summary key | `upstream` |
|---|---|---|---|
| 01 | `01_inventory` | `stats_summary` (3 keys) + `source_dir`, `cli_args`, `output_file` | absent |
| 02 | `2_parser` | `stats_summary` | inventory |
| 03 | `3_data` | `stats_summary` (23 keys) | inventory, parser |
| 04 | `4_logic` | `stats_summary` | parser, inventory |
| 05 | `5_rules` | `stats_summary` | parser, data, inventory (**no logic**) |
| 06 | `6_diagram` | `quality` | all five (null when absent) |
| 07 | `7_synthesis` | `counts` | all six |
| 08 | `8_graph` | `stats` | **absent** (artifact: `run_selector`) |

`status` is hard-coded `"success"` in all eight; no stage records a duration.

---

## A3. Live execution trace

### Environment

Python 3.11.9; `antlr4-python3-runtime` 4.13.2; `sqlglot` 30.18.0; pytest 9.0.2 (not usable for these suites). `PYTHONDONTWRITEBYTECODE=1`. Working directory: scratch; roots passed as relative `output/<stage>` — the same layout as the committed run (its `erd_reference` is `output\data\<rv>\erd.mmd`).

### Timeline (fresh run, 2026-10-01 UTC)

| # | Command (`S = .claude/scripts`) | start → end | wall s | exit | in-script s (rv → generated_at) | start-up s |
|---|---|---|---:|---:|---:|---:|
| 1 | `python S/01_inventory.py "<repo>/src" --output-root output/inventory --verbose` | 04:01:12.631 → 13.063 | 0.432 | 0 | n/a (both stamped at start) | 0.229 |
| 2 | `python S/02_parser.py --inventory-root output/inventory --output-root output/parser --verbose` | 04:01:19.103 → 52.899 | **33.796** | 0 | 32.393 | 0.823 |
| 3 | `python S/03_data.py … --output-root output/data --verbose` | 04:01:59.231 → 02:13.437 | **14.206** | 0 | 12.835 | 1.003 |
| 4 | `python S/04_logic.py … --verbose` | 04:02:18.740 → 19.009 | 0.270 | 0 | 0.015 | 0.166 |
| 5 | `python S/05_rules.py …` (no `--verbose` flag exists) | 04:02:19.779 → 20.052 | 0.273 | 0 | 0.016 | 0.175 |
| 6 | `python S/06_diagram.py …` | 04:02:27.209 → 27.638 | 0.430 | 0 | 0.026 | 0.227 |
| 7 | `python S/07_synthesis.py …` | 04:02:28.547 → 28.941 | 0.394 | 0 | **−0.028** (generated_at taken before build, run_version after) | 0.298 |
| 8 | `python S/08_graph.py …` | 04:02:29.783 → 30.091 | 0.308 | 0 | 0.033 | 0.183 |
| 8q/8a/8j | `--list-questions` / `--ask …` / `--ask … --json` | — | 0.24–0.27 | 0 | — | — |
| 8x | `--ask "what is the weather"`, `--ask "…ACCOUNTS.NOPE" --json` | — | 0.35 / 0.27 | **2** | — | — |

Parser + data ≈ 97 % of compute (2.2× slower than the committed run on this machine; not investigated). `--ask`/`--list-questions` create no run directory.

### Files written (81 total: 73 in run directories + 8 `latest.json`)

inventory: `inventory-artifact.json` 8,626 B · parser: `parser_artifact.json` 992 B + 5 `raw_structure` files (13.5–51.2 KB) · data: `data_artifact.json` 131,450 B, `erd.mmd` 4,351 B · logic: `logic_artifact.json` 4,022 B + 5 `program_logic` files · rules: `rules_artifact.json` 55,845 B · diagram: `diagrams_artifact.json` 21,338 B + 7 `.mmd` (354–3,434 B) · final_report: `brd.md` 122,488 B, `brd_index.json` 60,989 B, `gaps_register.json` 9,320 B · graph: `import.cypher` 260,379 B, `README.md`, `graph_artifact.json`, 13 node CSVs, 22 relationship CSVs. Plus `run_meta.json` and `latest.json` per stage.

`latest.json` (identical shape for all stages): `{"run_version": "2026-10-01T04.01.19.926Z", "path": "2026-10-01T04.01.19.926Z/parser_artifact.json", "updated_at": "2026-10-01T04:01:52.319420+00:00"}`.

### Verbatim stdout (selected)

```
[01_inventory] Complete.
  Source dir : E:\Virtusa Projects\statute\src
  Output     : output\inventory\2026-10-01T04.01.12.860Z\inventory-artifact.json
  Files found: 7 total, 0 excluded, 7 OK, 0 skipped, 0 with warnings
  Lines      : 940 total, 603 code
  Roles      : {'schema_ddl': 1, 'seed_data': 1, 'function': 1, 'procedure': 4}
  Complexity : {'medium': 7}
  Run version: 2026-10-01T04.01.12.860Z
  Latest ptr : output\inventory\latest.json

  Next step  : python .claude/scripts/02_parser.py --inventory-root output/inventory --inventory-run 2026-10-01T04.01.12.860Z
```

```
=== PL/SQL Parser Agent Complete ===
Objects parsed        : 5
  Package members      : 0
Statements extracted   : 124
Dynamic SQL blocks     : 0   (flagged for review)
Unresolved calls       : 0
Parse errors           : 0
Output                 : output\parser\2026-10-01T04.01.19.926Z\parser_artifact.json
=====================================
```

```
=== Diagram Agent Complete ===
Data-flow map          : 1
State models           : 1
Process flows          : 5
ERD (from Agent 3)     : indexed
Decision labels tier-1 : 100%
Branch traceability    : 100%
Largest diagram        : 45 nodes (budget 40)
Output                 : output\diagram\2026-10-01T04.02.27.436Z\diagrams_artifact.json
==============================
```

```
=== BRD Synthesis Complete ===
Capabilities documented : 5
Requirements            : 41
Glossary terms          : 21
Traceability rows       : 41
Open matters            : high 4, medium 8, low 9
Annotations applied     : 0
Document                : output\final_report\2026-10-01T04.02.28.845Z\brd.md
Machine index           : output\final_report\2026-10-01T04.02.28.845Z\brd_index.json
========================================
```

Stage 8 prints node and relationship counts per label/type (353 / 769), 12 questions, 4 blind spots. `--ask` text output includes "Equivalent Cypher"; redirected stdout is cp1252 (em-dash → byte 0x97).

### Determinism

Both trees contain the same 81 relative paths. **56 files are byte-identical** (all `raw_structure`, `program_logic`, `.mmd`, `erd.mmd`, `gaps_register.json`, graph CSVs, `import.cypher`, graph `README.md`); **the other 25 are identical after normalising** run_version stamps, ISO timestamps and the source path (`plsql_to_brd` → `statute`). Per-file sha256 values in the inventory match: `src/` has not drifted since the committed run.

### Inter-invocation gaps in the committed run

| Transition | Gap (prev `generated_at` → next `run_version`) | Next stage in-script |
|---|---:|---:|
| 1 → 2 | 7.083 s | 14.582 s |
| 2 → 3 | **0.700 s** | 5.601 s |
| 3 → 4 | 8.484 s | 0.014 s |
| 4 → 5 | **0.084 s** | 0.017 s |
| 5 → 6 | 8.299 s | 0.001 s |
| 6 → 7 | **0.115 s** | ≈ 0 s |
| 7 → 8 | 6.906 s | 0.010 s |

End-to-end 51.9 s; in-script ≈ 20.2 s; four long gaps = 30.8 s (59 %). Pattern = five invocations `[01] [02+03] [04+05] [06+07] [08]`. The fresh run's own separate tool calls produced 5.3–7.2 s gaps, consistent with agent tool-call round-trips [I]. Gaps are lower bounds (`run_version` is stamped after imports and input loading).

---

## A4. Observable signals catalogue

| Surface | Signals |
|---|---|
| Directory listing | `output/<stage>/<run_version>/` (sortable UTC); a directory without `run_meta.json` = crashed or in progress; `run_meta` newer than `latest.json` = unpublished |
| `latest.json` | `run_version`, `path`, `updated_at` |
| `run_meta.json` | `stage`, `run_version`, `generated_at`, `status` (always `success`), `upstream.*_run_version`, stage summary (`stats_summary` / `quality` incl. `degraded_inputs` / `counts` / `stats`), 01: `source_dir`, `cli_args` |
| Inventory | `summary.*` (files by status/role/complexity, `files_with_warnings`, `unreadable_files`, `codebase_features`); per file `sha256`, `size_bytes`, `last_modified`, `status`, `warnings` (free text, no severity), `encoding_used`, `file_role`, `line_counts` |
| Parser | `files_parsed/passthrough/skipped`, `stats`, `issues[]` (`severity`, `type`: `syntax_error`, `unresolved_reference`, `sqlglot_parse_failed`, `wrapped_object_skipped`; `file`, `line`, `column`, `message`); per object `parse_status` (`success`/`skipped_wrapped`/`failed`), `parse_issues`, statements, CFG |
| Data | 23–28-key stats; `issues[]` (`syntax_error`, `unresolved_type_reference`, `unknown_table_reference`, `unknown_column_reference`, `constraint_not_enforced`, `constraint_not_validated`) |
| Logic | stats; `shape_distribution`; per object complexity with `exceeds_threshold`; `transactions.hazards[]` (`COMMIT_INSIDE_LOOP`, `SAVEPOINT_PARTIAL_ROLLBACK` high; `NO_TRANSACTION_CONTROL` info); loop warnings |
| Rules | `stats.by_category`, `by_confidence`; per rule `confidence`, `signal_strength`, `requires_sme_review`, `is_enforced`, `source{kind, object_id, statement_id, line}` or DDL source; `error_handling_catalogue` |
| Diagram | `quality` (tier-1 %, traceability %, max nodes, fallback labels, leaked identifiers, `degraded_inputs`); `warnings[]` (`DIAGRAM_NOTE`, `DETAIL_COLLAPSED`, `OVERSIZE`); `diagram_index[*]` (`nodes`, `edges`, `budget`, `node_origins`, `rule_ids`) |
| Final report | `gaps[]` (`gap_id`, `gap_type`: FILE_WARNING, PARSE_FAILURE (critical), UNRESOLVED_CALL, UNDOCUMENTED_ENUM, SME_REVIEW_REQUIRED, MEDIUM_CONFIDENCE_RULE, CONSTRAINT_DISABLED, LOOP_RISK, TRANSACTION_HAZARD, HIGH_COMPLEXITY, DIAGRAM_OVERSIZE, DIAGRAM_DETAIL_COLLAPSED, DIAGRAM_NOTE; `severity` critical/high/medium/low; `detected_in`; `related_rule_ids`); `brd_index` requirements (`needs_review`, `confidence`, `owner`, `priority`), `traceability` |
| Graph | `stats`, `blind_spots[]` (`DYNAMIC_SQL`, `EXTERNAL_CALLERS`, `UNRESOLVED_CALLS`, `TRIGGER_SIDE_EFFECTS`), `supported_questions` |
| stdout | `=== … Complete ===` blocks with `Label : value` lines; `Output :` path; 01 `Run version:`, `Latest ptr:`, `Next step:`; `Parse errors :` (02, 03); `Degraded (missing) :` (06 only when degraded); `Largest diagram : N nodes (budget B)`; `Open matters : critical N, high N …` (07) |
| stderr | `--verbose` only for 01–04: `[ok ]`/`[excluded]`, `[discovering]`, `[parsing]`, `[parsing DDL]`, `[analysing]`; tracebacks; 01 `ERROR: …`; 06 `=== Diagram Agent FAILED validation ===` |
| Exit codes | 0 success (including degraded and parse-error runs); 1 crash or 06 validation failure; 2 `08 --ask` unmatched (collides with argparse usage errors) |
| Tests | `[PASS]`/`[FAIL]` lines; "All tests passed." or "N failure(s)"; exit code |

Never surfaced as gaps by 07: parser `parse_status: failed`, `sqlglot_parse_failed`, `wrapped_object_skipped`, and all of 03's `issues[]`.

---

## A5. Write order, atomicity and timing semantics

`run_version` = `datetime.now(utc)` formatted `YYYY-MM-DDThh.mm.ss.mmmZ` (duplicated `generate_run_version` in all 8 scripts: 01:304-313, 02:53, 03:123, 04:76, 05:47, 06:110, 07:132, 08:103). `generated_at` = `datetime.now(utc).isoformat()`. **All writes are direct (`write_text` / `open("w")`); no temp-file + rename; `latest.json` is overwritten in place.**

| Stage | `run_version` taken | `generated_at` taken | Write order | Residue on mid-run exception |
|---|---|---|---|---|
| 01 | start (611) | **start** (621) — no end time | mkdir (618) → artifact (663) → run_meta (684) → latest (692) | empty run dir |
| 02 | after loading inventory (746) | end (825) | mkdir `raw_structure` (749) → per-object (810) → artifact (832) → run_meta (841) → latest (844) | empty `raw_structure/` (Pass A) or partial object files (Pass B) |
| 03 | after loading inventory, parser, object files (1241) | end (1376) | mkdir (1243) → `erd.mmd` (1372) → artifact (1392) → run_meta (1396) → latest (1400) | empty dir, or `erd.mmd` alone |
| 04 | after loading (820) | end (877) | mkdir `program_logic` (823) → per-object (850) → artifact (888) → run_meta (892) → latest (896) | partial `program_logic/*` |
| 05 | after loading (1133) | end (1166) | mkdir (1135) → artifact (1175) → run_meta (1178) → latest (1182) | empty dir |
| 06 | after loading/indexing (1097) | after validation and `.mmd` writes (1160) | mkdir `diagrams` (1100) → every `.mmd` (1122) → **validation exit (1145-1149)** → artifact (1178) → run_meta (1182) → latest (1187) | `.mmd` files without artifact or meta |
| 07 | **after** building the document (1272) | **before** building (1187) → `generated_at < run_version` | loads + build → mkdir (1274) → `brd.md` (1276) → `brd_index.json` (1277) → `gaps_register.json` (1279) → run_meta (1283) → latest (1290) | no directory |
| 08 | after `build_graph` (373) | after export (383) | mkdir (375) → `nodes/`, `rels/` CSVs → `import.cypher` (227) → `README.md` (312) → artifact (392) → run_meta (396) → latest (400) | partial CSVs |

Concurrency [I]: two runs within one millisecond share a directory (`exist_ok=True`); concurrent runs race on `latest.json` (last writer wins); a reader can see a half-written `latest.json` (only 08 catches `JSONDecodeError`).

Source re-reads after stage 1 (none re-check sha256):

| Stage | Reads source? | Missing file | Non-UTF-8 |
|---|---|---|---|
| 02 | yes (`:765`, ANTLR `FileStream` strict UTF-8 `:117/776`) | abort | abort |
| 03 | yes (DDL `FileStream`; line reads; NEXTVAL/CURRVAL search across all files) | abort on DDL; swallowed for line reads | abort [I] |
| 04 | yes (`raw_snippet`) | **silent degradation** | abort [I] |
| 05 | yes | silent degradation | abort [I] |
| 06 | yes (labels, state transitions) | silent degradation | abort [I] |
| 07, 08 | no | — | — |

---

## A6. Failure probes

All in scratch directories; repository untouched.

| Probe | Setup | Exit | Visible signal | Residue |
|---|---|---:|---|---|
| a | 02 with empty / missing inventory root, or a bad pinned run | 1 | raw traceback `FileNotFoundError: No inventory runs found …` / `Inventory run not found …`; empty stdout; ~1.0 s (ANTLR import) | none (fails before mkdir) |
| b1 | 01 on nonexistent dir / on a file | 1 | `ERROR: directory not found` / `ERROR: not a directory` | none |
| b2 | 01 on an **empty** directory | **0** | `Files found: 0 total`; `run_meta.status: "success"`; 02 on it also exits 0 with `Objects parsed : 0` | full "successful" runs of nothing; no warning anywhere |
| c | corpus + `06_broken.sql` (`CREATE OR REPLACE PROCEDURE broken AS BEGIN IF x THEN END;`), stages 1–8 | 0 ×8 | 01: file OK, role `procedure`, no warning. 02: `Parse errors : 3`, 3 `syntax_error` issues (first message **32,557 chars**), object `PROC-.BROKEN` **`parse_status: "success"`** with one empty `IF`. 04: BROKEN classified `QUERY_ONLY`. 05: **BR-042 "Validate Create"** from the raw line. 07 stdout: **`Open matters : critical 3, high 5, medium 8, low 10`** (first severity anywhere); gaps GAP-001…003 PARSE_FAILURE; `brd.md` still documents "10.6 Broken — Enquiry" and BR-042. 08: 362 nodes | — |
| c' | variants: truncated header, garbage, function without body, binary file, empty file | 0 | parsed objects `success` with 0 statements; binary/empty files skipped silently by 02 (01 warns `encoding_fallback:latin-1` / `File is empty`) | — |
| d1 | 05 with `--logic-root` missing | 0 | **nothing**: rules 41 → **35**, CALCULATION 6 → 0, high-confidence 16 → 10; not in stdout, `run_meta` or `upstream` | — |
| d2 | 06 with logic and rules missing | 0 | **declared**: stdout `Degraded (missing) : logic, rules`; `quality.degraded_inputs`; upstream nulls; tier-1 and traceability → 0 % | — |
| d3 | 07 with diagram root missing | 1 | traceback | no directory |
| d4 | 08 with report root missing | 0 | **silent**: Gap label and AFFECTS relationship disappear (12 labels, 762 rels); status success | — |
| e1 | 02 against committed `output/inventory` | 1 | `FileNotFoundError: '…\plsql_to_brd\src\01_simple_calculate_simple_interest.sql'` | **orphan** `…/2026-10-01T04.07.11.718Z/raw_structure/` (empty) |
| e2 | good parser run published; then one `abs_path` pointed at a moved file | 1 | crash after **17.8 s** at the 4th file; 3 parsed files discarded | orphan `…04.07.25.677Z/raw_structure/` (empty); **`latest.json` unchanged** (sha256 `ca88906d…` before/after) |
| e3 | 05 where `latest.json` is a pre-created directory | 1 | `PermissionError … latest.json` | complete `rules_artifact.json` **and `run_meta.json` with `"status":"success"`**, pointer not advanced |
| e4 | output root is an existing file | 1 | `FileExistsError [WinError 183]` at mkdir | nothing |
| e5 | 06 with `--max-nodes 1` | 0 | overrun declared `OVERSIZE` (validation-fail path not triggered) | — |
| e6 | 04 with one source file missing | 0 | **silent**: pseudocode 151 → 145, slices 25 → 19, false positive `Unbounded loops w/o EXIT : 1` (`source_lines()` swallows `OSError`) | — |
| e7 | 04 → 05 on committed artifacts (all source paths stale) | 0 | **silent**: slices 25 → 0, rules 41 → 18, SME-review 3 → 14 | — |

---

## A7. Tests and evaluation

| Suite | Checks | Result | Duration (this machine) |
|---|---:|---|---:|
| `test_inventory.py` | 22 | pass | 0.4 s |
| `test_parser.py` | 31 | pass | 58.4 s |
| `test_data.py` | 76 | pass | 148.8 s |
| `test_logic.py` | 46 | pass | 72.1 s |
| `test_rules.py` | 33 | pass | 46.0 s |
| `test_diagram.py` | 52 | pass | 45.9 s |
| `test_synthesis.py` | 86 | pass | 94.5 s |
| `test_graph.py` | 68 | pass | (completed in the drift audit run) |
| **Total** | **414** | **0 failures** | 7–9 min |

- Suites write only to `tempfile` directories, except opt-in flags that write fixtures: `test_inventory.py --update-golden`, `evaluate_rules.py --baseline` (not used).
- `python -m pytest tests` fails to start in this environment (a globally installed pytest plugin crashes); with plugin autoload disabled: 12 passed, 38 errors (missing fixtures) — the suites are script-style (`check()` prints and never raises), so **pytest is not a valid runner**.
- `evaluate_rules.py`: P/R/F1 1.000 (34/34) across four procedures, including two marked `held_out`; `BASELINE.json` records P 0.6154 / R 0.5714 / F1 0.5926.
- A killed graph-suite run may have left `C:\Users\annav\AppData\Local\Temp\tmpo0im75k3` in system temp (outside the repository).

---

## A8. Identifier schemes

| ID | Format | Generated at | Stable? |
|---|---|---|---|
| `run_version` | `YYYY-MM-DDThh.mm.ss.mmmZ` | each script | per run |
| `file_id` | `{STEM_SLUG_UPPER}__{SHA256(rel path)[0:8]}`; `_2`, `_3` on collision | 01:130-164 | yes |
| `object_id` | `{PROC\|FUNC\|PKGS\|PKGB\|TRG}-{OWNER}.{NAME}`; member `{parent}::{MEMBER}` | 02:172-207, 280 | yes; no collision handling across files [I] |
| object file name | `object_id` with `::`→`__`, `/`→`_` | 02:809, 04:849 | yes |
| `statement_id` | `{file_id}__{object_id}__STMT_{seq:04d}` (depth-first, handlers after body) | 02:381-425 | yes if source unchanged |
| CFG | `"*"` pseudo-node for exception edges; edge types `SEQUENCE`, `BRANCH_ENTRY`, `EXCEPTION_EDGE`, `LOOP_BACK_EDGE` | 02:549-589 | — |
| `scope_path` tokens | `IF#n.THEN`, `IF#n.ELSIF{i}`, `IF#n.ELSE`, `LOOP#n`, `NESTED_BLOCK#n`, `CASE#n.WHEN{i}`, `EXCEPTION`, `WHEN(A+B)` | 02:416-469 | — |
| `column_id` | `{TABLE}.{COLUMN}` | 03:1069 | yes |
| `rule_id` | `BR-{i:03d}` after dedupe, sorted by (−signal_strength, name) | 05:1145-1146 | **no**; internal `raw_key` (e.g. `IF::{oid}::{line}`, `CHECK::{table}::{name}`) is stable but deleted (1147, 1153) |
| `rule_set_id` | `RS-{i:03d}` | 05:1097-1099 | mostly |
| `gap_id` | `GAP-{n:03d}` in detection order | 07:345-347 | **no** |
| diagram | `system_dataflow`, `flow_{short_name}`, `state_{TABLE}`; nodes `N1…`; `node_origins` → statement/object | 06:299, 527, 814, 1121 | yes; package members would put `:` in a Windows file name [I] |
| figure numbers | `Figure 4.{i}` by rule count | 07:1156 | no |
| annotation keys | `BR-nnn`, `table:{T}`, `term:{T.C}`, `param:{oid}:{name}`, `object:{oid}`, `executive_summary` | 07:581, 671, 757, 832, 845, 1118 | depends on target |
| graph keys | Parameter `{oid}::{name}`; State `{T}.{C}={V}` | `lib_graph_model.py:177, 336` | — |

---

## A9. MARS inspection facts

Read-only inspection of `E:\Virtusa Projects\MARS` (branch `feature/04d-version-migration-v2` @ `5b8008b`).

| Aspect | Current harness | Previous generation (`origin/feature/control-center`, local `older-project/`, gitignored) |
|---|---|---|
| Purpose | Human-gated remediation of reported vulnerabilities (Excel issue register, CWE-tagged) in six Spring Boot services; per issue: root cause, blast radius, fix plan (human approval), patch verified in a throwaway `git worktree`, three AI verification reports, QA/build gates by real exit codes, deterministic Cleared/Blocked verdict, PR content, audit trail | "Migration and Remediation System": deterministic Java 21 engine + Control Center |
| Stack | Node.js CommonJS scripts; 7 agents; 18 skills; ~49 entry scripts + 23 libs; optional Neo4j; optional `@anthropic-ai/sdk`, `openai`, `@google/generative-ai` in one skill | Java 21, Jackson, picocli, JGit, JavaParser, OpenRewrite; Spring Boot 3.5 API; React 19 UI |
| Pattern | Collect (script facts) → Author (agent judgement JSON validated by schema) → Render (Markdown) | Engine phases (31-state `RunPhase`), gates, capabilities |
| Hierarchy | Phase → Agent → Skill (toolbox) → Script → Artifact per Issue; **no Run or Task entity** | Run (`RUN-<ULID>`) → RunPhase → Gate; Finding → Plan → Proposal → Decision → Change; Evidence; Verdict |
| HITL | plan `Status` cell hand-edited `Proposed → Approved`; PR publication by chat request; neither recorded | `DEC-*.json` write-once, HMAC-signed, hash-bound, attributed |
| Persistence | overwrite in place; intermediates gitignored; no run IDs | run directories, hash-chained `provenance/evidence.jsonl`, ledgers, checkpoints, `events/events.jsonl` |
| Observability | none structured (timestamps, gate records with exit codes, provenance footers, `pipeline-lint.js`) | `ExecutionEvent` envelope (`event_id, run_id, sequence, timestamp, type, category, phase, component, activity, status, title, message, progress, subjects, evidence_refs, artifact_refs, human_action, attributes`), ~60 types, statuses STARTED/PROGRESS/COMPLETED/WAITING/FAILED/SKIPPED/INFO; file-locked gap-free append; SSE (`hello`, `execution-event` with `id`=sequence, `worker`, 15 s heartbeat; `Last-Event-ID` replay); OTel spans rebuilt from events in the API only; principle "events are witnesses, not authority" |
| Dashboard | **Mission Control proposal in progress** (`docs/mission-control/MARS-Mission-Control-Proposal.md`, untracked, Part I only): "remediation operations console with evidence-grade observability"; four questions (needs a human now? where is every issue? can I trust the evidence? what did MARS do?); hooks-first then zero-dependency script emitter; roadmap P0–P8; sections on event model, OTel, frontend, MVP not yet written | Built Control Center: pages Runs, Overview, Pipeline, Actions (gates), Activity, Security, Finding, Migration, Changes, Proposal, Graph, Evidence, Logs, Validation, Verdict; read API + command API with idempotency keys and expected-hash decisions; roles VIEWER/OPERATOR/APPROVER/ADMIN; invariants: API writes no files, UI invents no state |
| Evidence-integrity issue | `06-test-gate/qa_ISSUE-003.md` says `Passed` while recording `FAIL | 1`; re-scoring today's files would flip two issues to Cleared | — |

---

## A10. Branch state

- Current branch `readme-full-documentation` is in sync with its remote.
- Local `main` is stale: `origin/main` is 6 commits ahead (PRs #10–#12). Over `origin/main`, this branch adds only `d0d7fbc` (36 files: `src/openwiki/**`, `src/.github/workflows/openwiki-update.yml`, `src/AGENTS.md`, `src/CLAUDE.md`).
- Feature branches are merged except `redesign-data-agent-enforcement-state` (patch-equivalent) and `origin/rename-inventory-stage-files` (5 fixes by another author, apparently superseded).
- Timeline: scripts last changed Jul 27–29; agent specs 1, 2, 4 on Jul 27 (spec 4 not updated in the Jul 28 redesign); README/docs Jul 30; committed output generated 2026-07-29T16:05Z (after the last code change) but committed Sep 1; OpenWiki dated Aug 5, committed Sep 1.
