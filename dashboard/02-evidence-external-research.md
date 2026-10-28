# Appendix B — External Research Evidence

Supporting evidence for [00-statue-dashboard-research-report.md](00-statue-dashboard-research-report.md). Research date: **2026-09-30**. Every claim cites a primary source where one was found; claims marked *(unverified)* came from secondary sources or search snippets only.

The question this appendix answers: *which patterns from mature agent-observability, workflow, lineage, tracing and developer-platform tools apply to STATUTE — a deterministic, file-mediated, eight-stage pipeline whose stages are invoked by Claude Code subagents but whose scripts call no model?*

## Contents

- [B1. Claude Code native telemetry (the runtime STATUTE actually executes under)](#b1-claude-code-native-telemetry)
- [B2. Agent / LLM observability platforms](#b2-agent--llm-observability-platforms)
- [B3. OpenTelemetry GenAI semantic conventions](#b3-opentelemetry-genai-semantic-conventions)
- [B4. Workflow, CI and lineage tools](#b4-workflow-ci-and-lineage-tools)
- [B5. Human-in-the-loop and curation patterns](#b5-human-in-the-loop-and-curation-patterns)
- [B6. Distributed tracing and APM](#b6-distributed-tracing-and-apm)
- [B7. Developer platform dashboards](#b7-developer-platform-dashboards)
- [B8. Frontend libraries](#b8-frontend-libraries)
- [B9. Real-time transport, visual design and rendering security](#b9-real-time-transport-visual-design-and-rendering-security)
- [B10. Pattern catalogue and applicability to STATUTE](#b10-pattern-catalogue-and-applicability-to-statute)

---

## B1. Claude Code native telemetry

STATUTE's stages are launched by Claude Code subagents (`.claude/agents/*.md`) that run each script through the Bash tool. Claude Code therefore already sits *above* every stage invocation, and can emit telemetry with **no change to STATUTE's code**.

Sources: [monitoring-usage](https://code.claude.com/docs/en/monitoring-usage) · [hooks](https://code.claude.com/docs/en/hooks.md) · [headless](https://code.claude.com/docs/en/headless.md) · [sessions](https://code.claude.com/docs/en/sessions.md) · [Agent SDK observability](https://code.claude.com/docs/en/agent-sdk/observability.md)

### OpenTelemetry export

| Item | Detail |
|---|---|
| Enable | `CLAUDE_CODE_ENABLE_TELEMETRY=1`; exporters via `OTEL_METRICS_EXPORTER` (otlp/prometheus/console/none), `OTEL_LOGS_EXPORTER` (otlp/console/none), `OTEL_TRACES_EXPORTER` (requires `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`) |
| Status | Metrics and events GA; **traces beta** — "span names and attributes may change between releases" |
| Metrics | `claude_code.session.count`, `token.usage`, `cost.usage`, `lines_of_code.count`, `commit.count`, `pull_request.count`, `code_edit_tool.decision`, `active_time.total`. Cost/token carry `query_source` (main/subagent/auxiliary) and `agent.name` |
| Events (OTLP logs) | `user_prompt`, `assistant_response`, `tool_result` (`tool_name`, `success`, `duration_ms`, `error_type`), `tool_decision`, `api_request` (tokens, `cost_usd`, `duration_ms`), `api_error`, `api_refusal`, plus permission/MCP/skill/hook lifecycle events. Correlation: `prompt.id`, `event.sequence` |
| Spans (beta) | `claude_code.interaction` → `claude_code.llm_request` / `claude_code.tool` → `claude_code.tool.execution` (`success`, `error_class`, `duration_ms`). Subagent spans **nest under the parent's tool span**; tool spans carry `agent_id`, `parent_agent_id` |
| Subagent identity | `agent.name` is reported as `"custom"` for user-defined agents unless `OTEL_LOG_TOOL_DETAILS=1` — needed to see `5_rules` etc. **No OTel event exists for subagent start/stop**; attribution is via span attributes only |
| Trace propagation | "Bash and PowerShell subprocesses automatically inherit a `TRACEPARENT` environment variable containing the W3C trace context of the active tool execution span." Any span a STATUTE script emits would nest under `claude_code.tool.execution` |
| Content | Redacted by default. Opt-in: `OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_ASSISTANT_RESPONSES`, `OTEL_LOG_TOOL_DETAILS`, `OTEL_LOG_TOOL_CONTENT`, `OTEL_LOG_RAW_API_BODIES`. Identity attributes (`user.email`, `organization.id`, `user.account_uuid`) are attached by default |

### Hooks

Configured in `.claude/settings.json` (project, committable), `.claude/settings.local.json`, user settings, managed policy, plugins, or **scoped in subagent frontmatter** (active only while that subagent runs). Handler types: `command`, `http`, `mcp_tool`, `prompt`, `agent`; `"async": true` makes a hook non-blocking. Exit code 0 on a non-blocking event is purely observational.

| Hook | Relevance to STATUTE | Payload fields (beyond `session_id`, `prompt_id`, `transcript_path`, `cwd`, `hook_event_name`) |
|---|---|---|
| `SubagentStart` | A stage wrapper (`2_parser` …) began | `agent_id`, `agent_type` (matcher can target `^5_rules$`) |
| `SubagentStop` | A stage wrapper finished | `agent_id`, `agent_type`, `last_assistant_message` *(the agent's report — output, not reasoning)* |
| `PreToolUse` (Bash) | A stage script is about to run | `tool_name`, `tool_input.command`, `tool_use_id`; inside a subagent also `agent_id`, `agent_type` |
| `PostToolUse` / `PostToolUseFailure` (Bash) | Script finished / failed | adds `tool_response` / `error_message` |
| `SessionStart` / `SessionEnd` | Operator session boundary | `source` / `reason` |

*(unverified verbatim)*: `agent_transcript_path` on `SubagentStart`; exact shape of `tool_response` across tools.

### Transcripts and headless streams

- Transcripts: `~/.claude/projects/<project>/<session-id>.jsonl`, subagents under `<session-id>/subagents/agent-<id>.jsonl`, 30-day retention. **The format "is internal to Claude Code and changes between versions"** — not an interface to build on.
- `claude -p --output-format stream-json --verbose`: subagent messages carry `parent_tool_use_id`; final `result` has `session_id`, usage and cost. Usable if STATUTE is ever driven headlessly.
- In-session `/tasks` shows running subagents and background tasks — a partial "what is running now" view that exists today for the interactive operator only.

### Third-party Claude Code tracers

Langfuse, LangSmith and MLflow ship hook-based Claude Code integrations; they parse transcripts and therefore **bypass Claude Code's OTel redaction gates**. Langfuse notes hook-based tracing "depends on local developer configuration" ([source](https://langfuse.com/resources/engineering/coding-agent-tracing)).

**Implication for STATUTE.** The invocation layer (which subagent ran which script, when, how long, with what exit status) can be captured by a narrowly scoped, observational hook writing a local ledger — without editing any stage script. Token/cost belongs only to the wrapper subagents; the scripts are model-free tool executions.

---

## B2. Agent / LLM observability platforms

| Product | Run / trace model | Trace UI | Notable for STATUTE |
|---|---|---|---|
| **LangSmith** ([concepts](https://docs.langchain.com/langsmith/observability-concepts), [run format](https://docs.langchain.com/langsmith/run-data-format)) | project → thread → trace → run (`run_type`, `parent_run_id`, `dotted_order`) | Trajectory, Turns, Details (run tree + I/O + metadata). Studio graph mode with time travel | Masking env vars (`LANGSMITH_HIDE_INPUTS/OUTPUTS`); OTLP ingest; self-host is Enterprise-only |
| **Langfuse** ([data model](https://langfuse.com/docs/observability/data-model), [observation types](https://langfuse.com/docs/observability/features/observation-types), [agent graphs](https://langfuse.com/docs/observability/features/agent-graphs)) | session → trace → observation (10 typed kinds: span, generation, event, agent, tool, chain, retriever, evaluator, embedding, guardrail) | Tree / Timeline / Graph toggle; **Aggregated vs Expanded** agent graph; log-level filter; responsive timeline with zoom (Aug 2026) | Typed kinds drive icons, filters and graph inference; client-side masking only |
| **Arize Phoenix / OpenInference** ([spec](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)) | project / session / trace; span kinds LLM, CHAIN, TOOL, AGENT, RETRIEVER, EVALUATOR … | Span tree, waterfall *(secondary)* | OTLP-native, free self-host (ELv2); `OPENINFERENCE_HIDE_*` default **off** |
| **Braintrust** ([traces](https://www.braintrust.dev/docs/observe/examine-traces), [experiments](https://www.braintrust.dev/docs/evaluate/interpret-results)) | logs + experiments; typed spans incl. `score` | Spans / Thread / Timeline; detail tabs incl. Raw JSON | **Baseline diff, "order by regressions"**; `ExternalAttachment` references objects without uploading |
| **W&B Weave** ([trace tree](https://docs.wandb.ai/weave/guides/tracking/trace-tree)) | thread → trace → call | Three panes; flame graph; **Timeline / Peers / Siblings / Stack scrubbers** | Scrubbers navigate large trees without overwhelm |
| **AgentOps** ([concepts](https://docs.agentops.ai/v2/concepts/core-concepts)) | session root; AGENT / TASK / WORKFLOW / LLM / TOOL | Session replay, waterfall | MIT, self-hostable |
| **Helicone** ([sessions](https://docs.helicone.ai/features/sessions)) | proxy logging; session id/path/name | Path hierarchy | "Group by function, not by time"; **maintenance mode since Mar 2026** ([blog](https://www.helicone.ai/blog/joining-mintlify)) |
| **OpenLLMetry / Traceloop** ([privacy](https://www.traceloop.com/docs/openllmetry/privacy/traces)) | OTel `@workflow` / `@task` | via backend | **Content captured by default**; acquired by ServiceNow (Mar 2026) |
| **OpenAI Agents SDK** ([tracing](https://openai.github.io/openai-agents-python/tracing/)) | trace (`workflow_name`, `group_id`) → typed spans (`agent_span`, `function_span`, `generation_span`, `handoff_span`, `guardrail_span`, `custom_span`) | OpenAI dashboard; pluggable processors | `trace_include_sensitive_data` **defaults to True** |
| **Pydantic Logfire** ([concepts](https://pydantic.dev/docs/logfire/get-started/concepts/)) | OTel traces + SQL | Live view | **Pending spans**: a span is exported when work *starts*, so in-progress and crashed work stays visible |
| **MLflow Tracing** ([docs](https://mlflow.org/docs/latest/genai/tracing/)) | experiment / trace / session; 10 span types | Trace, timeline, chat | Apache 2.0; artifacts store built in |
| **Inspect AI (UK AISI)** ([eval logs](https://inspect.aisi.org.uk/eval-logs.html), [viewer](https://inspect.aisi.org.uk/log-viewer.html)) | `EvalLog` (status started/success/cancelled/error, plan, results, stats, error) → samples (events, scores, attachments) | `inspect view` live local server; VS Code pane; **`inspect view bundle` static site**; `read_eval_log(header_only=True)` for list views | **Closest analogue to STATUTE**: a serious dashboard over a directory of log files, header-only reads, static export, `status: started` written early |
| **SWE-agent / OpenHands trajectory viewers** | trajectory file | Flat step list | Trivial to deploy; no tree |

---

## B3. OpenTelemetry GenAI semantic conventions

- In semconv v1.42.0 (12 Jun 2026) the `gen_ai.*` conventions moved to [open-telemetry/semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai). Every span in the [agent spans doc](https://raw.githubusercontent.com/open-telemetry/semantic-conventions-genai/main/docs/gen-ai/gen-ai-agent-spans.md) carries **Development** status; nothing is Stable.
- `gen_ai.operation.name` includes `chat`, `embeddings`, `retrieval`, `create_agent`, `invoke_agent`, `execute_tool`, `invoke_workflow`, `plan`, memory operations.
- Content attributes (`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, tool arguments/results) are **Opt-In**: "Instrumentations SHOULD NOT capture this attribute by default."
- Open proposals: [#35](https://github.com/open-telemetry/semantic-conventions-genai/issues/35) (tasks, actions, teams, **artifacts**, memory) and [#462](https://github.com/open-telemetry/semantic-conventions-genai/issues/462) (durable execution: a **logical execution identity separate from trace IDs**, checkpoint/resume, span links for retries). #462 is the closest standards effort to STATUTE's `run_version` + upstream-pointer model.

**Implication.** STATUTE's scripts are not GenAI operations and should not be labelled `invoke_agent`/`execute_tool`. Only the Claude Code wrapper layer is GenAI, and Claude Code labels that itself.

---

## B4. Workflow, CI and lineage tools

### Dagster — closest semantic model

- **Asset-centric** UI: asset catalog, per-asset Overview / Events / Checks / Lineage tabs, global asset lineage, run Gantt, structured event log separate from raw compute logs, re-execute All / Selected / From failure ([webserver](https://docs.dagster.io/guides/operate/webserver)).
- **Event record**: `EventLogEntry{run_id, timestamp, step_key, level, user_message, error_info, dagster_event{event_type_value, …}}` ([internals](https://docs.dagster.io/api/dagster/internals)). Event types group into run (`RUN_START`, `RUN_SUCCESS`, `RUN_FAILURE` …), step (`STEP_START`, `STEP_SUCCESS`, `STEP_FAILURE`, `STEP_UP_FOR_RETRY` …), asset (`ASSET_MATERIALIZATION`, `ASSET_CHECK_EVALUATION`, `ASSET_FAILED_TO_MATERIALIZE` …).
- **Materialization metadata** (row counts etc.) is plotted as a time series ([metadata](https://docs.dagster.io/guides/build/assets/metadata-and-tags)) — maps to STATUTE's `stats_summary`.
- **Asset checks**: `AssetCheckResult{passed, check_name, severity WARN|ERROR, metadata}`; `blocking=True` stops downstream ([asset checks](https://docs.dagster.io/api/dagster/asset-checks)) — maps to STATUTE's quality gates.
- **Staleness**: `code_version` + `data_version` (hash of code version and input data versions). UI shows **"Unsynced"** with cause ("Upstream data version change", "Code version changed", "New materialization") and a "Materialize unsynced" action; time-based *freshness* is kept separate ([versioning](https://docs.dagster.io/guides/build/assets/asset-versioning-and-caching)).
- External producers can report materializations via REST without Dagster orchestrating ([external assets](https://docs.dagster.io/api/rest-apis/external-assets-rest-api)).

### dbt — machine-readable artifact discipline

- Every invocation writes versioned JSON artifacts (`manifest.json`, `run_results.json`, `catalog.json`, `sources.json`) with shared `metadata{dbt_schema_version, generated_at, invocation_id}` and **published JSON Schemas** ([artifacts](https://docs.getdbt.com/reference/artifacts/dbt-artifacts)).
- `run_results.json` results carry `status`, `timing[{name, started_at, completed_at}]`, `execution_time`, `message` ([run results](https://docs.getdbt.com/reference/artifacts/run-results-json)) — the template for the timing STATUTE lacks.
- Comparison and replay as selectors: `state:modified`, `result:error`, `source_status:fresher+`, `dbt retry` ([methods](https://docs.getdbt.com/reference/node-selection/methods)).
- dbt Docs is a **static site generated from artifacts**; dbt Catalog adds **lenses** (colour lineage by status, test status, materialization) and **health signals** (Healthy / Caution / Degraded / Unknown) ([explore](https://docs.getdbt.com/docs/explore/explore-projects), [health](https://docs.getdbt.com/docs/explore/data-health-signals)).

### OpenLineage + Marquez — lineage standard

- `RunEvent{eventType START|RUNNING|COMPLETE|FAIL|ABORT|OTHER, eventTime, run{runId, facets}, job{namespace, name}, inputs[], outputs[], producer, schemaURL}` ([run cycle](https://openlineage.io/docs/spec/run-cycle)); `ParentRunFacet` for hierarchy; dataset `version` facet.
- Python client `FileTransport` writes JSONL with no server ([config](https://openlineage.io/docs/client/python/configuration/)).
- Marquez's last release is 0.50.0 (2024-10-23) ([GitHub](https://github.com/MarquezProject/marquez)); no staleness or check roll-up UI found.
- **Fit**: semantically exact (stage = job, `run_version` = runId, artifact = dataset with version); operationally heavy. Use as an **export format**, not the UI.

### Prefect, Temporal, Airflow, Argo

| Tool | Pattern worth taking | Source |
|---|---|---|
| Prefect | Typed + named states, **CRASHED distinct from FAILED** (infrastructure vs code); human-facing **artifacts with keyed version history** | [states](https://docs.prefect.io/v3/concepts/states), [artifacts](https://docs.prefect.io/v3/concepts/artifacts) |
| Temporal | Append-only event history as source of truth; Timeline / Compact / JSON history views; replay detects nondeterminism | [workflows](https://docs.temporal.io/workflows), [web UI](https://docs.temporal.io/web-ui) |
| Airflow 3 | **Grid** (tasks × runs) with Gantt integrated; 14 task-instance states incl. `upstream_failed`, `awaiting_input`; Required Actions page | [UI](https://airflow.apache.org/docs/apache-airflow/stable/ui.html), [tasks](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/tasks.html) |
| Argo Workflows | Artifacts as **clickable DAG nodes**, previews served under a **CSP that disables JavaScript** | [artifact visualization](https://argo-workflows.readthedocs.io/en/latest/artifact-visualization/) |

### CI consoles

- **GitHub Actions**: run → job → step; `status` + `conclusion`; `run_attempt`; "re-run failed jobs and their dependents"; **annotations** (`::warning file=,line=::msg`) and **job summaries** (Markdown via `$GITHUB_STEP_SUMMARY`) ([workflow commands](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands)).
- **GitLab**: stage vs job-dependency graph toggle; mini-graphs; `artifacts:reports` surfaced in merge-request widgets ([pipelines](https://docs.gitlab.com/ci/pipelines/)).
- **Jenkins**: Blue Ocean deprecated (July 2026); Pipeline Graph View plugin; Restart from Stage ([blue ocean](https://www.jenkins.io/doc/book/blueocean/)).
- **Kubeflow / MLflow**: run comparison as side-by-side scalar tables ([MLflow tracking](https://mlflow.org/docs/latest/ml/tracking/)).
- **Great Expectations / Monte Carlo**: validation results as **first-class pages** separate from run logs ([checkpoints](https://docs.greatexpectations.io/docs/core/trigger_actions_based_on_results/create_a_checkpoint_with_actions/)).

### Which model fits STATUTE

| Family | Fit | Reason |
|---|---|---|
| Task/run-centric (Airflow, GitHub Actions) | Partial | STATUTE stages take seconds and never retry; a grid of green squares wastes space. Take the run × stage grid, job summaries, file/line annotations |
| **Asset/materialization-centric (Dagster, dbt)** | **Best** | Every stage *materializes* versioned artifacts and records the upstream versions it consumed; the operator's questions are asset questions ("is the BRD current with the latest parse?") |
| Event-history-centric (Temporal) | Low | STATUTE's state is its artifacts; an append-only per-run event log is still worth having for timing and failure evidence |
| Lineage standard (OpenLineage) | Export only | Exact semantics, too much infrastructure for a UI |

**Replay.** STATUTE already supports a stronger form than Temporal's: pin upstream `run_version`s and re-run a deterministic stage to reproduce its artifact. A dashboard should offer "re-run this stage against these pinned inputs" (as a copyable command), not a history replayer.

---

## B5. Human-in-the-loop and curation patterns

### Runtime approval gates (orchestrators and CI)

| Tool | Runtime state | Identity | Expiry | Audit |
|---|---|---|---|---|
| GitHub environments ([docs](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/review-deployments)) | job *Waiting*; Approve / Reject + comment | `user` on approvals API | wait timer; ~30-day auto-fail *(community source)* | review history API |
| GitLab ([docs](https://docs.gitlab.com/ci/environments/deployment_approvals/)) | manual job → pipeline **blocked** | approval rules | delayed jobs | deployment approval history |
| Airflow 3.1+ ([HITL](https://airflow.apache.org/docs/apache-airflow/stable/tutorial/hitl.html)) | task state `awaiting_input`; **Required Actions** page | `responded_by` | `response_timeout` + defaults | `HITLDetail` |
| Prefect ([interactive](https://docs.prefect.io/v3/advanced/interactive)) | Paused / Suspended with typed input form | — | default 3600 s | state history |
| Temporal ([approval pattern](https://docs.temporal.io/design-patterns/approval)) | signal + `wait_condition` | in signal payload | timers | signals in history |
| LangGraph ([interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)) | `interrupt()` + checkpointer; node re-runs on resume | app-defined | app-defined | checkpoints |
| Backstage Scaffolder | **not native** — gated-workflow RFC [closed as not planned](https://github.com/backstage/backstage/issues/30429); practice is PR review | — | — | PR |

### Curation records on generated artifacts (catalogs, docs, tests)

- **DataHub** keeps UI edits in separate *editable* aspects that re-ingestion never overwrites; known failure mode is **orphaned edits** when the ingested entity disappears ([issue](https://github.com/datahub-project/datahub/issues/11642)). Closest analogue to STATUTE's `brd_annotations.json`.
- **GitHub PR review comments** are anchored to a line and marked **"Outdated"** when the anchor changes, but stay visible ([docs](https://docs.github.com/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/commenting-on-a-pull-request)).
- **Snapshot / approval testing** (`cargo insta review`, ApprovalTests `.received` vs `.approved`) — the natural shape of "human sign-off on deterministic generated output".
- **dbt** keeps human documentation in source YAML keyed by node, never in generated artifacts.

**Implication.** In generation pipelines, human review is a **record keyed to a stable ID and an artifact version**, not a paused run. STATUTE should not add blocking runtime gates; it should make annotation status (applied / outdated / orphaned) and the SME-review queue visible.

---

## B6. Distributed tracing and APM

### OpenTelemetry building blocks (status as of Sep 2026)

| Concept | Status / key fact | STATUTE implication |
|---|---|---|
| **Span links** | For causal relationships where "we cannot predict when the subsequent operations will start" ([traces concepts](https://opentelemetry.io/docs/concepts/signals/traces/)); in Python, add at span creation so samplers see them | Exactly "stage N consumed pinned run X of stage M" |
| **Span events** | **Being deprecated** in favour of log-based events correlated by context ([blog](https://opentelemetry.io/blog/2026/deprecating-span-events/), [OTEP 4430](https://github.com/open-telemetry/opentelemetry-specification/blob/main/oteps/4430-span-event-api-deprecation-plan.md)) | Stage findings should be log records with `trace_id`/`span_id`, not span events |
| **Logs data model** | Stable; records carry TraceId/SpanId ([spec](https://opentelemetry.io/docs/specs/otel/logs/data-model/)) | One `events.jsonl` per stage run is consistent with it |
| **Resources / Entities** | Resources stable; Entity data model still Development ([spec](https://opentelemetry.io/docs/specs/otel/entities/data-model/)) | Use plain resource attributes (`service.name=statute`, `service.version=<git sha>`) |
| **CI/CD semconv** | Release Candidate; pipeline-run and task-run spans; `cicd.pipeline.task.run.result` ∈ {success, failure, timeout, skip, cancellation, error} ([cicd spans](https://opentelemetry.io/docs/specs/semconv/cicd/cicd-spans/)) | Reuse this result vocabulary instead of inventing one |
| **OTLP File Exporter** | Development; JSON Lines of `TracesData`/`LogsData` ([spec](https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/)); Python `opentelemetry-exporter-otlp-json-file` 0.66b0, Beta ([PyPI](https://pypi.org/project/opentelemetry-exporter-otlp-json-file/)) | Optional export; free local viewers: [otel-tui](https://github.com/ymtdzzz/otel-tui), [otel-desktop-viewer](https://github.com/CtrlSpice/otel-desktop-viewer) |
| **Env-var context propagation** | **Release Candidate**, cannot be declared stable before 2026-11-02 ([spec](https://opentelemetry.io/docs/specs/otel/context/env-carriers/)); Python environment carriers since API 1.40 | `TRACEPARENT` is the right carrier; Claude Code already injects it into Bash |

### Trace UIs

| Product | Layout | Comparison / critical path | Correlation |
|---|---|---|---|
| Jaeger v2 ([docs](https://www.jaegertracing.io/docs/2.21/)) | Timeline + minimap + summary | Critical path on by default; **trace diff** (grey both / red A-only / green B-only) | `linkPatterns` deep links from span tags |
| Grafana Tempo + Traces Drilldown ([GA](https://grafana.com/blog/traces-drilldown-generally-available/)) | Query-less RED views | **Comparison** tab ranks attributes that differ from baseline | Trace-to-logs with time shifts |
| Honeycomb ([waterfall](https://docs.honeycomb.io/reference/honeycomb-ui/query/trace-waterfall)) | Header, minimap, waterfall, sidebar (Fields / Events / Links) | **BubbleUp** vs baseline across all dimensions | Events and links in sidebar |
| Datadog APM ([trace view](https://docs.datadoghq.com/tracing/trace_explorer/trace_view/)) | Flame graph / Span list / Waterfall / Map; "Focus" re-roots | — | Logs tab; hovering a log draws a time marker |
| New Relic ([docs](https://docs.newrelic.com/docs/distributed-tracing/ui-data/understand-use-distributed-tracing-ui/)) | Waterfall; filter to error/anomalous spans | Anomaly = >2σ slower over 6 h and >10% of trace | — |
| Elastic APM ([traces UI](https://www.elastic.co/docs/solutions/observability/apm/traces-ui)) | Waterfall with critical path | — | Service-map flyout to traces/logs/SLOs |

### Does one-trace-per-pipeline fit STATUTE? No.

| Model | Problem |
|---|---|
| M1 — one trace per pipeline run, one span per stage | No process owns the root span (no orchestrator); re-running one stage mutates a "finished" trace or orphans the new span; backends mishandle spans arriving minutes apart — Tempo recommends **"adopting span links to split traces intentionally"** ([long-running traces](https://grafana.com/docs/tempo/latest/troubleshooting/querying/long-running-traces/)) |
| **M2 — one bounded trace per stage invocation + span links to the upstream stage runs it consumed (recommended)** | Each trace is complete; re-runs are new traces linking to pinned upstreams. Workflow SDK made the same choice: "one bounded trace per invocation" ([tracing](https://workflow-sdk.dev/docs/observability/tracing)) |
| M3 — hybrid with a pipeline root span | Needs a begin/end process; two shapes to render. Optional only |

A *pipeline run* becomes a **grouping attribute** (`statute.pipeline_run_id`) drawn by the dashboard, not an OTel trace. When the stage runs under Claude Code, its trace simply nests under the inherited `TRACEPARENT`.

**Critical path** is trivial for an eight-stage chain; replace it with a **provenance path** — the exact upstream versions that fed an output.

---

## B7. Developer platform dashboards

| Product | Pattern | What STATUTE should take |
|---|---|---|
| Backstage ([system model](https://backstage.io/docs/features/software-catalog/system-model)) | Typed entity model with owners and relations; entity pages with tab groups | **Entity pages** for PL/SQL objects, tables, rules, requirements with tabs (Overview, Logic, Rules, Data, Diagrams, Provenance) |
| Vercel ([build logs](https://vercel.com/docs/deployments/logs)) | Deployment list → immutable deployment page; build logs separate from runtime logs, stated truncation | Stage-run list; **immutable per-run URLs**; stated truncation policy |
| Cloudflare ([quick search](https://blog.cloudflare.com/quick-search-beta/), [shortcuts](https://developers.cloudflare.com/changelog/post/2026-05-04-keyboard-shortcuts/)) | ⌘K search; `g`-chord navigation | Command palette later |
| GitHub Actions ([logs](https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs)) | Run graph; **line-level log deep links**; attempts dropdown | Attempts per stage (STATUTE already keeps every run); deep links |
| GitLab ([pipelines](https://docs.gitlab.com/ci/pipelines/)) | Hover a job highlights its prerequisites | Hover a stage run highlights its pinned upstream runs |
| Linear ([redesign](https://linear.app/now/how-we-redesigned-the-linear-ui), [refresh](https://linear.app/now/behind-the-latest-design-refresh)) | Dense lists, dimmed chrome; "not every element should carry equal visual weight" | Data-first density |
| Headlamp / k9s ([k9s](https://github.com/derailed/k9s)) | Kubernetes Dashboard archived Jan 2026 → Headlamp; k9s `:pulses` health grid, `:xray` dependency tree | **Stage × recent-runs health grid** |

Suggested URL scheme (everything deep-linkable): `/` · `/pipeline-runs/:id` · `/stages/:stage/runs/:runVersion?tab=` · `/findings?severity=&stage=` · `/trace/:kind/:id` · `/compare?a=&b=`.

---

## B8. Frontend libraries

Versions as of late September 2026; sizes are orders of magnitude.

| Library | Version / status | License | Notes for STATUTE |
|---|---|---|---|
| Vite | 8.0 (Rolldown default) ([blog](https://vite.dev/blog/announcing-vite8)) | MIT | Build-time only. **Dev server has a file-read CVE record** (CVE-2025-30208, Windows backslash CVE-2025-62522, CVE-2026-39364) — never use it as the viewer |
| React | 19.x | MIT | — |
| Tailwind CSS | 4.3.x; 4.2 EOL May 2026 ([endoflife](https://endoflife.date/tailwind-css)) | MIT | Short minor support windows |
| shadcn/ui | Base UI default since Jul 2026; Radix still supported ([changelog](https://ui.shadcn.com/docs/changelog/2026-07-base-ui-default)) | MIT | Copy-in, owned code |
| TanStack Query | v5 | MIT | Polling + cache + ETag-friendly |
| TanStack Router | v1, typed search params | MIT | URL state for filters/tabs |
| React Router | v8 (Jun 2026), ESM-only, React 19.2.7+ ([InfoQ](https://www.infoq.com/news/2026/08/react-route-v8/)) | MIT | Alternative to TanStack Router |
| TanStack Table | **v9 stable 2026-08-04** ([InfoQ](https://www.infoq.com/news/2026/07/tanstack-table-v9-beta/)) | MIT | Headless; render a semantic `<table>` |
| TanStack Virtual / react-virtuoso | v3 / 4.18 | MIT | Virtualisation breaks Ctrl+F and screen-reader browsing — only above ~1–2k rows |
| React Flow (`@xyflow/react`) | 12.12.0 (2026-09-24) | MIT (attribution) | DOM nodes, keyboard-focusable, `ariaLabelConfig`; ideal for ≤ a few hundred nodes |
| dagre (`@dagrejs/dagre`) | 3.1.1 | MIT | Layered layout, ~40 KB; fine for a stage DAG |
| ELK.js | 0.12.0, ~1.46 MB | **EPL-2.0 OR GPL-3.0+** | License needs legal review; Mermaid 12 bundles ELK |
| Cytoscape.js | 3.34 | MIT | Canvas → weak screen-reader support; only for >1k-node graphs, with a list fallback |
| CodeMirror 6 | 6.43.x | MIT | Read-only JSON/SQL viewer if needed |
| Monaco | 2–5 MB in bundle | MIT | **Overkill for read-only**; not mobile-supported |
| Shiki | fine-grained bundles, ~20 KB JS engine | MIT | Static highlighting — best fit for showing a source line window |
| Mermaid | **12.0.0 (2026-09-10)**, ELK default, ES2024 baseline ([release](https://github.com/mermaid-js/mermaid/releases/tag/mermaid@12.0.0)) | MIT | Large — lazy-load; **high advisory churn** (B9) |
| react-markdown | 10, "secure by default", raw HTML escaped | MIT | Never add `rehype-raw` without `rehype-sanitize` |
| DOMPurify | 3.4.x; several 2025–26 CVEs | Apache-2.0 / MPL-2.0 | Pin ≥ 3.4.6 if used |
| Recharts / visx / uPlot / ECharts | 3.x / v4 / 1.6 / 6.0 | MIT / MIT / MIT / Apache-2.0 | Not needed until run-history trends exist; hand-rolled SVG sparklines suffice |
| htmx | 2.x supported indefinitely; 4.0 on npm `next` | 0BSD | Option for a Python-rendered MVP |
| Starlette | 1.x; recent StaticFiles traversal fixes | BSD-3 | Hardened static serving if a Python framework is used |
| stdlib `http.server` | — | PSF | "Not recommended for production"; **follows symlinks; binds all interfaces by default** — every check must be written by hand |

### Should the MVP be React?

The research track's honest assessment: a **Python-served, read-only, localhost-bound viewer with polling** covers ~80 % of the value (run list, stage-run detail, findings, artifacts, BRD view, diagrams, diffs) without bringing a Node toolchain into a Python repository. React earns its place with interactive graph exploration, a zoomable waterfall, large virtualised tables, ⌘K, rich URL state, or a combined STATUTE + MARS console. **Either way, define a versioned JSON read API as the stable contract** so the front end can be replaced without touching the back end. (The report's recommendation, which weighs the user's stated React preference and the MARS precedent, is in §39.)

---

## B9. Real-time transport, visual design and rendering security

### Transport

| Option | Fit | Replay | Caveats |
|---|---|---|---|
| **Polling with ETag** | **Best for MVP** — stages take seconds; files are the truth | Not needed: every poll reads full state | 2 s while active, 15–30 s idle, pause when tab hidden |
| SSE | Good later for event-log tailing | `Last-Event-ID` = byte offset / sequence in an append-only `events.jsonl` ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)) | HTTP/1.1 limit of 6 connections per browser+domain across tabs |
| WebSockets | Not justified — no client→server traffic | Must be hand-built | Cross-site WebSocket hijacking without Origin checks ([OWASP](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html)) |
| File watching | Only as an accelerator | **Lossy**: Windows `ReadDirectoryChangesW` discards the whole buffer on overflow ([MS docs](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-readdirectorychangesw)); watchdog needs polling on network shares | Always reconcile with a rescan |

**Writer discipline matters more than transport**: write JSON to a temp file then `os.replace`; update `latest.json` last. STATUTE today writes in place (Appendix A §A5).

### Visual design references

- **IBM Carbon status indicators** ([pattern](https://carbondesignsystem.com/patterns/status-indicator-pattern/)): icon / shape / badge / differential; "relying solely on color … is insufficient"; red error, orange serious warning, yellow warning, green success, blue information, gray draft/incomplete, purple outlier/undefined.
- **Carbon data table** ([usage](https://carbondesignsystem.com/components/data-table/usage/)): row heights 24 / 32 / 40 / 48 / 64 px.
- **GitHub Primer** ([color](https://primer.style/accessibility/design-guidance/color-considerations/)): text 4.5:1, non-text 3:1; prefix labels with words ("Pass: …").
- **Atlassian lozenge** ([examples](https://atlassian.design/components/lozenge/lozenge/examples)): `moved` = "changed and requires attention" — a natural fit for *Unsynced*.
- **Vercel Geist** ([colors](https://vercel.com/geist/colors)): 10-step scales (1–3 backgrounds, 4–6 borders, 9–10 text).
- **WCAG 2.2**: [1.4.1](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html) no colour-only meaning; [1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) 4.5:1; [1.4.11](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html) 3:1 — its examples include **dashboard status icons and graph lines**.
- **Avoiding "AI-looking" UI**: Anthropic's frontend-design post lists over-used fonts, "purple gradients on white backgrounds" and predictable layouts ([Claude blog](https://claude.com/blog/improving-frontend-design-through-skills)); community lists add glassmorphism, gradient text, fake metric grids, rows of three identical cards ([no-slop-ui](https://github.com/LeoStehlik/no-slop-ui)).

### Rendering generated content safely

STATUTE ingests third-party PL/SQL. Identifiers, comments, `COMMENT ON` strings and literals flow into `brd.md`, Mermaid labels, graph labels and JSON — **a stored-XSS path even though the pipeline is deterministic**.

- **Mermaid advisories** ([list](https://github.com/mermaid-js/mermaid/security/advisories)): ~10 between Aug 2025 and Aug 2026, including critical XSS via architecture `iconText`, sequence-label XSS ([CVE-2025-54881](https://github.com/advisories/GHSA-7rqq-prvp-x9jh)), `classDef` HTML injection in state diagrams ([CVE-2026-41149](https://www.sentinelone.com/vulnerability-database/cve-2026-41149/)), CSS injection, prototype pollution, DoS. Snyk showed stored XSS with `securityLevel: 'loose'` ([Snyk](https://labs.snyk.io/resources/exploiting-diagram-renderers/)). Mitigate: pin latest; `securityLevel: 'sandbox'` or pre-render to SVG shown via `<img>`; never honour `%%{init}%%`; render with a timeout.
- **Markdown**: escape raw HTML; allow only http/https/mailto/relative links; `rel="noopener noreferrer"`.
- **CSP**: `default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'` ([OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)).
- **Local server**: bind `127.0.0.1`; **validate the Host header** to block DNS rebinding (the cause of several 2025–26 MCP-server CVEs, e.g. [CVE-2025-10193](https://www.sentinelone.com/vulnerability-database/cve-2025-10193/)); GET only; map IDs to paths server-side, `resolve()` and check `is_relative_to(root)`, reject absolute/drive/UNC/backslash/NUL; refuse symlinks out of root; `X-Content-Type-Options: nosniff`; serve `.md`/`.mmd`/`.json` as text or JSON, never HTML.

---

## B10. Pattern catalogue and applicability to STATUTE

| # | Pattern | Seen in | STATUTE verdict |
|---|---|---|---|
| P1 | Three panes: list → tree/waterfall → tabbed detail (Attributes, Events, Links, Artifacts, Raw) | Weave, Braintrust, Langfuse, Honeycomb, Datadog | **Adopt** for stage-run detail |
| P2 | Several views of one execution (tree / timeline / graph) | Langfuse, Braintrust, Datadog | **Adopt, limited**: lineage graph + timeline; no chat/thread view |
| P3 | Typed span kinds driving icons and filters | Langfuse, OpenInference, MLflow | **Adapt**: a small STATUTE taxonomy (pipeline run, stage run, agent invocation, script execution, work item, check, artifact) |
| P4 | Grouping above the trace (session / thread) | all | **Adapt**: a *pipeline run* = lineage closure of a terminal stage run |
| P5 | Aggregated vs expanded graph | Langfuse, Arize | **Adopt**: latest-per-stage vs every run_version |
| P6 | Scores attached to runs | Braintrust, Phoenix, Dagster asset checks | **Adopt**: quality gates and counts as named checks — deterministic, not LLM judges |
| P7 | Experiments, baselines, diffs ordered by regression | Braintrust, Jaeger diff, Tempo comparison, dbt `state:modified` | **Adopt** — determinism makes every diff a real signal |
| P8 | Artifacts by reference (path + hash), never inlined | Braintrust, Inspect, Argo | **Adopt** |
| P9 | Write "started" early so crashes stay visible | Logfire pending spans, Inspect `status: started` | **Adopt** — STATUTE's biggest blind spot |
| P10 | Overwhelm control: severity filters, focus/zoom, find-in-trace, scrubbers | Langfuse, Weave, Honeycomb | **Adopt** for findings and statements |
| P11 | Token / cost / TTFT columns | all LLM tools | **Agent wrappers only**; never on scripts |
| P12 | Content capture off by default; masking | Claude Code, OTel GenAI, LangSmith, Logfire | **Adopt**: no source text or prompts by default |
| P13 | Static / file-based viewer over a log directory | Inspect bundle, dbt Docs, GX Data Docs | **Adopt** as the MVP architecture |
| P14 | Asset staleness ("Unsynced" with cause) separate from freshness | Dagster, dbt health | **Adopt** — the single most useful derived signal |
| P15 | Run × stage health grid | Airflow grid, k9s pulses, Grafana status history | **Adopt** for history |
| P16 | Curation records keyed to stable IDs with Outdated / Orphaned states | DataHub, GitHub PR comments, snapshot tests | **Adopt** for annotations |
| P17 | Runtime approval gates (waiting state) | GitHub, GitLab, Airflow, Temporal | **Reject** for generation; possible later only at publish/sign-off |
| P18 | Chat / trajectory transcript views, prompt panels, playgrounds | LangSmith, Langfuse, AgentOps | **Reject** for STATUTE (MARS-relevant) |
