import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { api, runPath, type CompareResult, type FreshnessInfo, type HealthCheck, type PipelineRun } from "../api";
import { stageName, stageNo } from "../lib/format";
import { DataTable, Empty, ErrorBox, FreshnessBadge, Icon, Loading, PageHeader, Panel, Pill, SeverityBadge } from "../components/ui";
import { useHealth } from "../queries";

/* ---------------------------------------------------------------- compare -- */
export function ComparePage({ a, b }: { a?: string; b?: string }) {
  const navigate = useNavigate();
  const runs = useQuery({ queryKey: ["pipeline-runs-list"], queryFn: () => api<{ pipeline_runs: PipelineRun[] }>("/pipeline-runs") });
  const cmp = useQuery({ queryKey: ["compare", a, b], enabled: !!a && !!b, queryFn: () => api<CompareResult>("/compare", { a, b }) });
  const ids = runs.data?.pipeline_runs.map((p) => p.id) ?? [];
  const pick = (k: "a" | "b", v: string) => navigate({ to: "/compare", search: { a, b, [k]: v || undefined }, replace: true });
  return (
    <div className="flex max-w-[1300px] flex-col gap-4">
      <PageHeader title="Compare" subtitle="What changed between two pipeline runs. Rules are matched by their source location, not by BR id (BR ids are renumbered on every rules run)." />
      <div className="flex flex-wrap items-center gap-3">
        {(["a", "b"] as const).map((k) => (
          <label key={k} className="flex items-center gap-2">{k === "a" ? "Baseline" : "Compared"}
            <select value={(k === "a" ? a : b) ?? ""} onChange={(e) => pick(k, e.target.value)} className="mono rounded border border-line bg-surface px-2 py-1 text-[12.5px]">
              <option value="">choose a pipeline run</option>{ids.map((id) => <option key={id}>{id}</option>)}
            </select></label>
        ))}
      </div>
      {ids.length < 2 && runs.data && <Panel><Empty title="Only one pipeline run exists">Comparison needs two. Re-run 07_synthesis after a change to create another.</Empty></Panel>}
      {cmp.isLoading && <Loading />}
      {cmp.error && <ErrorBox error={cmp.error} />}
      {cmp.data && <CompareBody c={cmp.data} />}
    </div>
  );
}

function CompareBody({ c }: { c: CompareResult }) {
  const r = c.rules;
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {c.identical ? <Pill tone="tone-ok"><Icon name="check" />Every compared file is byte-identical</Pill> : <Pill tone="tone-stale">Outputs differ</Pill>}
        <Pill>Rules {r.count_a} → {r.count_b}</Pill><Pill>Open matters {c.gaps.count_a} → {c.gaps.count_b}</Pill>
        {r.renumbered.length > 0 && <Pill tone="tone-warn" title="Annotations keyed by BR id would now attach to a different rule"><Icon name="warn" />{r.renumbered.length} rule(s) renumbered</Pill>}
      </div>
      <Panel title="By stage">
        <DataTable rows={c.stages} rowKey={(s) => s.stage} columns={[
          { key: "stage", header: "Stage", render: (s) => <span><span className="mono text-fg-3">{stageNo(s.stage)}</span> {stageName(s.stage)}</span> },
          { key: "runs", header: "Runs", render: (s) => s.same_run ? <span className="text-fg-3">same run</span> : <span className="mono text-[12px]">{s.a ?? "—"} → {s.b ?? "—"}</span> },
          { key: "files", header: "Files", render: (s) => s.files_changed.length + s.files_added.length + s.files_removed.length === 0
            ? <span className="text-fg-3">{s.files_compared ? `${s.files_compared} identical` : "—"}</span>
            : <span>{s.files_changed.length} changed · {s.files_added.length} added · {s.files_removed.length} removed</span> },
          { key: "metrics", header: "Metric changes", render: (s) => s.metric_deltas.length ? s.metric_deltas.slice(0, 4).map((d) => <div key={d.metric} className="mono text-[12px]">{d.metric}: {String(d.a)} → {String(d.b)}</div>) : <span className="text-fg-3">none</span> },
        ]} />
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={`Rules added (${r.added.length}) / removed (${r.removed.length})`}>
          {r.added.length + r.removed.length === 0 ? <Empty title="No rules added or removed" /> : (
            <ul className="m-0 p-4 pl-8">
              {r.added.map((x) => <li key={"a" + x.id}><span className="text-[color:var(--ok)]">+</span> <span className="mono">{x.id}</span> {x.name}</li>)}
              {r.removed.map((x) => <li key={"r" + x.id}><span className="text-[color:var(--fail)]">−</span> <span className="mono">{x.id}</span> {x.name}</li>)}
            </ul>)}
        </Panel>
        <Panel title={`Rules changed (${r.changed.length})`}>
          {r.changed.length === 0 ? <Empty title="No rule changed meaning" /> : (
            <ul className="m-0 p-4 pl-8">{r.changed.map((x, i) => <li key={i}><span className="mono">{x.id_a}→{x.id_b}</span>: {Object.entries(x.changes).map(([k, v]) => `${k} ${String(v.a)} → ${String(v.b)}`).join("; ")}</li>)}</ul>)}
        </Panel>
      </div>
      {r.renumbered.length > 0 && (
        <Panel title="Renumbered rules (same rule, new id)">
          <ul className="m-0 p-4 pl-8">{r.renumbered.map((x, i) => <li key={i}><span className="mono">{x.id_a} → {x.id_b}</span> {x.name}</li>)}</ul>
        </Panel>
      )}
      <Panel title="Open matters">
        {c.gaps.opened.length + c.gaps.closed.length === 0 ? <Empty title="The same open matters in both runs" /> : (
          <ul className="m-0 p-4 pl-8">
            {c.gaps.opened.map((g, i) => <li key={"o" + i}><SeverityBadge sev={g.severity} /> opened: {g.title}</li>)}
            {c.gaps.closed.map((g, i) => <li key={"c" + i}><SeverityBadge sev={g.severity} /> closed: {g.title}</li>)}
          </ul>)}
      </Panel>
    </>
  );
}

/* ----------------------------------------------------------------- health -- */
const H_TONE: Record<HealthCheck["status"], [string, "check" | "warn" | "x" | "info" | "dash", string]> = {
  pass: ["tone-ok", "check", "Pass"], warn: ["tone-warn", "warn", "Warning"], fail: ["tone-fail", "x", "Fail"],
  info: ["tone-muted", "info", "Info"], not_applicable: ["tone-muted", "dash", "n/a"],
};
export function HealthPage() {
  const q = useHealth();
  if (q.isLoading) return <Loading what="Running self-checks" />;
  if (q.error) return <ErrorBox error={q.error} />;
  return (
    <div className="max-w-[1200px]">
      <PageHeader title="Health" subtitle="Read-only self-checks of the environment, the corpus, the output tree and the harness definitions.">
        <button type="button" onClick={() => q.refetch()} className="rounded border border-line px-2.5 py-1 text-[12.5px] hover:bg-surface-2">Re-run checks</button>
      </PageHeader>
      <div className="flex flex-col gap-3">
        {q.data!.checks.map((c) => {
          const [tone, icon, label] = H_TONE[c.status];
          return (
            <Panel key={c.id}>
              <div className="flex flex-wrap items-start gap-3 px-4 py-3">
                <span className="mono w-8 text-fg-3">{c.id}</span>
                <span className={`badge ${tone}`}><Icon name={icon} />{label}</span>
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{c.name}</div>
                  <div className="text-fg-2">{c.summary}</div>
                  {c.details.length > 0 && <ul className="mt-1.5 mb-0 pl-5 text-[12.5px] text-fg-2">{c.details.map((d) => <li key={d}>{d}</li>)}</ul>}
                  {c.remediation && <div className="mt-1.5 text-[12.5px]"><span className="text-fg-3">Fix: </span>{c.remediation}</div>}
                  {c.evidence.length > 0 && <div className="mt-1 text-[12px] text-fg-3">evidence: {c.evidence.map((e) => <span key={e.label} className="mono mr-2">{e.path}</span>)}</div>}
                </div>
              </div>
            </Panel>
          );
        })}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- stages -- */
interface StageDef { key: string; n: number; title: string; purpose: string; script: string; agent: string; requires: string[]; optional: string[]; downstream: string[]; latest_run_version: string | null; freshness: FreshnessInfo }
export function StagesPage() {
  const q = useQuery({ queryKey: ["stages"], queryFn: () => api<{ stages: StageDef[] }>("/stages") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  return (
    <div className="max-w-[1300px]">
      <PageHeader title="Stages" subtitle="The eight stage definitions as the console understands them — checked against each script's own flags by health check H8. There is no orchestrator: an operator or a Claude Code subagent runs each script." />
      <Panel>
        <DataTable rows={q.data!.stages} rowKey={(s) => s.key} columns={[
          { key: "n", header: "#", width: "40px", render: (s) => <span className="mono text-fg-3">{stageNo(s.key)}</span> },
          { key: "title", header: "Stage", render: (s) => <div className="py-1"><div className="font-medium">{s.title}</div><div className="text-[12px] text-fg-3">{s.purpose}</div></div> },
          { key: "req", header: "Requires", render: (s) => s.requires.length ? s.requires.map((r) => <div key={r} className="mono text-[12px]">{r}</div>) : <span className="text-fg-3">source directory</span> },
          { key: "opt", header: "Optional", render: (s) => s.optional.length ? s.optional.map((r) => <div key={r} className="mono text-[12px]">{r}</div>) : <span className="text-fg-3">—</span> },
          { key: "impl", header: "Implemented by", render: (s) => <div className="text-[12px]"><div className="mono">.claude/scripts/{s.script}</div><div className="mono text-fg-3">.claude/agents/{s.agent}</div></div> },
          { key: "latest", header: "Latest", render: (s) => s.latest_run_version ? <div><Link to={runPath(s.key, s.latest_run_version)} className="mono text-[12px]">{s.latest_run_version}</Link><div className="mt-0.5"><FreshnessBadge value={s.freshness?.value} /></div></div> : <span className="text-fg-3">never run</span> },
        ]} />
      </Panel>
    </div>
  );
}
