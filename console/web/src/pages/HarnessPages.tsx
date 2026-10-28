import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api, runPath, type AgentRow, type ArtifactContent, type CatalogueEntry, type PipelineDetail, type TraceData } from "../api";
import { useStatus } from "../queries";
import { fmtBytes, fmtDuration, fmtTime, stageName, stageNo } from "../lib/format";
import { CopyButton, Drawer, Empty, ErrorBox, FreshnessBadge, Loading, Mono, PageHeader, StateBadge } from "../components/ui";
import { ArtifactBody } from "../components/viewers";
import { Timeline } from "../components/graphs";

/* ================================================================ Agents == */
export function AgentsPage() {
  const q = useQuery({ queryKey: ["agents"], queryFn: () => api<{ agents: AgentRow[] }>("/agents"), refetchInterval: 4000 });
  if (q.isLoading) return <Loading what="Reading agent specifications" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const rows = q.data!.agents;
  return (
    <div>
      <PageHeader title="Agents" subtitle="Eight Claude Code subagents, each a thin wrapper that runs one deterministic Python stage script, validates its output and reports. No language model writes any content." />
      <div className="panel overflow-x-auto">
        <table className="dt">
          <thead><tr><th>#</th><th>Agent</th><th>Type</th><th>Backing script</th><th>Output artifact</th><th>Status</th><th>Freshness</th><th className="num">Size</th><th className="num">Duration</th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.stage}>
                <td className="font-bold" style={{ color: "var(--color-accent-text)" }}>{a.n}</td>
                <td className="max-w-[460px]">
                  <div className="font-semibold">{a.title} <span className="mono ml-1 text-[11px] font-normal text-fg-3">{a.agent}</span></div>
                  <div className="mt-0.5 line-clamp-3 max-w-[560px] text-[11px] leading-snug text-fg-3" title={a.description}>{a.description}</div>
                  <div className="mt-1 text-[11px] text-fg-3">
                    needs {a.requires.length ? a.requires.join(", ") : "the source directory"}{a.optional.length ? ` · optional ${a.optional.join(", ")}` : ""}{a.tools ? ` · tools ${a.tools}` : ""}
                  </div>
                </td>
                <td><span className="badge tone-gold" title="No language model in the generation path (ADR-001)"><span className="dot" />{a.type}</span></td>
                <td className="mono text-[11px] text-fg-3">{a.script}</td>
                <td className="mono text-[11px]">{a.artifact}</td>
                <td>{a.run_version ? <Link to={runPath(a.stage, a.run_version)}><StateBadge state={a.state} /></Link> : <StateBadge state={null} />}</td>
                <td><FreshnessBadge value={a.freshness} /></td>
                <td className="num whitespace-nowrap text-fg-3">{a.artifact_bytes ? fmtBytes(a.artifact_bytes) : "—"}</td>
                <td className="num whitespace-nowrap text-fg-3">{fmtDuration(a.duration_ms)}{a.timing_basis === "partial" ? "*" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[12px] text-fg-3">* partial: runs made before run-lifecycle instrumentation record only part of their time. Specs live in <span className="mono">.claude/agents/</span>; health check H8 compares them with the scripts' real flags.</p>
    </div>
  );
}

/* ============================================================= Artifacts == */
const EXT_COLOR: Record<string, string> = { ".json": "var(--color-blue-text)", ".md": "var(--color-green)", ".mmd": "var(--color-accent-text)",
  ".csv": "var(--color-violet)", ".cypher": "var(--color-orange)", ".jsonl": "var(--color-blue-text)" };

export function ArtifactsPage() {
  const q = useQuery({ queryKey: ["catalogue"], queryFn: () => api<{ artifacts: CatalogueEntry[]; total_bytes: number }>("/catalogue"), refetchInterval: 10000 });
  const [stage, setStage] = useState("All");
  const [kind, setKind] = useState("All");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<CatalogueEntry | null>(null);
  const content = useQuery({ queryKey: ["artifact", open?.stage, open?.run_version, open?.id], enabled: !!open,
    queryFn: () => api<ArtifactContent>(`/stages/${open!.stage}/runs/${encodeURIComponent(open!.run_version)}/artifacts/${open!.id}`) });
  if (q.isLoading) return <Loading what="Listing artifacts" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const all = q.data!.artifacts;
  const stages = ["All", ...Array.from(new Set(all.map((a) => a.stage)))];
  const shown = all.filter((a) => (stage === "All" || a.stage === stage) && (kind === "All" || a.kind === kind)
    && (!search || a.path.toLowerCase().includes(search.toLowerCase())));
  const size = shown.reduce((s, a) => s + a.bytes, 0);
  return (
    <div>
      <PageHeader title="Artifacts" subtitle="Every file produced by the stage runs of the current pipeline run. Click a file to preview it (generated content is rendered safely).">
        <span className="text-[13px] text-fg-3">{shown.length} files · {fmtBytes(size)}</span>
      </PageHeader>
      <div className="mb-3.5 flex flex-wrap items-center gap-2">
        <input className="input w-[220px]" placeholder="Search by name…" aria-label="Search artifacts" value={search} onChange={(e) => setSearch(e.target.value)} />
        {stages.map((s) => <button key={s} type="button" className={`pill${stage === s ? " active" : ""}`} onClick={() => setStage(s)}>{s === "All" ? "All" : stageName(s)}</button>)}
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        {["All", "artifact", "per-item", "metadata", "witness"].map((k) => <button key={k} type="button" className={`pill${kind === k ? " active" : ""}`} onClick={() => setKind(k)}>{k}</button>)}
      </div>
      <div className="panel overflow-x-auto">
        <table className="dt">
          <thead><tr><th>File</th><th>Stage</th><th>Type</th><th>Kind</th><th className="num">Size</th><th>Path</th></tr></thead>
          <tbody>
            {shown.map((a) => (
              <tr key={a.stage + a.path} className="cursor-pointer" onClick={() => setOpen(a)}>
                <td><button type="button" className="text-left font-semibold text-fg hover:underline" onClick={(e) => { e.stopPropagation(); setOpen(a); }}>{a.name}</button></td>
                <td className="text-[11px] text-fg-3"><span className="mono">{stageNo(a.stage)}</span> {a.stage_title}</td>
                <td><span className="text-[11px] font-bold" style={{ color: EXT_COLOR[a.ext] ?? "var(--color-text-muted)" }}>{a.ext.replace(".", "").toUpperCase() || "—"}</span></td>
                <td className="text-[11px] text-fg-3">{a.kind}</td>
                <td className="num whitespace-nowrap text-fg-3">{fmtBytes(a.bytes)}</td>
                <td className="mono text-[11px] text-fg-3">{a.stage.slice(3)}/{a.run_version}/{a.path}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <Empty title="No artifacts match" />}
      </div>
      <Drawer wide open={!!open} onClose={() => setOpen(null)} title={<span className="mono">{open?.path}</span>}>
        {content.isLoading && <Loading />}
        {content.error && <ErrorBox error={content.error} />}
        {content.data && (
          <>
            <div className="mb-3 flex flex-wrap gap-x-4 text-[12px] text-fg-3">
              <span>{fmtBytes(content.data.bytes)}</span>
              {content.data.sha256 && <span className="mono">sha256 {content.data.sha256.slice(0, 16)}…</span>}
              <Link to={runPath(open!.stage, open!.run_version)} search={{ tab: "outputs" }}>open the {open!.stage} run →</Link>
            </div>
            <ArtifactBody path={content.data.path} text={content.data.text} truncated={content.data.truncated} />
          </>
        )}
      </Drawer>
    </div>
  );
}

/* ======================================================= Statement trace == */
const KIND: Record<string, { label: string; color: string }> = {
  control_flow: { label: "Control flow", color: "var(--color-blue-text)" },
  data_access: { label: "Data access", color: "var(--color-green)" },
  call: { label: "Call", color: "var(--color-violet)" },
  transaction: { label: "Transaction", color: "var(--color-orange)" },
  exception: { label: "Exception", color: "var(--color-red)" },
  assignment: { label: "Assignment", color: "var(--color-text-muted)" },
  other: { label: "Other", color: "var(--color-text-muted)" },
};

export function TracePage() {
  const [object, setObject] = useState("all");
  const [kind, setKind] = useState("all");
  const [search, setSearch] = useState("");
  const q = useQuery({ queryKey: ["trace", object], queryFn: () => api<TraceData>("/trace", { object: object === "all" ? undefined : object }) });
  if (q.isLoading) return <Loading what="Reading statement trees for every object" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const rows = d.entries.filter((e) => (kind === "all" || e.kind === kind)
    && (!search || `${e.operation} ${e.target} ${e.scope} ${e.object}`.toLowerCase().includes(search.toLowerCase())));
  return (
    <div>
      <PageHeader title="Statement trace" subtitle="A source-ordered record of every statement each PL/SQL object executes: control flow, data access, calls, transaction control and exception handling — from the parser's ANTLR statement trees." />
      <div className="callout mb-4">
        <div><strong className="text-fg">How to read it</strong></div>
        <div>CALL returns here after the routine finishes; RAISE leaves the current block for its exception handler; COMMIT and ROLLBACK end the transaction.</div>
        <div>Scope shows where a statement sits: <span className="mono">IF#n.THEN</span>, <span className="mono">LOOP#n</span>, <span className="mono">EXCEPTION › WHEN(OTHERS)</span>.</div>
      </div>
      <div className="mb-3 flex flex-wrap gap-5 text-[13px] text-fg-3">
        <span><strong className="text-fg">{d.counts.total}</strong> statements</span>
        <span><strong className="text-fg">{d.counts.data_access ?? 0}</strong> touch data</span>
        <span><strong className="text-fg">{d.counts.exception ?? 0}</strong> raise or handle exceptions</span>
        <span><strong className="text-fg">{d.counts.transaction ?? 0}</strong> control the transaction</span>
      </div>
      <div className="mb-3.5 flex flex-wrap items-center gap-2">
        <select className="input" aria-label="Object" value={object} onChange={(e) => setObject(e.target.value)}>
          <option value="all">All objects ({d.objects.length})</option>
          {d.objects.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <button type="button" className={`pill${kind === "all" ? " active" : ""}`} onClick={() => setKind("all")}>All {d.counts.total}</button>
        {Object.entries(KIND).filter(([k]) => d.counts[k]).map(([k, v]) => (
          <button key={k} type="button" className={`pill${kind === k ? " active" : ""}`} onClick={() => setKind(k)}>
            {kind !== k && <span className="mr-1.5 inline-block h-[7px] w-[7px] rounded-full" style={{ background: v.color }} aria-hidden />}
            {v.label} {d.counts[k]}
          </button>
        ))}
        <input className="input ml-auto w-[220px]" placeholder="Filter…" aria-label="Filter statements" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div className="panel max-h-[calc(100vh-200px)] overflow-auto">
        <table className="dt">
          <thead><tr><th>Step</th><th>Object</th><th>Line</th><th>Scope</th><th>Kind</th><th>Operation</th><th>Target</th><th>Flow</th></tr></thead>
          <tbody>
            {rows.map((e) => {
              const k = KIND[e.kind] ?? KIND.other;
              return (
                <tr key={e.statement_id}>
                  <td className="font-semibold text-fg-3">{e.step}</td>
                  <td className="mono text-[11px]"><Link to="/evidence/$kind/$id" params={{ kind: "object", id: e.object }}>{e.object.replace(/^[A-Z]+-\./, "")}</Link></td>
                  <td><Link to="/evidence/$kind/$id" params={{ kind: "statement", id: e.statement_id }} className="mono text-[11px]">{e.line}{e.end_line && e.end_line !== e.line ? `–${e.end_line}` : ""}</Link></td>
                  <td className="mono max-w-[260px] truncate text-[11px] text-fg-3" title={e.scope}>{e.scope}</td>
                  <td><span className="rounded px-2 py-0.5 text-[11px] font-semibold" style={{ color: k.color, background: `color-mix(in srgb, ${k.color} 15%, transparent)` }}>{k.label}</span></td>
                  <td className="mono text-[11px]" style={{ color: "var(--color-accent-text)" }}>{e.operation}</td>
                  <td className="mono text-[11px]">{e.target || <span className="text-fg-3">—</span>}</td>
                  <td className="text-[11px]" style={{ color: e.flow === "Leaves the block" ? "var(--color-orange)" : e.flow === "Ends transaction" ? "var(--color-amber)" : e.flow === "Returns here" ? "var(--color-green)" : "var(--color-text-muted)" }}>{e.flow}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <Empty title="No statements match" />}
      </div>
    </div>
  );
}

/* ============================================================== Timeline == */
export function TimelinePage() {
  const { data: s } = useStatus();
  const pid = s?.pipeline_run?.id;
  const q = useQuery({ queryKey: ["pipeline-run", pid], enabled: !!pid, queryFn: () => api<PipelineDetail>(`/pipeline-runs/${encodeURIComponent(pid!)}`) });
  if (!s) return <Loading />;
  if (!pid) return <Empty title="No pipeline run yet">The timeline appears once 07_synthesis has produced a BRD.</Empty>;
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const p = q.data!;
  const rows = [...p.timeline.rows];
  const gapBefore = (stage: string) => p.timeline.gaps.find((g) => g.before === stage);
  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
      <div>
        <PageHeader title="Timeline" subtitle={<>Pipeline events for <Link to="/runs/$pid" params={{ pid }} className="mono">{pid}</Link> as each stage completed.</>} />
        <div className="relative">
          <div className="absolute bottom-2 left-[9px] top-2 w-0.5 bg-line" aria-hidden />
          {rows.map((r) => {
            const gap = gapBefore(r.stage);
            const ok = r.state === "succeeded";
            return (
              <div key={r.stage}>
                {gap && gap.ms > 1000 && (
                  <div className="relative mb-4 ml-[30px] text-[11px] text-fg-3"><span className="hatched mr-2 inline-block h-2 w-8 align-middle" aria-hidden />{fmtDuration(gap.ms)} between invocations (agent or operator)</div>
                )}
                <div className="relative mb-7 flex gap-5">
                  <div className="relative z-[1] mt-0.5 h-5 w-5 shrink-0 rounded-full border-2" style={{ background: ok ? "var(--color-green)" : r.state === "running" ? "var(--color-blue)" : "var(--color-red)", borderColor: "var(--color-bg)" }} aria-hidden />
                  <div className="flex-1">
                    <div className="mono mb-1 text-[11px] text-fg-3">{fmtTime(r.end)}</div>
                    <div className="mb-0.5 text-[14px] font-bold">
                      Stage {Number(stageNo(r.stage))}: <span className="capitalize">{stageName(r.stage)}</span> {ok ? "completed" : r.state}
                      {r.duration_ms !== null && <span className="text-[13px] font-normal text-fg-3"> in {fmtDuration(r.duration_ms)}{r.basis !== "recorded" ? " (partial)" : ""}</span>}
                    </div>
                    <div className="text-[12px] text-fg-3">
                      Run <Link to={runPath(r.stage, r.run_version)} className="mono">{r.run_version}</Link>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div>
        <h3 className="mb-3 mt-0 text-[14px] font-bold">Waterfall</h3>
        <div className="card"><Timeline t={p.timeline} /></div>
      </div>
    </div>
  );
}

/* ================================================================= State == */
export function StatePage() {
  const { data: s } = useStatus();
  const json = useMemo(() => JSON.stringify(s ?? {}, null, 2), [s]);
  return (
    <div className="max-w-[1100px]">
      <PageHeader title="Raw state" subtitle="The live /api/v1/status snapshot backing this dashboard — derived on read from the output tree, never persisted.">
        <CopyButton text={json} label="Copy JSON" />
      </PageHeader>
      <pre tabIndex={0} className="mono m-0 overflow-auto rounded-lg border border-line bg-surface p-4 text-[11.5px] leading-[1.6]" style={{ maxHeight: "calc(100vh - 320px)" }}>{json}</pre>
      <div className="mt-2 text-[12px] text-fg-3"><Mono>{`${(json.length / 1024).toFixed(1)} KB`}</Mono></div>
    </div>
  );
}
