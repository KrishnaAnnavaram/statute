import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api, runPath, type GridStage, type PipelineDetail, type PipelineRun } from "../api";
import { fmtAgo, fmtDuration, fmtTime, stageName, stageNo } from "../lib/format";
import { DataTable, Empty, ErrorBox, Icon, KeyValues, Loading, PageHeader, Panel, Pill, StateBadge } from "../components/ui";
import { LineageGraph, Timeline } from "../components/graphs";

export function RunsPage() {
  const q = useQuery({ queryKey: ["pipeline-runs"], queryFn: () => api<{ pipeline_runs: PipelineRun[]; grid: GridStage[] }>("/pipeline-runs"), refetchInterval: 15000 });
  const [hover, setHover] = useState<{ stage: string; rv: string } | null>(null);
  const [pick, setPick] = useState<string[]>([]);
  const consumed = useMemo(() => {
    if (!hover || !q.data) return new Set<string>();
    const row = q.data.grid.find((g) => g.stage === hover.stage)?.runs.find((r) => r.run_version === hover.rv);
    return new Set((row?.upstream ?? []).map((u) => `${u.stage}/${u.run_version}`));
  }, [hover, q.data]);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { pipeline_runs: prs, grid } = q.data!;
  return (
    <div className="flex max-w-[1500px] flex-col gap-4">
      <PageHeader title="Runs" subtitle="A pipeline run is derived: a 07_synthesis run plus every upstream run it was built from.">
        {pick.length === 2 && <Link to="/compare" search={{ a: pick[1], b: pick[0] }} className="rounded border border-line px-2.5 py-1">Compare selected →</Link>}
      </PageHeader>
      <Panel title="Pipeline runs">
        <DataTable rows={prs} rowKey={(p) => p.id} caption="Pipeline runs" empty="No pipeline run yet — 07_synthesis has not succeeded"
          columns={[
            { key: "sel", header: <span className="sr-only">Select for comparison</span>, width: "32px", render: (p) => (
              <input type="checkbox" aria-label={`Select ${p.id} for comparison`} checked={pick.includes(p.id)}
                onChange={(e) => setPick((xs) => e.target.checked ? [p.id, ...xs].slice(0, 2) : xs.filter((x) => x !== p.id))} />) },
            { key: "id", header: "Pipeline run", render: (p) => <Link to="/runs/$pid" params={{ pid: p.id }} className="mono">{p.id}</Link>, sort: (p) => p.anchor },
            { key: "cur", header: "Status", render: (p) => (
              <span className="flex flex-wrap gap-1">
                {p.is_current && !p.superseded_by.length && <Pill tone="tone-ok"><Icon name="check" />Current</Pill>}
                {p.is_current && p.superseded_by.length > 0 && <Pill tone="tone-stale"><Icon name="clock" />Latest BRD</Pill>}
                {p.consistency !== "consistent" && <Pill tone="tone-fail"><Icon name="x" />{p.consistency}</Pill>}
                {p.superseded_by.length > 0 && <Pill tone="tone-stale"><Icon name="clock" />superseded</Pill>}
              </span>) },
            { key: "req", header: "Requirements", num: true, render: (p) => <span className="mono">{p.counts.requirements ?? "—"}</span> },
            { key: "om", header: "Open matters (crit/high/med/low)", render: (p) => <span className="mono">{p.open_matters.critical}/{p.open_matters.high}/{p.open_matters.medium}/{p.open_matters.low}</span> },
            { key: "span", header: "Built in", num: true, render: (p) => <span className="mono">{fmtDuration(p.span_ms)}</span>, sort: (p) => p.span_ms ?? 0 },
            { key: "when", header: "Finished", render: (p) => <span title={p.finished_at ?? ""}>{fmtAgo(p.finished_at)}</span>, sort: (p) => p.finished_at ?? "" },
          ]} initialSort={{ key: "id", dir: -1 }} />
        <div className="border-t border-line px-4 py-1.5 text-[12px] text-fg-3">Select two to compare them.</div>
      </Panel>
      <Panel title="Stage runs" actions={<span className="text-[12px] text-fg-3">newest left · hover a run to highlight the runs it consumed</span>}>
        <div className="overflow-x-auto p-3">
          <table className="border-separate border-spacing-1 text-[12px]" aria-label="Stage run history">
            <tbody>
              {grid.map((g) => (
                <tr key={g.stage}>
                  <th scope="row" className="whitespace-nowrap pr-3 text-left font-medium"><span className="mono text-fg-3">{stageNo(g.stage)}</span> {stageName(g.stage)}</th>
                  {g.runs.length === 0 && <td className="text-fg-3">never run</td>}
                  {g.runs.map((r) => {
                    const key = `${g.stage}/${r.run_version}`;
                    const lit = consumed.has(key) || (hover && hover.stage === g.stage && hover.rv === r.run_version);
                    return (
                      <td key={r.id}>
                        <Link to={runPath(g.stage, r.id)} onMouseEnter={() => r.run_version && setHover({ stage: g.stage, rv: r.run_version })} onMouseLeave={() => setHover(null)}
                          onFocus={() => r.run_version && setHover({ stage: g.stage, rv: r.run_version })} onBlur={() => setHover(null)}
                          title={`${r.attempt ? "attempt" : r.run_version} · ${r.state}${r.published ? " · published" : ""} · ${fmtDuration(r.duration_ms)}`}
                          className={`block rounded no-underline hover:no-underline ${lit ? "ring-2 ring-[color:var(--accent)]" : ""} ${hover && !lit ? "opacity-40" : ""}`}>
                          <StateBadge state={r.state} basis={r.state_basis} />
                          <div className="mono mt-0.5 text-center text-[10.5px] text-fg-3">{r.attempt ? "attempt" : r.run_version?.slice(5, 16).replace("T", " ")}{r.published ? " ●" : ""}</div>
                        </Link>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-1 text-[12px] text-fg-3">● published (named by latest.json)</div>
        </div>
      </Panel>
    </div>
  );
}

export function PipelineRunPage({ pid }: { pid: string }) {
  const q = useQuery({ queryKey: ["pipeline-run", pid], queryFn: () => api<PipelineDetail>(`/pipeline-runs/${encodeURIComponent(pid)}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const p = q.data!;
  return (
    <div className="flex max-w-[1500px] flex-col gap-4">
      <PageHeader eyebrow={<><Link to="/runs">Runs</Link> › pipeline run</>} title={<span className="mono">{p.id}</span>}
        subtitle={`${p.counts.requirements ?? "?"} requirements · ${p.open_matters.high} high-severity open matters · built in ${fmtDuration(p.span_ms)}`}>
        {p.is_current && (p.superseded_by.length ? <Pill tone="tone-stale" title="This is the latest BRD, but newer runs of its inputs exist"><Icon name="clock" />Latest BRD · inputs superseded</Pill> : <Pill tone="tone-ok"><Icon name="check" />Current</Pill>)}
        {p.consistency === "consistent" ? <Pill tone="tone-ok"><Icon name="check" />Consistent</Pill> : <Pill tone="tone-fail"><Icon name="x" />{p.consistency}</Pill>}
        {p.superseded_by.length > 0 && <Pill tone="tone-stale"><Icon name="clock" />newer run of {p.superseded_by.join(", ")}</Pill>}
      </PageHeader>
      {p.inconsistencies.length > 0 && (
        <div role="alert" className="badge tone-fail !flex !w-full !flex-col !items-start !whitespace-normal !px-4 !py-2.5 !text-[13px]">
          {p.inconsistencies.map((i) => (
            <div key={i.stage}><b>{i.stage}</b>: {i.versions.map((v) => `${v.run_version} (used by ${v.consumed_by.join(", ")})`).join(" vs ")}</div>
          ))}
        </div>
      )}
      <Panel title="Lineage"><div className="p-4"><LineageGraph lineage={p.lineage} /></div></Panel>
      <Panel title="Timeline"><div className="p-4"><Timeline t={p.timeline} /></div></Panel>
      <Panel title="Member stage runs">
        <DataTable rows={p.member_runs} rowKey={(m) => m.stage} caption="Stage runs in this pipeline run" columns={[
          { key: "stage", header: "Stage", render: (m) => <span><span className="mono text-fg-3">{stageNo(m.stage)}</span> {m.title}</span> },
          { key: "run", header: "Run", render: (m) => m.run ? <Link to={runPath(m.stage, m.run.id)} className="mono">{m.run.run_version}</Link> : <span className="text-fg-3">not part of this run</span> },
          { key: "state", header: "State", render: (m) => m.run ? <StateBadge state={m.run.state} basis={m.run.state_basis} /> : null },
          { key: "pub", header: "Published", render: (m) => m.run ? (m.is_published ? "yes" : <span className="text-fg-2">no — latest is <span className="mono">{m.latest_run_version}</span></span>) : "—" },
          { key: "dur", header: "Duration", num: true, render: (m) => <span className="mono">{fmtDuration(m.run?.duration_ms)}{m.run?.timing_basis === "partial" ? "*" : ""}</span> },
          { key: "note", header: "Provenance", render: (m) => m.inferred ? <span className="text-[color:var(--unknown)]">matched by time (inputs unrecorded)</span> : m.run?.provenance_gaps.length ? <span className="text-[color:var(--unknown)]">does not record {m.run.provenance_gaps.join(", ")}</span> : <span className="text-fg-3">recorded</span> },
        ]} />
      </Panel>
      <Panel title="Deliverables">
        <div className="p-4"><KeyValues cols={1} items={p.deliverables.map((d) => [d.label, <Link key={d.path} to={runPath(d.stage, d.run_version)} search={{ tab: "outputs", artifact: d.artifact_id }} className="mono">{d.path}</Link>])} /></div>
        {!p.deliverables.length && <Empty title="No deliverables found on disk" />}
      </Panel>
      <div className="text-[12px] text-fg-3">Started {fmtTime(p.started_at)} · finished {fmtTime(p.finished_at)}</div>
    </div>
  );
}
