import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { api, runPath, type Artifact, type ArtifactContent, type ConsoleEvent, type Items, type StageFinding, type StageRunDetail } from "../api";
import { fmtBytes, fmtDuration, fmtTime, stageName, stageNo } from "../lib/format";
import { CopyButton, DataTable, Drawer, Empty, ErrorBox, FreshnessBadge, Icon, KeyValues, Loading, Mono, PageHeader, Panel, Pill, SeverityBadge, StateBadge, Tabs, Code } from "../components/ui";
import { ArtifactBody } from "../components/viewers";
import { EventTable } from "./EventsPage";

type Tab = "summary" | "inputs" | "outputs" | "items" | "findings" | "events" | "raw";

export function StageRunPage({ stage, rid, tab, artifact }: { stage: string; rid: string; tab: Tab; artifact?: string }) {
  const navigate = useNavigate();
  const base = `/stages/${stage}/runs/${encodeURIComponent(rid)}`;
  const q = useQuery({ queryKey: ["run", stage, rid], queryFn: () => api<StageRunDetail>(base),
    refetchInterval: (x) => (x.state.data?.state === "running" ? 2000 : false) });
  const setTab = (t: Tab) => navigate({ to: runPath(stage, rid), search: { tab: t }, replace: true });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const r = q.data!;
  const label = r.attempt ? `failed attempt ${rid.slice(8)}` : r.run_version!;
  return (
    <div className="max-w-[1400px]">
      <PageHeader
        eyebrow={<><Link to="/">Pipeline</Link> › {r.pipeline_runs[0] ? <><Link to="/runs/$pid" params={{ pid: r.pipeline_runs[0] }}>{r.pipeline_runs[0]}</Link> › </> : null}<span className="mono">{stageNo(stage)}</span> {stageName(stage)}</>}
        title={<span className="flex flex-wrap items-center gap-2"><span className="capitalize">{stageName(stage)}</span><span className="mono text-[15px] font-normal text-fg-2">{label}</span></span>}
        subtitle={r.summary_text[0]}>
        <StateBadge state={r.state} basis={r.state_basis} />
        {r.published ? <Pill tone="tone-ok" title="latest.json points at this run"><Icon name="check" />Published</Pill> : <Pill title="latest.json points elsewhere">Not published</Pill>}
        {r.freshness && <FreshnessBadge value={r.freshness.value} />}
        <span className="mono text-fg-2">{fmtDuration(r.duration_ms)}{r.timing_basis === "partial" ? " (partial)" : ""}</span>
      </PageHeader>

      {(r.state === "failed" || r.state === "crashed") && (
        <div role="alert" className="badge tone-fail mb-4 !flex !w-full !flex-col !items-start !whitespace-normal !px-4 !py-3 !text-[13px]">
          <div className="flex items-center gap-1.5 font-semibold"><Icon name="x" />{r.error ? `${r.error.class}${r.error.where ? ` at ${r.error.where}` : ""}` : "No outcome recorded"}</div>
          <div className="text-fg">{r.error?.message ?? r.state_reason}</div>
          {r.error?.last_item && <div className="text-fg-2">While processing {r.error.last_item.kind} <span className="mono">{r.error.last_item.id}</span></div>}
          <div className="text-fg-2">Downstream stages still read the published run. Fix the cause, then: <span className="mono">{r.rerun_command}</span></div>
        </div>
      )}
      {r.state === "running" && (
        <div role="status" className="badge tone-run mb-4 !flex !w-full !whitespace-normal !px-4 !py-2.5 !text-[13px]">
          <Icon name="ring" />Running for {fmtDuration(r.duration_ms)}
          {r.current_item && <> · processing {r.current_item.kind} <span className="mono">{r.current_item.id}</span></>}
          {r.progress && <> · {r.progress.done}/{r.progress.total} {r.progress.unit}</>}
        </div>
      )}

      <Panel>
        <Tabs<Tab> label="Stage run sections" value={tab} onChange={setTab} tabs={[
          { id: "summary", label: "Summary" }, { id: "inputs", label: "Inputs", count: r.upstream.length },
          { id: "outputs", label: "Outputs" }, { id: "items", label: "Items" }, { id: "findings", label: "Findings" },
          { id: "events", label: "Events", count: r.events ?? undefined }, { id: "raw", label: "Raw" }]} />
        <div className="p-4">
          {tab === "summary" && <Summary r={r} />}
          {tab === "inputs" && <Inputs r={r} />}
          {tab === "outputs" && <Outputs stage={stage} rid={rid} open={artifact} />}
          {tab === "items" && <ItemsTab stage={stage} rid={rid} />}
          {tab === "findings" && <FindingsTab stage={stage} rid={rid} />}
          {tab === "events" && <EventsTab stage={stage} rid={rid} running={r.state === "running"} instrumented={r.instrumented} />}
          {tab === "raw" && <Raw r={r} />}
        </div>
      </Panel>
    </div>
  );
}

function Summary({ r }: { r: StageRunDetail }) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div>
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">{r.summary_text.map((t) => <li key={t}>{t}</li>)}</ul>
        {r.degraded.length > 0 && (
          <div className="mt-4">
            <div className="mb-1 font-medium">Ran with incomplete input</div>
            <ul className="m-0 pl-5 text-fg-2">{r.degraded.map((d) => <li key={d.input}><span className="mono">{d.input}</span> — {d.reason}</li>)}</ul>
          </div>
        )}
        {r.freshness && r.freshness.causes.length > 0 && (
          <div className="mt-4">
            <div className="mb-1 font-medium">Why it is marked {r.freshness.value.replace("_", " ")}</div>
            <ul className="m-0 pl-5 text-fg-2">{r.freshness.causes.map((c) => <li key={c.text}>{c.text}</li>)}</ul>
          </div>
        )}
      </div>
      <KeyValues cols={1} items={[
        ["Started", fmtTime(r.started_at)], ["Finished", fmtTime(r.finished_at)],
        ["Timing", r.timing_basis === "recorded" ? "recorded by the run" : r.timing_basis === "partial" ? "partial (run_version → generated_at)" : "inferred"],
        ["State evidence", r.evidence.length ? r.evidence.map((e) => <div key={e.label} className="mono">{e.path}</div>) : r.state_reason],
        ["Directory", <span className="mono">{r.dir}</span>],
        ["Code version", r.code_version ? <span className="mono">{r.code_version}</span> : r.instrumented ? "—" : "not recorded (pre-instrumentation run)"],
        ["Trace context", r.traceparent ? <Mono max={40}>{r.traceparent}</Mono> : "none (not launched under an OTel trace)"],
        ["Consumed by", r.consumers.length ? r.consumers.map((c) => <div key={c.stage + c.run_version}><Link to={runPath(c.stage, c.run_version)}>{c.stage}</Link> <span className="mono text-fg-3">{c.run_version}</span>{c.published ? "" : " (not published)"}</div>) : "no downstream run"],
        ["Re-run", <span className="flex items-center gap-2"><span className="mono">{r.rerun_command}</span><CopyButton text={r.rerun_command} /></span>],
      ]} />
    </div>
  );
}

function Inputs({ r }: { r: StageRunDetail }) {
  if (!r.upstream.length && !r.provenance_gaps.length) return <Empty title="This stage reads the source directory, not another stage" />;
  const rows = [...r.upstream.map((u) => ({ ...u, gap: false })),
    ...r.provenance_gaps.map((g) => ({ stage: g, run_version: null, resolved: "unknown" as const, present: false, optional: false, source: "run_meta" as const, gap: true }))];
  return (
    <DataTable rows={rows} rowKey={(x) => x.stage} caption="Upstream inputs" columns={[
      { key: "stage", header: "Input", render: (u) => <span><span className="mono text-fg-3">{stageNo(u.stage)}</span> {stageName(u.stage)}</span> },
      { key: "rv", header: "Run consumed", render: (u) => u.gap ? <span className="text-[color:var(--unknown)]">not recorded by this run</span> : u.run_version ? <Link className="mono" to={runPath(u.stage, u.run_version)}>{u.run_version}</Link> : <span className="text-fg-3">absent{u.optional ? " (optional)" : ""}</span> },
      { key: "res", header: "Resolved as", render: (u) => u.gap ? "—" : u.resolved },
      { key: "latest", header: "Published now", render: (u) => {
        const cur = r.upstream_latest[u.stage];
        if (!cur) return <span className="text-fg-3">—</span>;
        const same = cur === u.run_version;
        return same ? <span className="text-fg-3">same run</span> : <span><Icon name="clock" /> <span className="mono">{cur}</span></span>;
      } },
    ]} />
  );
}

function Outputs({ stage, rid, open }: { stage: string; rid: string; open?: string }) {
  const navigate = useNavigate();
  const base = `/stages/${stage}/runs/${encodeURIComponent(rid)}`;
  const list = useQuery({ queryKey: ["artifacts", stage, rid], queryFn: () => api<{ artifacts: Artifact[] }>(`${base}/artifacts`) });
  const content = useQuery({ queryKey: ["artifact", stage, rid, open], enabled: !!open,
    queryFn: () => api<ArtifactContent>(`${base}/artifacts/${open}`) });
  const setOpen = (id?: string) => navigate({ to: runPath(stage, rid), search: { tab: "outputs", artifact: id }, replace: true });
  if (list.isLoading) return <Loading />;
  if (list.error) return <ErrorBox error={list.error} />;
  const arts = list.data!.artifacts;
  return (
    <>
      <DataTable rows={arts} rowKey={(a) => a.id} caption="Files in this run directory" onRowClick={(a) => setOpen(a.id)}
        initialSort={{ key: "kind", dir: 1 }} columns={[
          { key: "path", header: "File", render: (a) => <button type="button" className="mono text-accent hover:underline" onClick={(e) => { e.stopPropagation(); setOpen(a.id); }}>{a.path}</button>, sort: (a) => a.path },
          { key: "kind", header: "Kind", render: (a) => a.kind, sort: (a) => ["artifact", "metadata", "witness", "per-item"].indexOf(a.kind) * 1e6 + a.path.length },
          { key: "bytes", header: "Size", num: true, render: (a) => <span className="mono">{fmtBytes(a.bytes)}</span>, sort: (a) => a.bytes },
        ]} />
      <Drawer wide open={!!open} onClose={() => setOpen(undefined)} title={<span className="mono">{content.data?.path ?? "Loading…"}</span>}>
        {content.isLoading && <Loading />}
        {content.error && <ErrorBox error={content.error} />}
        {content.data && (
          <>
            <div className="mb-3 flex flex-wrap gap-x-4 text-[12px] text-fg-3">
              <span>{fmtBytes(content.data.bytes)}</span>
              {content.data.sha256 && <span className="mono">sha256 {content.data.sha256.slice(0, 16)}…</span>}
              <span>read-only preview · local paths redacted</span>
            </div>
            <ArtifactBody path={content.data.path} text={content.data.text} truncated={content.data.truncated} />
          </>
        )}
      </Drawer>
    </>
  );
}

function ItemsTab({ stage, rid }: { stage: string; rid: string }) {
  const q = useQuery({ queryKey: ["items", stage, rid], queryFn: () => api<Items>(`/stages/${stage}/runs/${encodeURIComponent(rid)}/items`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { columns, rows } = q.data!;
  const link = (row: Items["rows"][number], v: unknown) => {
    const kinds: Record<string, string> = { object: "object", rule: "rule", table: "table", file: "file" };
    const k = kinds[row.kind];
    return k ? <Link to="/evidence/$kind/$id" params={{ kind: k, id: row.id }} className="mono">{String(v)}</Link> : <span className="mono">{String(v)}</span>;
  };
  return (
    <DataTable<Items["rows"][number]> rows={rows} rowKey={(x) => x.id} caption="Work items" empty="This run recorded no items"
      columns={columns.map((c, i) => ({
        key: c, header: c, num: typeof rows[0]?.[c] === "number" || c === "duration",
        sort: (x) => { const v = x[c]; return typeof v === "number" ? v : String(v ?? ""); },
        render: (x) => {
          const v = x[c];
          if (i === 0) return link(x, v);
          if (c === "duration") return <span className="mono">{fmtDuration(v as number | null)}</span>;
          if (c === "parse status" && v !== "success") return <Pill tone="tone-fail">{String(v)}</Pill>;
          if (typeof v === "boolean") return v ? "yes" : "no";
          return v === null || v === undefined ? <span className="text-fg-3">—</span> : String(v);
        },
      }))} />
  );
}

function FindingsTab({ stage, rid }: { stage: string; rid: string }) {
  const q = useQuery({ queryKey: ["run-findings", stage, rid], queryFn: () => api<{ findings: StageFinding[] }>(`/stages/${stage}/runs/${encodeURIComponent(rid)}/findings`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  return (
    <DataTable rows={q.data!.findings} rowKey={(f) => f.kind + f.title} caption="Findings recorded by this run" empty="This run recorded no issues, warnings or gaps"
      columns={[
        { key: "sev", header: "Severity", render: (f) => <SeverityBadge sev={f.severity} />, sort: (f) => ["critical", "high", "medium", "low", "info"].indexOf(f.severity), width: "110px" },
        { key: "kind", header: "Kind", render: (f) => <span className="mono text-[12px]">{f.kind}</span>, sort: (f) => f.kind },
        { key: "title", header: "Finding", render: (f) => <div><div>{f.title}</div>{f.detail && <div className="text-[12px] text-fg-3">{f.detail}</div>}</div> },
        { key: "loc", header: "Where", render: (f) => {
          const l = f.location as Record<string, string | number | null> | null;
          if (!l) return "—";
          if (l.rule_id) return <Link to="/evidence/$kind/$id" params={{ kind: "rule", id: String(l.rule_id) }}>{String(l.rule_id)}{l.line ? ` · line ${l.line}` : ""}</Link>;
          if (l.gap_id) return <Link to="/evidence/$kind/$id" params={{ kind: "gap", id: String(l.gap_id) }}>{String(l.gap_id)}</Link>;
          if (l.object_id) return <Link to="/evidence/$kind/$id" params={{ kind: "object", id: String(l.object_id) }} className="mono">{String(l.object_id)}{l.line ? `:${l.line}` : ""}</Link>;
          return <span className="mono">{String(l.file ?? "")}{l.line ? `:${l.line}` : ""}</span>;
        } },
      ]} />
  );
}

function EventsTab({ stage, rid, running, instrumented }: { stage: string; rid: string; running: boolean; instrumented: boolean }) {
  const q = useQuery({ queryKey: ["run-events", stage, rid], refetchInterval: running ? 1500 : false,
    queryFn: () => api<{ events: ConsoleEvent[]; available: boolean; error: string | null }>(`/stages/${stage}/runs/${encodeURIComponent(rid)}/events`) });
  if (!instrumented) return <Empty title="No events recorded for this run">It was produced before run-lifecycle instrumentation (lib_runlog) existed. Re-running the stage records events.</Empty>;
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  return <>
    {q.data!.error && <div className="mb-2 text-[12px] text-fg-2">Note: {q.data!.error} in events.jsonl (a writer may have been mid-line).</div>}
    <EventTable events={q.data!.events} />
  </>;
}

function Raw({ r }: { r: StageRunDetail }) {
  return r.run_meta ? <Code text={JSON.stringify(r.run_meta, null, 2)} /> : <Empty title="No run_meta.json">The run did not finish, so it never wrote its metadata.</Empty>;
}
