# STATUTE Console

A local, **read-only** operational console for STATUTE. It shows:

- what every pipeline stage is doing now;
- how the latest outputs were derived (lineage, staleness);
- what failed, degraded or needs a human;
- the evidence behind every requirement, down to the source line.

Design rationale: [`dashboard/00-statue-dashboard-research-report.md`](../dashboard/00-statue-dashboard-research-report.md). Build and review record: [`dashboard/03-build-and-review-report.md`](../dashboard/03-build-and-review-report.md).

**Files are the source of truth.** The console derives every status on read from `output/` (`run_meta.json`, `latest.json`, artifacts, and the `run_status.json` / `events.jsonl` witnesses written by `lib_runlog.py`). It persists nothing. It never writes to `output/`, `src/` or `brd_annotations.json`, and it never runs the pipeline. Commands are offered for you to copy.

## Run it

```bash
# once: build the UI (Node 20+)
cd console/web && npm ci && npm run build

# serve (Python 3.10+, standard library only) — from console/server
cd console/server && python -m statute_console            # http://127.0.0.1:8765/
python -m statute_console --output /path/to/other/output   # another output tree
python -m statute_console --port 9000
```

The server binds `127.0.0.1` and rejects requests whose `Host` header is not local.

## What you get

The look follows the Legacy Harness Modernization System dashboard: dark first (with a remembered light theme), a gold accent, the system font stack, and a collapsible stage sidebar with numbered gold phase circles. Every screen shares one header:

- the live/idle badge;
- buttons for the theme, **View BRD** (a modal with a table of contents and a Markdown download), **Export JSON** (the status snapshot) and **Export PDF** (print);
- a strip with the project, source and output directories and the BRD name;
- eight KPI tiles: overall, objects, tables, rules, requirements, open matters, artifacts, build time.

| Tab | Answers |
|---|---|
| **Pipeline** (`/`) | Overall progress, then one card per stage with state, freshness, worst finding and expandable detail (purpose, causes, error, run link). Alongside: a *quality gate* derived from the output directory, the latest pipeline run with its deliverables, next steps with copyable commands, recent activity and a ranked *Needs attention* list |
| **Agents** | The eight subagents from `.claude/agents` frontmatter, each with its backing script, output artifact, status, freshness, size and duration. Generation is marked deterministic |
| **Artifacts** | Every file the current pipeline run produced (73), searchable and filterable by stage and kind, with safe previews |
| **Statement Trace** | Every parsed statement (124) in source order, by object and kind (control flow, data access, call, transaction, exception, assignment), with scope, target and flow |
| **Synthetic Testing** | A rule-coverage score: (confirmed + 0.9·high + 0.5·medium + 0.2·low) / rules × 100. Also confidence, category and verification breakdowns, the 06_diagram quality gates and open matters by type |
| **Interactive Workflow** | Clickable stage lineage for the current pipeline run, plus STATUTE's own system data-flow diagram |
| **Diagrams** | All generated Mermaid diagrams, with budget warnings |
| **Timeline** | Stage completions with the gaps between invocations, plus a waterfall |
| **Rules** | All 41 rules, filterable by category, confidence and SME review; rows expand to the requirement, condition and evidence links |
| **Data Model** | Tables with CRUD usage by program, constraint statistics and the ERD |
| **State** | The raw status snapshot |
| **Runs** | Pipeline runs (derived: a 07_synthesis run plus its upstream closure), and a stage × run grid that highlights consumed upstream runs on hover |
| **Pipeline run** | Lineage graph of the exact runs consumed, a timeline separating in-stage time from time between invocations, member runs and deliverables |
| **Stage run** | Summary · Inputs (latest vs pinned, published-now comparison) · Outputs (artifacts with sandboxed previews) · Items (per-item status and duration) · Findings · Events · Raw |
| **Findings** | One queue across run, lineage, source, content and review lenses; filters live in the URL |
| **Evidence** | A requirement, rule, open matter, object, statement, table, column or file, with its provenance path to a source line (source text is shown only on request) |
| **Compare** | Two pipeline runs compared by stable rule keys, never by `BR-nnn`, which is renumbered; renumbering is called out |
| **Events** | A follow-live / pause console over `events.jsonl`, with filters, a JSON drawer and JSONL export |
| **Health** | H1–H11 self-checks: dependencies, grammar, source reachability and drift, output-tree integrity, lineage, annotations, agent specs vs script flags, instrumentation, retention |

Runs made before `lib_runlog.py` existed (including the committed `output/`) carry only `run_meta.json`. For those runs:

- the console labels running and crashed states *inferred*;
- durations are *partial*;
- there are no events.

Re-running the pipeline produces fully instrumented runs.

## Layout

```
console/
  server/statute_console/   registry · model (scan + derivations) · findings · evidence · health · compare · catalog (tab data) · views · server
  server/tests/             unittest suite: fixtures are mutated copies of the real output/
  web/                      React 19 + TypeScript + Vite + Tailwind 4; TanStack Query/Router; react-markdown; Mermaid (lazy, sandboxed)
  web/e2e/                  Playwright suite against the real server and committed output (+ axe WCAG 2.2 AA scan)
```

## Tests

```bash
cd console/server && python -m unittest discover -s tests      # 37 tests
cd console/web && npm run typecheck && npm run lint && npm test   # unit/component tests
cd console/web && npm run build && npm run e2e                   # 13 end-to-end tests incl. axe on 17 pages
```

## Security posture

- **Network:** localhost only; Host-header check; GET/HEAD only; strict CSP; `nosniff`; no-referrer.
- **No paths from the client:** runs, artifacts and source files are addressed by IDs that the server maps to paths and re-checks against its roots.
- **Untrusted content:** generated content is treated as untrusted. Markdown escapes raw HTML and allow-lists links. Mermaid renders with `securityLevel: strict` and is displayed in an iframe with an empty `sandbox`.
- **Redaction:** absolute local paths are redacted from every response, and source lines are shown only on request.
