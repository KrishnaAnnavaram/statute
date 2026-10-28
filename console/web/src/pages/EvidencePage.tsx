import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { api, runPath, type EvidenceEntity, type EvidenceRef, type SourceWindow } from "../api";
import { DataTable, Empty, ErrorBox, KeyValues, Loading, Mono, PageHeader, Panel, Pill, SeverityBadge } from "../components/ui";

const KIND_LABEL: Record<string, string> = { rule: "Rule", requirement: "Requirement", gap: "Open matter", object: "Program object",
  statement: "Statement", table: "Table", column: "Column", file: "Source file" };

export function EvidenceSearchPage({ q }: { q?: string }) {
  const navigate = useNavigate();
  const [text, setText] = useState(q ?? "");
  const res = useQuery({ queryKey: ["search", q], enabled: !!q,
    queryFn: () => api<{ results: EvidenceRef[] }>("/evidence/search", { q }) });
  return (
    <div className="max-w-[1100px]">
      <PageHeader title="Evidence" subtitle="Trace any requirement, rule, open matter, program object, table, column or file back to its source line." />
      <form role="search" onSubmit={(e) => { e.preventDefault(); navigate({ to: "/evidence", search: { q: text || undefined } }); }} className="mb-4 flex gap-2">
        <input type="search" autoFocus aria-label="Search evidence" value={text} onChange={(e) => setText(e.target.value)}
          placeholder="e.g. BR-002, GAP-016, SP_TRANSFER_FUNDS, ACCOUNTS.BALANCE" className="flex-1 rounded border border-line bg-surface px-3 py-1.5" />
        <button type="submit" className="rounded border border-line bg-surface-2 px-3 py-1.5 hover:bg-surface-3">Search</button>
      </form>
      {!q && (
        <Panel title="Start here">
          <div className="flex flex-wrap gap-2 p-4">
            {[["rule", "BR-002"], ["gap", "GAP-016"], ["object", "PROC-.SP_TRANSFER_FUNDS"], ["table", "ACCOUNTS"], ["column", "ACCOUNTS.BALANCE"]].map(([k, id]) => (
              <Link key={id} to="/evidence/$kind/$id" params={{ kind: k, id }} className="rounded border border-line px-2.5 py-1 no-underline hover:bg-surface-2">
                <span className="text-fg-3">{KIND_LABEL[k]}</span> <span className="mono">{id}</span></Link>
            ))}
          </div>
        </Panel>
      )}
      {res.isLoading && <Loading />}
      {res.error && <ErrorBox error={res.error} />}
      {res.data && (
        <Panel title={`${res.data.results.length} result(s)`}>
          <DataTable rows={res.data.results} rowKey={(r) => r.kind + r.id} empty="Nothing matches — try an id, a table or a program name"
            onRowClick={(r) => navigate({ to: "/evidence/$kind/$id", params: { kind: r.kind, id: r.id } })}
            columns={[
              { key: "kind", header: "Kind", width: "130px", render: (r) => KIND_LABEL[r.kind] ?? r.kind },
              { key: "label", header: "Match", render: (r) => <Link to="/evidence/$kind/$id" params={{ kind: r.kind, id: r.id }}>{r.label}</Link> },
              { key: "detail", header: "", render: (r) => <span className="text-fg-3">{r.detail}</span> },
            ]} />
        </Panel>
      )}
    </div>
  );
}

export function EntityPage({ kind, id }: { kind: string; id: string }) {
  const q = useQuery({ queryKey: ["entity", kind, id], queryFn: () => api<EvidenceEntity>(`/evidence/${kind}/${encodeURIComponent(id)}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <><PageHeader eyebrow={<Link to="/evidence">Evidence</Link>} title={<span className="mono">{id}</span>} /><ErrorBox error={q.error} /></>;
  const e = q.data!;
  const facts = Object.entries(e.facts ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== "") as [string, unknown][];
  return (
    <div className="flex max-w-[1200px] flex-col gap-4">
      <PageHeader eyebrow={<><Link to="/evidence">Evidence</Link> › {KIND_LABEL[e.kind] ?? e.kind}</>}
        title={e.title} subtitle={<span className="mono text-[12.5px]">{e.id}</span>}>
        {e.kind === "rule" && e.facts?.["needs SME review"] === true && <Pill tone="tone-warn">Needs SME review</Pill>}
        {e.kind === "gap" && e.facts?.severity ? <SeverityBadge sev={e.facts.severity as "high"} /> : null}
      </PageHeader>

      {e.requirement && (
        <Panel title="Requirement (as stated in the BRD)">
          <div className="flex flex-col gap-2 p-4">
            <p className="m-0 text-[14px] leading-[1.6]">{e.requirement.text}</p>
            <p className="m-0 text-fg-2"><span className="text-fg-3">Formal: </span>{e.requirement.formal}</p>
            <KeyValues items={[["Modality", e.requirement.modality], ["Type", e.requirement.type], ["Verification", e.requirement.verification],
              ["Needs review", e.requirement.needs_review ? "yes" : "no"], ["Owner", e.requirement.owner ?? <span className="text-[color:var(--warn)]">unassigned</span>],
              ["Priority", e.requirement.priority ?? <span className="text-[color:var(--warn)]">unassigned</span>]]} />
          </div>
        </Panel>
      )}

      <Panel title="Provenance path">
        <ol className="m-0 list-none p-4">
          {e.provenance.map((p, i) => (
            <li key={i} className="relative flex gap-3 pb-3 last:pb-0" style={{ paddingLeft: i * 18 }}>
              <span aria-hidden className="mono text-fg-3">{i ? "└" : "●"}</span>
              <div className="min-w-0">
                <EvidenceLink r={p} />
                {p.detail && <span className="ml-2 text-[12px] text-fg-3">{p.detail}</span>}
                {p.stage && p.run_version && <div className="text-[11.5px] text-fg-3">from <Link to={runPath(p.stage, p.run_version)}>{p.stage} <span className="mono">{p.run_version}</span></Link></div>}
              </div>
            </li>
          ))}
        </ol>
      </Panel>

      {e.location?.file_id && e.location.line ? <SourcePanel fileId={e.location.file_id} line={e.location.line} pipelineRun={e.pipeline_run} /> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        {facts.length > 0 && <Panel title="Facts"><div className="p-4"><KeyValues cols={1} items={facts.map(([k, v]) => [k, fmtVal(v)])} /></div></Panel>}
        {(e.condition || e.description) && (
          <Panel title="What the code says">
            <div className="flex flex-col gap-2 p-4">
              {e.condition && <div><div className="text-[12px] text-fg-3">Condition</div><code className="mono">{e.condition}</code></div>}
              {e.description && <p className="m-0 text-fg-2">{e.description}</p>}
              {e.note && <p className="m-0 text-[12px] text-fg-3">{e.note}</p>}
            </div>
          </Panel>
        )}
      </div>

      {e.rules && e.rules.length > 0 && <Panel title={`Rules (${e.rules.length})`}><DataTable rows={e.rules} rowKey={(r) => r.id} columns={[
        { key: "id", header: "Rule", render: (r) => <Link to="/evidence/$kind/$id" params={{ kind: "rule", id: r.id }} className="mono">{r.id}</Link>, sort: (r) => r.id },
        { key: "name", header: "Name", render: (r) => r.name },
        { key: "line", header: "Line", num: true, render: (r) => <span className="mono">{r.line ?? "—"}</span>, sort: (r) => r.line ?? 0 },
        { key: "conf", header: "Confidence", render: (r) => r.confidence ?? "—" },
      ]} /></Panel>}
      {e.related_rules && e.related_rules.length > 0 && <Panel title="Related rules"><ul className="m-0 p-4 pl-8">{e.related_rules.map((r) => <li key={r.id}><Link to="/evidence/$kind/$id" params={{ kind: "rule", id: r.id }} className="mono">{r.id}</Link> {r.name}</li>)}</ul></Panel>}
      {e.hazards && e.hazards.length > 0 && <Panel title="Transaction hazards"><ul className="m-0 p-4 pl-8">{e.hazards.map((h, i) => <li key={i}><b>{String(h.hazard)}</b> ({String(h.severity)}) — {String(h.explanation)}</li>)}</ul></Panel>}
      {e.columns && <Panel title={`Columns (${e.columns.length})`}><DataTable rows={e.columns} rowKey={(c) => String(c.name)} columns={[
        { key: "name", header: "Column", render: (c) => <Link to="/evidence/$kind/$id" params={{ kind: "column", id: `${e.id}.${c.name}` }} className="mono">{String(c.name)}</Link> },
        { key: "type", header: "Type", render: (c) => <span className="mono">{String(c.type)}</span> },
        { key: "null", header: "Nullable", render: (c) => (c.nullable ? "yes" : "no") },
      ]} /></Panel>}
      {e.checks && e.checks.length > 0 && <Panel title="Constraints"><DataTable rows={e.checks} rowKey={(c) => String(c.name)} columns={[
        { key: "name", header: "Constraint", render: (c) => <span className="mono">{String(c.name)}</span> },
        { key: "expr", header: "Expression", render: (c) => <code className="mono">{String(c.expression)}</code> },
        { key: "enf", header: "Enforced by the database", render: (c) => (c.enforced ? "yes" : <span className="text-[color:var(--fail)]">no — {String(c.state)}</span>) },
      ]} /></Panel>}
      {e.crud && Object.keys(e.crud).length > 0 && <Panel title="Data access (CRUD)"><div className="p-4"><KeyValues cols={1} items={Object.entries(e.crud).map(([k, v]) => [k, <span className="mono">{v}</span>])} /></div></Panel>}
      {e.appears_in && e.appears_in.length > 0 && <Panel title="Appears in"><ul className="m-0 p-4 pl-8">{e.appears_in.map((a, i) => <li key={i} className="mono">{String(a.diagram)}{a.node ? ` · node ${String(a.node)}` : ""}{a.title ? <span className="font-sans text-fg-2"> — {String(a.title)}</span> : null}</li>)}</ul></Panel>}
      {e.used_by && <Panel title="Used by"><ul className="m-0 p-4 pl-8">{e.used_by.map((u) => <li key={u.id}><Link to="/evidence/$kind/$id" params={{ kind: "object", id: u.id }} className="mono">{u.id}</Link></li>)}</ul></Panel>}
      {e.objects && <Panel title="Objects in this file">{e.objects.length ? <ul className="m-0 p-4 pl-8">{e.objects.map((u) => <li key={u.id}><Link to="/evidence/$kind/$id" params={{ kind: "object", id: u.id }} className="mono">{u.id}</Link></li>)}</ul> : <Empty title="No program objects (DDL or data file)" />}</Panel>}
      {e.gaps && e.gaps.length > 0 && <Panel title="Open matters"><ul className="m-0 p-4 pl-8">{e.gaps.map((g) => <li key={g.id}><Link to="/evidence/$kind/$id" params={{ kind: "gap", id: g.id }}>{g.id}</Link> {g.title}</li>)}</ul></Panel>}
      <div className="text-[12px] text-fg-3">From pipeline run <span className="mono">{e.pipeline_run}</span></div>
    </div>
  );
}

function fmtVal(v: unknown): ReactNode {
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

function EvidenceLink({ r }: { r: EvidenceRef }) {
  const link = ["rule", "requirement", "gap", "object", "statement", "table", "column", "file"].includes(r.kind);
  const label = <><span className="text-fg-3">{KIND_LABEL[r.kind] ?? r.kind}</span> <Mono max={72}>{r.label}</Mono></>;
  return link ? <Link to="/evidence/$kind/$id" params={{ kind: r.kind === "requirement" ? "rule" : r.kind, id: r.id }} className="inline-block min-h-6 py-0.5">{label}</Link> : label;
}

function SourcePanel({ fileId, line, pipelineRun }: { fileId: string; line: number; pipelineRun: string | null }) {
  const [show, setShow] = useState(false);
  const q = useQuery({ queryKey: ["source", fileId, line, pipelineRun], enabled: show,
    queryFn: () => api<SourceWindow>("/source", { file_id: fileId, line, context: 4, pipeline_run: pipelineRun ?? undefined }) });
  return (
    <Panel title="Source" actions={<button type="button" onClick={() => setShow((s) => !s)} aria-expanded={show}
      className="rounded border border-line px-2 py-0.5 text-[12px] hover:bg-surface-2">{show ? "Hide source lines" : "Show source lines"}</button>}>
      {!show ? <div className="px-4 py-2.5 text-[12.5px] text-fg-3">Source text is hidden by default (it is client code). Line {line}.</div> : (
        <div className="p-3">
          {q.isLoading && <Loading />}
          {q.error && <ErrorBox error={q.error} />}
          {q.data && !q.data.available && <div className="text-fg-2">{q.data.reason}</div>}
          {q.data?.available && (
            <>
              <div className="mb-1.5 text-[12px] text-fg-3"><span className="mono">{q.data.file}</span> · located via {q.data.located_via}</div>
              <pre className="mono m-0 overflow-x-auto rounded border border-line bg-surface-2 py-2 text-[12.5px]">
                {q.data.lines.map((l) => (
                  <div key={l.n} className={l.n === q.data!.focus ? "bg-accent-soft" : ""} aria-current={l.n === q.data!.focus ? "true" : undefined}>
                    <span className="inline-block w-12 select-none pr-3 text-right text-fg-3">{l.n}</span>{l.text}
                  </div>
                ))}
              </pre>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}
