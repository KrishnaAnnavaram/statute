import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { api, runPath, type Category, type Finding } from "../api";
import { DataTable, Drawer, ErrorBox, KeyValues, Loading, PageHeader, Panel, SeverityBadge, Tabs } from "../components/ui";

export interface FindingsSearch { category?: Category; severity?: string; stage?: string; q?: string }
type Lens = "all" | Category;
const LENSES: { id: Lens; label: string }[] = [
  { id: "all", label: "All" }, { id: "run", label: "Run" }, { id: "lineage", label: "Lineage" },
  { id: "source", label: "Source" }, { id: "content", label: "Content" }, { id: "review", label: "Review" },
];
const SEV_ORDER = ["critical", "high", "medium", "low", "info"];

export function FindingsPage({ search }: { search: FindingsSearch }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState<Finding | null>(null);
  const q = useQuery({ queryKey: ["findings"], refetchInterval: 15000,
    queryFn: () => api<{ pipeline_run: string | null; by_category: Record<Category, number>; findings: Finding[] }>("/findings") });
  const set = (k: keyof FindingsSearch, v: string | undefined) => navigate({ to: "/findings", search: { ...search, [k]: v || undefined }, replace: true });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const all = q.data!.findings;
  const text = (search.q ?? "").toLowerCase();
  const rows = all.filter((f) => (!search.category || f.category === search.category)
    && (!search.severity || SEV_ORDER.indexOf(f.severity) <= SEV_ORDER.indexOf(search.severity))
    && (!search.stage || f.stage === search.stage)
    && (!text || `${f.title} ${f.detail ?? ""} ${f.kind}`.toLowerCase().includes(text)));
  const counts = Object.fromEntries(SEV_ORDER.map((s) => [s, rows.filter((f) => f.severity === s).length]));
  return (
    <div className="max-w-[1500px]">
      <PageHeader title="Findings" subtitle={<>Everything that needs a human, for pipeline run <span className="mono">{q.data!.pipeline_run ?? "—"}</span>. Content and review items come from STATUTE's own gaps register and issue lists.</>}>
        <span className="mono text-[12.5px] text-fg-2">{SEV_ORDER.filter((s) => counts[s]).map((s) => `${counts[s]} ${s}`).join(" · ") || "none"}</span>
      </PageHeader>
      <Panel>
        <Tabs<Lens> label="Finding categories" value={search.category ?? "all"} onChange={(l) => set("category", l === "all" ? undefined : l)}
          tabs={LENSES.map((l) => ({ ...l, count: l.id === "all" ? all.length : q.data!.by_category[l.id as Category] }))} />
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-[12.5px]">
          <label className="flex items-center gap-1.5">Minimum severity
            <select value={search.severity ?? ""} onChange={(e) => set("severity", e.target.value)} className="rounded border border-line bg-surface px-1 py-0.5">
              <option value="">any</option>{SEV_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
            </select></label>
          <label className="flex items-center gap-1.5">Stage
            <select value={search.stage ?? ""} onChange={(e) => set("stage", e.target.value)} className="rounded border border-line bg-surface px-1 py-0.5">
              <option value="">any</option>
              {["01_inventory", "02_parser", "03_data", "04_logic", "05_rules", "06_diagram", "07_synthesis", "08_graph"].map((s) => <option key={s}>{s}</option>)}
            </select></label>
          <input type="search" aria-label="Search findings" placeholder="Search findings" value={search.q ?? ""} onChange={(e) => set("q", e.target.value)}
            className="ml-auto w-72 rounded border border-line bg-surface px-2 py-1" />
        </div>
        <DataTable rows={rows} rowKey={(f) => f.id} caption="Findings" onRowClick={setOpen} empty="No findings match these filters"
          initialSort={{ key: "sev", dir: 1 }} columns={[
            { key: "sev", header: "Severity", width: "112px", render: (f) => <SeverityBadge sev={f.severity} />, sort: (f) => SEV_ORDER.indexOf(f.severity) * 10 + ["run", "lineage", "source", "content", "review"].indexOf(f.category) },
            { key: "cat", header: "Category", render: (f) => <span className="capitalize text-fg-2">{f.category}</span>, sort: (f) => f.category },
            { key: "title", header: "Finding", render: (f) => (
              <div className="py-1">
                <button type="button" className="text-left font-medium text-fg hover:underline" onClick={(e) => { e.stopPropagation(); setOpen(f); }}>{f.title}</button>
                {f.detail && <div className="line-clamp-1 text-[12px] text-fg-3">{f.detail}</div>}
              </div>), sort: (f) => f.title },
            { key: "where", header: "Where", render: (f) => <Where f={f} /> },
            { key: "stage", header: "Stage", render: (f) => <span className="mono text-[12px]">{f.stage ?? "—"}</span>, sort: (f) => f.stage ?? "" },
          ]} />
      </Panel>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.title}>
        {open && (
          <div className="flex flex-col gap-4">
            <div className="flex gap-2"><SeverityBadge sev={open.severity} /><span className="badge tone-muted capitalize">{open.category}</span><span className="mono text-[12px] text-fg-3">{open.kind}</span></div>
            {open.detail && <p className="m-0 leading-[1.6]">{open.detail}</p>}
            <KeyValues cols={1} items={[
              ["Where", <Where f={open} />],
              ["Detected in", open.stage && open.run_version ? <Link to={runPath(open.stage, open.run_version)}>{open.stage} <span className="mono">{open.run_version}</span></Link> : open.stage],
              ["Related", open.related.length ? open.related.map((r) => <Link key={r.id} className="mr-2" to="/evidence/$kind/$id" params={{ kind: r.kind, id: r.id }}>{r.id}</Link>) : null],
              ["Evidence", open.evidence.length ? open.evidence.map((e) => <div key={e.label} className="mono">{e.path}</div>) : null],
              ["Next step", open.next_step],
            ]} />
            {open.subject && ["gap", "rule", "object", "table", "column"].includes(open.subject.kind) &&
              <Link to="/evidence/$kind/$id" params={{ kind: open.subject.kind, id: open.subject.id }}>Open the evidence page →</Link>}
          </div>
        )}
      </Drawer>
    </div>
  );
}

function Where({ f }: { f: Finding }) {
  const l = f.location;
  if (!l) return <span className="text-fg-3">—</span>;
  if (l.object_id) return <Link to="/evidence/$kind/$id" params={{ kind: "object", id: l.object_id }} className="mono text-[12px]">{l.object_id.replace(/^[A-Z]+-\./, "")}{l.line ? `:${l.line}` : ""}</Link>;
  return <span className="mono text-[12px]">{l.file ?? ""}{l.line ? `:${l.line}` : ""}</span>;
}
