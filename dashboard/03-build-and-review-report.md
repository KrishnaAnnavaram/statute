# STATUTE Console — Build, Test, Critique and Correction Report

Companion to [00-statue-dashboard-research-report.md](00-statue-dashboard-research-report.md). Date: 2026-10-01.

**Status:** Built, run against real STATUTE data, tested, critiqued twice and corrected. Nothing is committed: the changes are in the working tree of branch `readme-full-documentation`.

## 1. Re-inspection before building

The research still held:

- **Stage scripts** were unchanged since the research.
- **The committed `output/`** was unchanged: one pre-instrumentation run per stage, from 2026-07-29.
- **Infrastructure:** still no UI, API, hooks, CI or manifest.

Two facts shaped the build:

1. **The committed runs record no lifecycle.** Without instrumentation, *running* and *failed* could only be inferred, so the MVP had to include the Phase 2a helper.
2. **MARS was not reused.** Its domain (issues, approvals, verdicts) and its terminology appear nowhere in the console. The console speaks STATUTE's language: *stage, stage run, run version, pipeline run (derived), published, upstream, finding, gap, rule, evidence*.

## 2. Architecture implemented

```
.claude/scripts/lib_runlog.py ──writes──▶ output/<stage>/<rv>/run_status.json + events.jsonl   (witnesses)
8 stage scripts (+121 lines, additive) ─┘          output/<stage>/<rv>/run_meta.json, artifacts, latest.json (authority, unchanged)
                                                     ▲ read-only
console/server  (Python stdlib)  scan → derive (lineage · staleness · pipeline runs · findings · annotations · source drift · health) → /api/v1 (GET)
console/web     (React 19 · TS · Vite 8 · Tailwind 4 · TanStack Query/Router · react-markdown · Mermaid lazy+sandboxed) ← polling 2 s
```

| Decision | Choice and reason |
|---|---|
| Source of truth | Run directories and pointers. Every status is derived on read and carries evidence paths; nothing is persisted |
| Live transport | ETag'd polling every 2 s while the tab is visible (one status call takes ~40–90 ms). The snapshot is always authoritative, so missed, duplicated or out-of-order updates cannot corrupt state |
| Events | Per-run `events.jsonl`, append-only and co-located. The Events page tails it with a time cursor and de-duplicates by `event_id` |
| Graphs | Hand-drawn SVG: a fixed layered lineage graph for 8 stages, and a waterfall timeline. No graph library was needed |
| Approvals | None. STATUTE has no runtime approval; review is shown as findings and annotation status |
| OpenTelemetry | Not used. `TRACEPARENT` is captured if Claude Code provides it; export stays a later phase |

Change classification:

| Class | Changes |
|---|---|
| **Dashboard-only** | `console/server`, `console/web` |
| **Additive instrumentation** | `lib_runlog.py`; one `begin` / `input` / `attach` / `item` / `succeed` call per stage; failure capture via `sys.excepthook` / `atexit`; `_attempts/` for crashes before the run directory exists |
| **Backend integration** | 05 `run_meta.upstream` now records `logic_run_version`; 08 `run_meta` now records concrete upstream versions. Artifacts are unchanged |
| **Runtime-sensitive** | None. All artifact bytes are identical after normalisation, verified against committed output |

## 3. Dashboard features

**Pages:** Pipeline (home), Runs, Pipeline run, Stage run (7 tabs), Findings, Evidence (search plus entity pages), Compare, Events, Health, Stages.

**Questions the console answers, and how:**

| Question | How the console answers it |
|---|---|
| What is running? | The stage strip and header show the running stage with current item, progress (`3/5 objects parsed`) and elapsed time |
| What triggered it, and what did it consume? | The Inputs tab lists each upstream run with latest/pinned resolution and the run published now |
| What happened before, and what happens next? | Recent activity; a DAG-derived next-steps list with copyable commands; "wait for it to finish" while a stage runs |
| What failed? | Error class, message, `file:line` and the last item processed, with local paths redacted; "latest still points at …" |
| What is stale or inconsistent? | "Out of date" with a stated cause; inconsistent pipeline runs; unrecorded provenance |
| What needs a human? | Gaps, rules needing SME review, comment-only enums, and annotation status (applied / orphaned / re-pointed) |
| Where does a requirement come from? | Requirement → rule → statement → object → `file:line`, with an opt-in source window |
| Is the environment healthy? | H1–H11 self-checks. H8 catches agent-spec drift such as Agent 1's `./checkpoints/` instruction |

## 4. Files changed

**Modified:** `.claude/scripts/01_inventory.py` … `08_graph.py` (121 lines added, 4 changed).

**New:**
- `.claude/scripts/lib_runlog.py`
- `console/README.md`
- `console/server/statute_console/{__init__, __main__, registry, model, findings, evidence, health, compare, views, server}.py`
- `console/server/tests/test_console.py`
- `console/web/{package.json, package-lock.json, tsconfig.json, vite.config.ts, eslint.config.js, playwright.config.ts, index.html, .gitignore}`
- `console/web/src/**` (api, queries, router, main, styles, `lib/format`, `components/{ui, viewers, graphs, Layout}`, and 7 page modules)
- `console/web/src/**/*.test.ts(x)`
- `console/web/e2e/console.spec.ts`

## 5. Instrumentation added (`lib_runlog.py`)

**`run_status.json` (`statute.run_status/1`)** records:
- `status`: running, succeeded or failed;
- `started_at`, `updated_at`, `finished_at`, `duration_ms`;
- `inputs[{stage, run_version, resolved, present, optional}]`;
- `degraded[]`, `progress`, `current_item`, `published`;
- `error{class, message, where, last_item}`;
- `code_version`, `traceparent`, `pid`, `argv`.

The file is written atomically (temp file + `os.replace`, with Windows retry).

**`events.jsonl` (`statute.event/1`)** event types:
- `stage_run.started`, `stage_run.input_resolved`, `stage_run.degraded`, `stage_run.succeeded`, `stage_run.failed`;
- `pointer.published`;
- `item.started`, `item.succeeded`, `item.failed`, `item.skipped`.

**Failure capture:**
- uncaught exception → `failed`, with the deepest stage-script frame recorded as `where`;
- `sys.exit` or interruption → `failed (Exit)`;
- 06 validation failure → `DiagramValidationError`;
- crash before `mkdir` → `output/<stage>/_attempts/<id>/`.

**Degradation is now declared in five places** (all previously silent or only visible in stdout):
- 05 without logic;
- 06 and 08 missing optional inputs;
- unreadable source files in 03, 04, 05 and 06 (via the cached source readers);
- 01 on an empty directory.

**Disabled for `--output` runs**, the mode the test harnesses use, so tests and golden files are unaffected.

## 6. Tests added

| Suite | Count | Covers |
|---|---:|---|
| `console/server/tests` (unittest) | **32** | Committed-output facts (8 stages, provenance gaps 05 and 08, unreachable-but-identical source, BR-002 → line 79, BR-014 DDL trace, H8 drift). Scenarios: newer parser run → unsynced chain; pinned input; crashed legacy directory; failed attempt (with redaction); running → stalled; unpublished success; declared degradation; inconsistent pipeline; annotation applied/orphaned/re-pointed; unreadable annotations; source change; incremental and torn-line event reads; compare. Redaction (paths with spaces, linear time). HTTP: security headers, ETag, foreign Host 421, read-only 405, traversal, SPA deep links with dotted run versions, every endpoint with a no-write tree hash, unknown → 404. Real-repo read-only load |
| `console/web` Vitest | **10** | Formatting; status badges carry text and mark inferred states; link allow-list (`javascript:`, `data:`, `vbscript:` blocked); Markdown raw HTML inert; DataTable sort and `aria-sort`; empty state |
| `console/web` Playwright | **9** | Home answers within 5 s with real data; dotted deep links; BR-002 → line 79 in ≤ 3 clicks; keyboard tabs; findings lens in the URL; health findings; sandboxed Mermaid frame; API read-only and Host check; **axe WCAG 2.2 AA scan of 7 pages: no serious or critical violations** |
| Pipeline suites (existing) | **414 checks** | Re-run after instrumentation: **414 pass, 0 fail**. `evaluate_rules.py` unchanged |

## 7. Commands run and results

| Command | Result |
|---|---|
| `python tests/test_*.py` (8 suites) | 414 pass / 0 fail, run twice (after the patch and after the final library change) |
| `python tests/evaluate_rules.py` | Unchanged (P/R/F1 1.000) |
| Instrumented 8-stage run into scratch, then normalised diff vs committed `output/` | All artifacts identical; only 05/08 `run_meta.upstream` additions plus the new witness files differ |
| Failure probes: missing inventory, bad source dir, 05 without logic, moved source mid-parse, unreadable source in 04, `08 --ask` | All recorded correctly: `_attempts` failure at `02_parser.py:73`; `SourceNotFound`; degraded `04_logic`; failed at `02_parser.py:772` with last item; degraded `source:…`; nothing written |
| `python -m unittest discover -s tests` (console/server) | 32 OK |
| `npm run typecheck` · `npm run lint` · `npm test` · `npm run build` · `npm run e2e` | Clean · clean · 10 pass · built (main 97 KB gz) · 9 pass |
| Playwright sweep: 18 routes × light/dark/820 px plus interactions (29 loads) | 0 console errors, 0 failed requests, 0 horizontal overflow, max load 1.36 s |
| Live scenario (scratch output tree, real stage processes) | Running detected and shown within one poll; 106 events streamed live; downstream 03–08 flipped to out of date; a real crash surfaced with file, line and item |

## 8. Representative scenarios tested

| Brief scenario | STATUTE equivalent | Result |
|---|---|---|
| Idle | Committed output, nothing running | "Idle · last activity 64 days ago", next steps shown |
| New execution begins / running / nested operation | Real `02_parser` run: file items, then object items | Running badge, current item, `n/5` progress, elapsed time, live events |
| Successful completion | Parser finishes | Published; downstream marked out of date with cause |
| Operation failure | Source file moved mid-parse | Failed at `02_parser.py:772`; last item named; published run unchanged |
| Retry | Not a STATUTE concept | Not drawn (a re-run is a new immutable run) |
| External dependency failure | Missing source or inventory | `_attempts` / failed status; H3 reachability |
| Long-running | Parser ~35 s | Elapsed time and progress; stall → "crashed" after 5 min without updates (unit-tested) |
| Missing artifact | Unpublished success, missing members | Findings `run_unpublished` / `member_missing` |
| Malformed data | Torn `events.jsonl` line, unreadable annotations, unreadable `run_meta` | Tolerated and reported |
| Stream disconnect / reconnect | API unreachable | Header shows "API unreachable — showing data from …"; the next successful poll restores state (snapshot model) |
| Historical run | Committed 2026-07-29 runs | Partial timings marked `*`; provenance gaps shown |
| Large event list | 2,000-event window, 5,000 buffer, 1,500 DOM rows | Capped, searchable and exportable |
| Human action | SME review / annotations | Review lens; annotation re-pointing detection |

## 9. LLM-as-judge — pass 1 (functional build, before corrections)

Review board perspectives: staff frontend, staff platform, observability, SRE, security, enterprise UX, STATUTE developer, STATUTE operator.

| Criterion | Score | Why below 9 |
|---|---:|---|
| Fidelity to STATUTE | 9 | — |
| Fidelity to research | 8 | Lineage graph hid stage 08; no item-level waterfall |
| Architecture correctness | 7 | Deep links with dotted run versions returned 404 (P0) |
| Live-status clarity | 5 | 10 s idle poll missed new runs; "current item" stale for ~9 s because of the status-write throttle |
| Runtime observability | 7 | Invocation layer (agent/session) absent |
| Debugging usefulness | 7 | Failed run printed "Parsed ? objects … 0 parse errors" (misleading) |
| Trace quality | 6 | Duration labels drawn over bars; lineage clipped |
| Event console | 8 | No virtualisation (capped instead) |
| Graph usefulness | 6 | Stage 08 off-screen |
| Artifact visibility | 7 | Diagrams unreadably small in a 720 px drawer |
| Failure diagnosis | 6 | The misleading summary above |
| Information architecture | 8 | "Current" shown next to "newer runs" (contradictory) |
| Navigation | 6 | P0 deep links; wrong nav highlight on stage runs |
| Visual hierarchy | 8 | Severity count shown as an icon and a number only |
| Accessibility | 5 | axe: 4 serious violations (focusable scroll region, colour-only link, nested interactive SVG, 24 px target) |
| Responsive behaviour | 5 | At 820 px the nav didn't collapse; badges clipped |
| Performance | 7 | 165 KB gzipped main bundle |
| Security | 9 | — |
| Auditability | 8 | No invocation ledger |
| Maintainability | 8 | Declared registry (mitigated by H8) |
| Test coverage | 5 | No frontend unit, e2e or accessibility tests |
| Developer usefulness | 7 | Above defects |
| Operator/manager usefulness | 7 | Above defects |

**Defects found:**

| ID | Pri | Defect |
|---|---|---|
| D1 | **P0** | SPA fallback treated any final path segment with a dot as a missing asset, so every run-version deep link returned 404 |
| D2 | P1 | Idle polling at 10 s, so a new run could stay invisible for up to 10 s (criterion S6 is ≤ 4 s) |
| D3 | P1 | `lib_runlog` throttled the status write on item start, so the current item was stale for a whole item |
| D4 | P1 | Failed or crashed runs showed a stats sentence built from an empty summary |
| D5 | P1 | Lineage graph clipped `08_graph` |
| D6 | P1 | Timeline labels overlapped bars near the right edge |
| D7 | P1 | Four serious axe violations |
| D8 | P1 | No responsive layout below 1024 px |
| D9 | P2 | Mermaid diagrams too small to read |
| D10 | P2 | "Current" badge shown on a superseded pipeline run |
| D11 | P2 | Stage-run pages highlighted "Stages" in the nav |
| D12 | P2 | Severity marker shown as an icon and number only |
| D13 | P2 | Main bundle 165 KB gzipped |
| D14 | P2 | No frontend tests |
| D15 | P3 | Provenance labels repeated the kind ("Rule Rule BR-002") |
| D16 | P3 | Seven separate "provenance unrecorded" attention rows (grouped during the build, before pass 1 closed) |

## 10. Corrections implemented

| ID | Fix |
|---|---|
| D1 | Only `assets/` paths and real static extensions 404; added a regression test for 4 deep links |
| D2 | Poll every 2 s while visible (paused when hidden) |
| D3 | Item starts always rewrite `run_status.json`; verified live: the current item advances file by file |
| D4 | Run-state-aware text: "Failed before writing its summary (run_meta.json); no outputs were published. It reached 2 of 5 files discovered." Unit-tested |
| D5 | Graph scales to its panel via `viewBox` (minimum 880 px) |
| D6 | Labels flip to the left of bars ending past 82% |
| D7 | Focusable scroll regions; underlined in-text links; graph `role="group"`; ≥ 24 px targets; axe test added |
| D8 | Nav becomes a scrolling top bar below `lg`; strip uses 1/2/4/8 columns; header wraps |
| D9 | Wide drawer (up to 1240 px) and a 78vh diagram frame |
| D10 | "Latest BRD · inputs superseded" instead of "Current" |
| D11 | Stage-run pages highlight Runs |
| D12 | "7 · worst high" |
| D13 | Route-level code splitting: main bundle 97 KB gzipped |
| D14 | 10 Vitest tests and 9 Playwright tests (including axe) |
| D15 | Labels de-duplicated |
| D16 | Grouped into "2 stages do not record every input they consumed" |

## 11. LLM-as-judge — pass 2 (after corrections, re-rendered and re-tested)

| Criterion | Pass 1 | Pass 2 | Remaining reason if below 9 |
|---|---:|---:|---|
| Fidelity to STATUTE | 9 | 9 | — |
| Fidelity to research | 8 | 9 | — |
| Architecture correctness | 7 | 9 | — |
| Live-status clarity | 5 | 9 | — |
| Runtime observability | 7 | 8 | Agent/session invocation layer (Claude Code hooks, research Phase 3) not built |
| Debugging usefulness | 7 | 8 | No per-item waterfall; durations are in the Items table |
| Trace quality | 6 | 8 | Stage-level only; committed runs have partial timings |
| Event console | 8 | 8 | Polling with a DOM cap, not SSE or virtualisation; adequate at current volumes |
| Graph usefulness | 6 | 8 | No expanded multi-run lineage mode; no evidence ego-graph (path list instead) |
| Artifact visibility | 7 | 9 | — |
| Failure diagnosis | 6 | 9 | — |
| Information architecture | 8 | 9 | — |
| Navigation | 6 | 9 | — |
| Visual hierarchy | 8 | 9 | — |
| Accessibility | 5 | 8 | axe-clean on 7 pages; no manual screen-reader pass; SVG timeline is a table-role structure but not fully navigable |
| Responsive behaviour | 5 | 8 | Usable at 820 px; not designed for phones (a desktop tool) |
| Performance | 7 | 8 | Fine at today's scale; event and finding lists are not server-paginated |
| Security | 9 | 9 | — |
| Auditability | 8 | 8 | No invocation ledger; annotations audited only through git |
| Maintainability | 8 | 8 | Registry is declared (H8 guards it); Node toolchain added to a Python repo |
| Test coverage | 5 | 8 | No visual-regression baseline; Mermaid sandbox covered by one e2e test |
| Developer usefulness | 7 | 9 | — |
| Operator/manager usefulness | 7 | 8 | Single-corpus; no trend charts yet |

**No P0 remains. No practical P1 remains open.**

## 12. Remaining limitations

1. **Committed output predates instrumentation.** On the real `output/`, running and crashed states are *inferred*, timings are *partial* and there are no events. A fresh pipeline run, which rewrites `output/`, would make them recorded. I did not re-run the pipeline into the committed folder.
2. **No invocation layer.** Which Claude session or subagent launched a run is not recorded; that needs Claude Code hooks (research Phase 3, needs your approval for `.claude/settings.json`).
3. **Compare** needs two pipeline runs; the committed output has one.
4. **Pinning and rule identity are still weak.**
   - 07 and 08 still cannot pin individual inputs.
   - `BR-nnn` is still renumbered every run; the console detects re-pointed annotations but does not fix the root cause (research I9, I10).
5. **Not fixed (out of scope):** the content-correctness defects found by the research:
   - R1, "0 lines of code";
   - R8, branch arms drawn as a sequence;
   - R9, silent loss when source is unreachable. The console now *flags* it (H3 plus the source finding), and `lib_runlog` declares the degradation.
6. **Toolchain and scope:**
   - `console/web/dist` is not committed; Node 20+ is needed to build the UI.
   - Localhost only; no authentication (by design until hosting is decided).

## 13. Remaining instrumentation gaps

- Invocation ledger via hooks (I8).
- Per-artifact hashes in `run_status` (I7; the console computes them on demand).
- A canonical `stage_key` in `run_meta` (I5; the console normalises).
- Parser objects inside files with syntax errors are still `parse_status: success` (I11; the console raises a critical finding per file).
- `latest.json` is still written in place (only `run_status.json` is atomic).
- Optional OTel / OpenLineage exporters (research Phase 6).

## 14. Potential future MARS / STATUTE shared components

Kept independent, as the research recommended. Candidates to extract once MARS's console exists:

- design tokens and status semantics (`styles.css`);
- `ui.tsx` primitives (badges, DataTable, Drawer, Tabs, KeyValues);
- `viewers.tsx` (safe Markdown, sandboxed Mermaid, JSON);
- the waterfall `Timeline`;
- the event envelope conventions (`statute.event/1` ↔ `mars.event/1`);
- a shared Claude Code hook collector.

The domain model, the derivations and the API stay product-specific.

## 15. Recommended next phase

1. **Approve and add observational Claude Code hooks** (`SubagentStart`/`Stop`, `PostToolUse(Bash)`) writing an invocation ledger, and show "invoked by" on stage runs.
2. **Fix the root causes the console now exposes:**
   - per-stage pinning for 07 and 08;
   - stable rule keys alongside `BR-nnn`;
   - fail loudly on unreachable source;
   - store branch conditions in 02 (R8).
3. **Re-run the pipeline** so `output/` becomes fully instrumented. Then add item-level waterfalls and SSE tailing if event volume grows.
4. **Add the stated success criteria to CI** together with the 414-check suite (the repo still has no root workflow).

## 16. Reference-style redesign (LHMS dashboard) and judge pass 3

**Request.** Rebuild the console to look like the dashboard in `kaajalkrish/Legacy-Harness-Modernization-System`, adding sections where useful.

**Adopted from the reference:**
- dark-first palette (`#111` / `#1a1a1a` / gold `#e8b800`) and a remembered light theme;
- system font stack and monospace stack;
- pill badges with dots;
- uppercase 10px labels and 30px KPI tiles;
- gold-underlined tab bar;
- a 272px collapsible sidebar with gold numbered phase circles;
- the header with live badge, theme / View BRD / Export JSON / gold Export PDF;
- the four-field meta strip;
- the BRD modal with a table of contents.

**Tabs.** Mapped to what STATUTE actually records:

| Reference tab | Here | Why it differs |
|---|---|---|
| Pipeline | Pipeline overview | — |
| Agents | Agents (from `.claude/agents` frontmatter) | — |
| Artifacts | Artifacts (all 73 files of the current pipeline run) | — |
| Call Trace | **Statement Trace** | STATUTE has no runtime trace; this is the parser's source-ordered statement trees (124 statements) |
| Synthetic Testing | Synthetic Testing | The reference's score formula is applied to rule confidence and labelled as rule coverage, **not** executed tests |
| Interactive Workflow | Interactive Workflow | Clickable stage lineage plus STATUTE's system data-flow diagram |
| Timeline | Timeline | — |
| Rules | Rules | — |
| State | State | — |

New beyond the reference: Diagrams, Data Model, plus the existing Findings, Evidence, Runs, Events and Health.

**Backend additions.**
- `catalog.py` serves `/agents`, `/trace`, `/rules`, `/catalogue`, `/brd`, `/data-model`, `/diagrams` and `/quality`.
- `status` gained `workspace` and `kpis`.
- All of it remains read-only GET.

**Deliberately not copied.** The reference renders HTML with `dangerouslySetInnerHTML` and Mermaid with `securityLevel: 'loose'`. This console keeps:
- escaped Markdown (the lint rule bans `dangerouslySetInnerHTML`);
- strict Mermaid inside `sandbox=""` iframes;
- the localhost-only, Host-checked, read-only server.

**Judge pass 3: defects found by screenshot sweep and tests, all fixed.**

| # | Defect | Fix |
|---|---|---|
| 1 | Mermaid node labels clipped ("FN_CALCULATE_SIMPLE_IN"): Mermaid measures `<g class="label">` in the host page, where the dashboard's `.label` style (10px uppercase) applied | `.label:not(svg *)` |
| 2 | Light-filled `classDef` nodes (dataNode, warning, …) had light text in dark mode | dark label text forced for those classes inside the frame |
| 3 | Stages whose provenance is unrecorded were counted as "out of date" | counted as done and flagged separately as *provenance unrecorded* |
| 4 | Worst-finding badge on stage cards showed only a coloured dot | now "*n severity*", linked to that stage's findings |
| 5 | 16 tabs overflowed at 1600px with a hidden scrollbar; Health and State unreachable by sight | thin visible scrollbar, tighter padding, active tab scrolled into view |
| 6 | On a 390px phone the sidebar consumed the screen | collapsed by default under 768px, opens as an overlay, closes on navigation; no horizontal scroll (tested) |
| 7 | axe hung on pages with sandboxed diagram frames (it cannot inject into a script-less frame) | frames excluded; they contain only the rendered SVG |
| 8 | axe: meters with non-string labels had no accessible name | `aria-labelledby` |
| 9 | Light theme: 9–21 contrast failures per page (green 4.09:1 on badge tint) | darker light-theme green, orange and amber; lighter badge tint; 0 serious or critical violations in both themes |
| 10 | Aborted browser connections printed tracebacks in the server log | ignored quietly |

**Results after corrections:**
- typecheck clean; lint clean;
- Vitest 10/10 (badge label expectations updated);
- backend `unittest` 37/37 (new `TestCatalogue` checks agents, 124 statements, 41 rules with BR-002 at line 79, score formula, 15 tables, 7 diagrams, 73 artifacts and the KPIs, and adds the new endpoints to the never-writes sweep);
- Playwright 13/13 (new: every tab renders real data, BRD modal TOC and Escape, theme persistence, phone layout; axe now covers 17 pages);
- a separate axe run in the light theme over 15 pages found no serious or critical violations.
