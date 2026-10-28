// Typed client for the STATUTE Console read API (console/server). GET only.

export type RunState = "running" | "succeeded" | "failed" | "crashed";
export type Freshness = "current" | "unsynced" | "upstream_unsynced" | "pinned" | "unknown" | "never_run";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Category = "run" | "lineage" | "source" | "content" | "review";

export interface Evidence { label: string; path: string | null }
export interface Upstream {
  stage: string; run_version: string | null; resolved: "latest" | "pinned" | "unknown";
  present: boolean; optional: boolean; source: "run_status" | "run_meta";
}
export interface StageRun {
  stage: string; id: string; run_version: string | null; attempt: boolean; dir: string;
  state: RunState; state_basis: "recorded" | "inferred"; state_reason: string | null; published: boolean;
  started_at: string | null; finished_at: string | null; duration_ms: number | null;
  timing_basis: "recorded" | "partial" | "inferred" | null; generated_at: string | null;
  upstream: Upstream[]; provenance_gaps: string[]; degraded: { input: string; reason: string }[];
  summary: { kind: string; values: Record<string, unknown> } | null;
  progress: { done: number; total: number; unit: string } | null;
  current_item: { kind: string; id: string } | null;
  error: { class: string; message: string; where: string | null; last_item: { kind: string; id: string } | null } | null;
  instrumented: boolean; code_version: string | null; traceparent: string | null; events: number | null;
  evidence: Evidence[];
}
export interface FreshnessInfo { value: Freshness; causes: { kind: string; stage?: string; text: string }[] }
export interface Finding {
  id: string; category: Category; severity: Severity; kind: string; title: string; detail: string | null;
  stage: string | null; run_version: string | null; subject: { kind: string; id: string } | null;
  location: { file?: string; file_id?: string; line?: number | null; object_id?: string; statement_id?: string } | null;
  related: { kind: string; id: string }[]; evidence: Evidence[]; next_step: string | null; count: number; members: string[];
}
export interface PipelineRun {
  id: string; anchor: string; members: Record<string, string>; inferred_members: string[];
  missing_members: { stage: string; run_version: string }[];
  consistency: "consistent" | "inconsistent" | "incomplete";
  inconsistencies: { stage: string; versions: { run_version: string; consumed_by: string[] }[] }[];
  is_current: boolean; superseded_by: string[]; started_at: string | null; finished_at: string | null; span_ms: number | null;
  counts: Record<string, number>; open_matters: Record<string, number>; rules_need_review: number | null;
  diagrams: number; deliverables: { label: string; stage: string; run_version: string; artifact_id: string; path: string }[];
}
export interface StageCard {
  stage: string; title: string; n: number; purpose: string; latest: StageRun | null; newest: StageRun | null;
  freshness: FreshnessInfo; key_stat: string[]; worst_finding: { severity: Severity; count: number } | null;
  run_count: number; attempt_count: number; agent: string;
}
export interface RecentRow {
  stage: string; id: string; run_version: string | null; attempt: boolean; state: RunState; state_basis: string;
  published: boolean; started_at: string | null; finished_at: string | null; duration_ms: number | null;
  timing_basis: string | null; instrumented: boolean;
}
export interface Status {
  generated_at: string;
  corpus: { files: number; code_lines: number; lines: number; roles: Record<string, number>; source_display: string | null; source_reachable: boolean };
  running: string[]; stages: StageCard[]; attention: Finding[]; finding_counts: Record<Severity, number>;
  pipeline_run: PipelineRun | null;
  next_steps: { summary: string; stages: { stage: string; reason: string }[]; commands: string[]; running: string[] };
  recent: RecentRow[]; latest_activity: string | null;
  annotations: { present: boolean; error: string | null; applied: number; problems: number };
  workspace: Workspace;
  kpis: { overall_pct: number; stages_done: number; stages_total: number; files: number | null; code_lines: number | null;
    objects: number | null; statements: number | null; tables: number | null; columns: number | null; rules: number | null;
    sme: number | null; requirements: number | null; gaps: number; gaps_high: number; artifacts: number; artifact_bytes: number; span_ms: number | null };
}
export interface TimelineRow { stage: string; run_version: string; start: string; end: string; basis: string; duration_ms: number | null; state: RunState }
export interface PipelineDetail extends PipelineRun {
  member_runs: { stage: string; title: string; run: StageRun | null; inferred: boolean; is_published: boolean; latest_run_version: string | null }[];
  timeline: { rows: TimelineRow[]; gaps: { after: string; before: string; start: string; end: string; ms: number }[]; span_ms: number; in_stage_ms: number; between_ms: number; partial: boolean };
  lineage: {
    nodes: { stage: string; title: string; run_version: string | null; state: RunState | null; freshness: string | null; inferred: boolean; provenance_gaps: string[] }[];
    edges: { from: string; to: string; run_version: string | null; resolved: string; present: boolean | null; optional: boolean; matches_member: boolean | null }[];
  };
}
export interface StageRunDetail extends StageRun {
  title: string; freshness: FreshnessInfo | null; summary_text: string[];
  consumers: { stage: string; run_version: string; published: boolean }[];
  upstream_latest: Record<string, string | null>; pipeline_runs: string[]; rerun_command: string;
  run_meta: Record<string, unknown> | null;
}
export interface Items { columns: string[]; rows: (Record<string, unknown> & { id: string; kind: string; event_status?: string })[] }
export interface StageFinding { severity: Severity; kind: string; title: string; detail: string | null; location: Record<string, unknown> | null }
export interface Artifact { id: string; path: string; bytes: number; kind: string; suffix: string }
export interface ArtifactContent extends Artifact { text: string | null; truncated: boolean; sha256?: string; content_type?: string; reason?: string }
export interface ConsoleEvent {
  event_id: string; seq: number; time: string; type: string; stage: string; run_version: string | null;
  status?: string; severity?: Severity | "warning" | "error"; item?: { kind: string; id: string };
  progress?: { done: number; total: number; unit: string }; message?: string; data?: Record<string, unknown>;
  traceparent?: string; run_id?: string;
}
export interface HealthCheck { id: string; name: string; status: "pass" | "warn" | "fail" | "info" | "not_applicable"; summary: string; details: string[]; evidence: Evidence[]; remediation: string | null }
export interface EvidenceRef { kind: string; id: string; label: string; stage: string | null; run_version: string | null; detail: string | null }
export interface EvidenceEntity {
  kind: string; id: string; title: string; facts?: Record<string, unknown>; description?: string; condition?: string;
  requirement?: { text: string; formal: string; modality: string; type: string; verification: string; needs_review: boolean; owner: string | null; priority: string | null } | null;
  location?: { file_id?: string | null; file?: string | null; line?: number | null; object_id?: string; statement_id?: string; table?: string; constraint?: string } | null;
  provenance: EvidenceRef[]; appears_in?: Record<string, unknown>[]; gaps?: { id: string; title: string; severity: Severity }[];
  rules?: { id: string; name: string; line?: number; category?: string; confidence?: string }[];
  related_rules?: { id: string; name: string | null }[]; columns?: Record<string, unknown>[]; checks?: Record<string, unknown>[];
  foreign_keys?: Record<string, unknown>[]; crud?: Record<string, string>; hazards?: Record<string, unknown>[];
  used_by?: { id: string }[]; objects?: { id: string }[]; warnings?: string[]; parse_issues?: string[]; note?: string;
  pipeline_run: string | null;
}
export interface SourceWindow { file: string; available: boolean; reason?: string; located_via?: string; focus?: number; lines: { n: number; text: string }[] }
export interface CompareResult {
  a: string; b: string; identical: boolean;
  stages: { stage: string; a: string | null; b: string | null; same_run: boolean; metric_deltas: { metric: string; a: unknown; b: unknown }[]; files_changed: string[]; files_added: string[]; files_removed: string[]; files_compared: number }[];
  rules: { added: { id: string; name: string }[]; removed: { id: string; name: string }[]; changed: { id_a: string; id_b: string; changes: Record<string, { a: unknown; b: unknown }> }[]; renumbered: { id_a: string; id_b: string; name: string }[]; count_a: number; count_b: number };
  gaps: { opened: { title: string; severity: Severity }[]; closed: { title: string; severity: Severity }[]; count_a: number; count_b: number };
}
export interface GridStage { stage: string; title: string; runs: { id: string; run_version: string | null; state: RunState; state_basis: string; published: boolean; attempt: boolean; started_at: string | null; duration_ms: number | null; upstream: { stage: string; run_version: string | null }[] }[] }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, params?: Record<string, string | number | undefined | null>): Promise<T> {
  const qs = params
    ? "?" + Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&")
    : "";
  const res = await fetch(`/api/v1${path}${qs === "?" ? "" : qs}`, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error ?? msg; } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const runPath = (stage: string, id: string) => `/stages/${stage}/runs/${encodeURIComponent(id)}`;

/* ---- catalogue-style tabs ---------------------------------------------------- */
export interface Workspace { project: string; repo: string; output_dir: string; source_dir: string | null; brd_name: string | null; system: string | null }
export interface AgentRow {
  stage: string; n: number; title: string; agent: string; description: string; tools: string | null; type: string;
  llm_in_generation: boolean; script: string; spec: string; artifact: string; artifact_bytes: number;
  state: RunState | null; published_state: RunState | null; freshness: Freshness | null; run_version: string | null;
  duration_ms: number | null; timing_basis: string | null; instrumented: boolean | null; requires: string[]; optional: string[];
}
export interface TraceEntry {
  step: number; object: string; line: number | null; end_line: number | null; scope: string; depth: number | null;
  kind: "control_flow" | "data_access" | "call" | "transaction" | "exception" | "assignment" | "other";
  operation: string; target: string; flow: string; statement_id: string; writes: string[]; reads: string[]; manual_review: boolean;
}
export interface TraceData { objects: string[]; entries: TraceEntry[]; counts: Record<string, number>; run_version: string | null }
export interface RuleRow {
  rule_id: string; name: string; category: string; confidence: string; requires_sme_review: boolean; is_enforced: boolean | null;
  pattern: string; signal_strength: number; rule_set: string | null; condition: string; description: string; source_kind: string;
  object_id: string | null; line: number | null; statement_id: string | null; table: string | null; constraint: string | null;
  is_duplicated: boolean; requirement: string | null; modality: string | null; verification: string | null;
}
export interface RulesData { rules: RuleRow[]; stats: Record<string, unknown>; rule_sets: { rule_set_id: string; name: string; rule_count: number }[]; error_handling: { name: string; category: string; line: number | null; object_id: string | null }[]; run_version: string | null }
export interface CatalogueEntry { stage: string; stage_title: string; run_version: string; path: string; name: string; ext: string; bytes: number; id: string; kind: string }
export interface BrdDoc { name: string; system: string | null; run_version: string; bytes: number; content: string; artifact_id: string; generated_at: string | null }
export interface DataModel {
  tables: { table: string; columns: number; pk: string[] | string | null; fks: string[]; checks: number; file: string | null; line: number | null; used_by: Record<string, string>; comment: string | null }[];
  stats: Record<string, number>; erd: string | null; objects: string[]; run_version: string | null;
}
export interface DiagramsData { diagrams: { file: string; title: string; type: string; nodes: number; edges: number; object_id?: string; oversize: boolean; source: string | null }[]; quality: Record<string, unknown>; warnings: { kind: string; diagram: string; detail: string }[]; node_budget: number; run_version: string | null }
export interface Quality {
  score: number; total_rules: number; by_confidence: Record<string, number>; by_category: Record<string, number>; sme_review: number;
  gaps_by_type: Record<string, number>; gaps_by_severity: Record<string, number>; verification: Record<string, number>;
  requirements: number; unowned: number; gates: { name: string; value: number | null; threshold: number | null; fmt: string }[];
  suites: { checks: number; suites: number; note: string };
}
