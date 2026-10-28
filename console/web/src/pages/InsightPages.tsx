import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api, runPath, type DataModel, type DiagramsData, type PipelineDetail, type Quality, type RulesData } from "../api";
import { useStatus } from "../queries";
import { fmtDuration, stageName, stageNo } from "../lib/format";
import { Empty, ErrorBox, FreshnessBadge, KeyValues, Loading, Meter, PageHeader, Pill, StateBadge } from "../components/ui";
import { MermaidView } from "../components/viewers";
import { LineageGraph } from "../components/graphs";

const CONF_COLOR: Record<string, string> = { confirmed: "var(--color-green)", high: "var(--color-accent-text)", medium: "var(--color-blue-text)", low: "var(--color-text-muted)" };
const CAT_COLOR: Record<string, string> = { VALIDATION: "var(--color-blue-text)", CALCULATION: "var(--color-accent-text)", LIMIT_CHECK: "var(--color-green)",
  ROUTING: "var(--color-violet)", ERROR_HANDLING: "var(--color-orange)", COMPLIANCE: "var(--color-red)" };

/* ===================================================== Synthetic testing == */
export function TestingPage() {
  const q = useQuery({ queryKey: ["quality"], queryFn: () => api<Quality>("/quality"), refetchInterval: 10000 });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const conf = d.by_confidence, total = d.total_rules;
  const ready = (conf.confirmed ?? 0) + (conf.high ?? 0);
  const review = (conf.medium ?? 0) + (conf.low ?? 0);
  const coverage = total ? Math.round((ready / total) * 100) : 0;
  const tone = d.score >= 70 ? "var(--color-green)" : d.score >= 40 ? "var(--color-accent-text)" : "var(--color-red)";
  const sevTotal = Object.values(d.gaps_by_severity).reduce((a, b) => a + b, 0);
  return (
    <div>
      <PageHeader title="Synthetic testing" subtitle={`Business-rule coverage — a quality gate derived from the ${total} rules STATUTE extracted, the BRD's verification methods and the diagram quality gates.`} />
      <div className="card mb-5 flex flex-wrap items-center gap-8" style={{ borderColor: tone }}>
        <div className="min-w-[110px] text-center">
          <div className="text-[48px] font-extrabold leading-none" style={{ color: tone }}>{d.score}</div>
          <div className="label mt-1.5">Quality score</div>
        </div>
        <div className="min-w-[280px] flex-1">
          <div className="mb-2 text-[13px]"><strong>{coverage}% testable</strong> — {ready} of {total} rules have confirmed or high-confidence evidence in the PL/SQL and can become test scenarios directly.</div>
          <div className="progress-bar" style={{ height: 10 }}><div className="progress-bar-fill" style={{ width: `${coverage}%`, background: "var(--color-green)" }} /></div>
          <div className="mt-2.5 flex flex-wrap gap-5 text-[12px] text-fg-3">
            <span style={{ color: "var(--color-green)" }}>✓ {conf.confirmed ?? 0} confirmed</span>
            <span style={{ color: "var(--color-accent-text)" }}>↑ {conf.high ?? 0} high</span>
            <span>~ {conf.medium ?? 0} medium</span><span>↓ {conf.low ?? 0} low</span>
          </div>
          <div className="mt-2 text-[11px] text-fg-3">score = (confirmed×1.0 + high×0.9 + medium×0.5 + low×0.2) ÷ rules × 100</div>
        </div>
        <div className="grid min-w-[240px] grid-cols-2 gap-2.5">
          {[["Total rules", total, "var(--color-text)"], ["Needs review", review, "var(--color-accent-text)"],
            ["Test-ready", ready, "var(--color-green)"], ["Coverage", `${coverage}%`, "var(--color-blue-text)"]].map(([l, v, c]) => (
            <div key={String(l)} className="rounded-lg bg-surface-2 px-3 py-2.5">
              <div className="label mb-0.5">{l}</div>
              <div className="text-[20px] font-bold" style={{ color: String(c) }}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <div className="card">
          <div className="mb-3.5 text-[14px] font-bold">Rules by confidence</div>
          {Object.entries(conf).sort((a, b) => b[1] - a[1]).map(([k, v]) => <Meter key={k} label={<span className="capitalize">{k}</span>} value={v} total={total} color={CONF_COLOR[k]} />)}
        </div>
        <div className="card">
          <div className="mb-3.5 text-[14px] font-bold">Rules by category</div>
          {Object.entries(d.by_category).filter(([, v]) => v).sort((a, b) => b[1] - a[1]).map(([k, v]) => <Meter key={k} label={k} value={v} total={total} color={CAT_COLOR[k]} />)}
        </div>
        <div className="card">
          <div className="mb-3.5 text-[14px] font-bold">How each requirement is verified</div>
          {Object.entries(d.verification).map(([k, v]) => <Meter key={k} label={k} value={v} total={d.requirements} color={k.startsWith("Test") ? "var(--color-blue-text)" : "var(--color-green)"} />)}
          <div className="mt-3 text-[12px] text-fg-3">{d.unowned} of {d.requirements} requirements have no owner or priority yet (visible blanks in the BRD).</div>
        </div>
      </div>

      <div className="mb-5 grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="mb-3 text-[14px] font-bold">Quality gates (06_diagram)</div>
          <table className="dt">
            <thead><tr><th>Gate</th><th className="num">Value</th><th className="num">Threshold</th><th>Result</th></tr></thead>
            <tbody>
              {d.gates.map((g) => {
                const v = g.value ?? 0;
                const pass = g.threshold === null ? null : g.fmt === "pct" ? v >= g.threshold : v <= g.threshold;
                return (
                  <tr key={g.name}>
                    <td>{g.name}</td>
                    <td className="num mono">{g.value === null ? "—" : g.fmt === "pct" ? `${Math.round(v * 100)}%` : v}</td>
                    <td className="num mono text-fg-3">{g.threshold === null ? "—" : g.fmt === "pct" ? `≥ ${Math.round(g.threshold * 100)}%` : `≤ ${g.threshold}`}</td>
                    <td>{pass === null ? <Pill>info</Pill> : pass ? <Pill tone="tone-ok"><span className="dot" />pass</Pill> : <Pill tone="tone-warn"><span className="dot" />declared over</Pill>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="mb-3.5 text-[14px] font-bold">Open matters by type</div>
          {Object.entries(d.gaps_by_type).sort((a, b) => b[1] - a[1]).map(([k, v]) => <Meter key={k} label={k.replace(/_/g, " ").toLowerCase()} value={v} total={sevTotal} color="var(--color-orange)" />)}
        </div>
      </div>

      {review > 0 && (
        <div className="callout-warn">
          <strong style={{ color: "var(--color-accent-text)" }}>⚠ {review} rules need SME review</strong> before they can be turned into test scenarios — the branch condition is documented, but its business meaning needs confirmation. Open the <Link to="/rules">Rules</Link> tab or the <Link to="/findings" search={{ category: "review" }}>Review queue</Link>.
          <div className="mt-1.5 text-[12px] text-fg-3">Regression suite: {d.suites.suites} self-checking suites, {d.suites.checks} checks. {d.suites.note}.</div>
        </div>
      )}
    </div>
  );
}

/* ================================================= Interactive workflow == */
export function WorkflowPage() {
  const { data: s } = useStatus();
  const pid = s?.pipeline_run?.id;
  const [sel, setSel] = useState<string | null>(null);
  const p = useQuery({ queryKey: ["pipeline-run", pid], enabled: !!pid, queryFn: () => api<PipelineDetail>(`/pipeline-runs/${encodeURIComponent(pid!)}`) });
  const dg = useQuery({ queryKey: ["diagrams"], queryFn: () => api<DiagramsData>("/diagrams") });
  if (!s) return <Loading />;
  const stage = sel ? s.stages.find((x) => x.stage === sel) : null;
  const dataflow = dg.data?.diagrams.find((d) => d.type === "dataflow");
  return (
    <div>
      <PageHeader title="Interactive workflow" subtitle="How the stages feed each other in the current pipeline run, and how the analysed programs use the data. Click a stage for details." />
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1">
          <div className="card mb-4">
            <div className="mb-3 text-[14px] font-bold">Stage lineage · {pid ?? "no pipeline run"}</div>
            {p.data ? <LineageGraph lineage={p.data.lineage} onSelect={setSel} selected={sel} /> : p.isLoading ? <Loading /> : <Empty title="No pipeline run yet" />}
          </div>
          <div className="card">
            <div className="mb-1 text-[14px] font-bold">System data flow</div>
            <div className="mb-3 text-[12px] text-fg-3">Programs × tables they create, read, update or delete — STATUTE's own <span className="mono">system_dataflow.mmd</span>.</div>
            {dataflow?.source ? <MermaidView source={dataflow.source} title="System data flow" height={520} /> : dg.isLoading ? <Loading /> : <Empty title="No data-flow diagram in this run" />}
          </div>
        </div>
        {stage && (
          <div className="card w-full shrink-0 xl:sticky xl:top-0 xl:w-[300px]">
            <div className="mb-3 flex items-start justify-between">
              <div><div className="label">Stage {stage.n}</div><div className="text-[15px] font-bold capitalize">{stageName(stage.stage)}</div></div>
              <button type="button" className="btn !px-2 !py-0.5" onClick={() => setSel(null)} aria-label="Close stage details">×</button>
            </div>
            <div className="mb-3 flex flex-wrap gap-1.5"><StateBadge state={stage.latest?.state} basis={stage.latest?.state_basis} /><FreshnessBadge value={stage.freshness.value} /></div>
            <p className="mb-3 mt-0 text-[12px] leading-relaxed text-fg-3">{stage.purpose}</p>
            <KeyValues cols={1} items={[
              ["Agent", <span className="mono text-[12px]">{stage.agent}</span>],
              ["Run", stage.latest ? <Link to={runPath(stage.stage, stage.latest.id)} className="mono text-[12px]">{stage.latest.run_version}</Link> : null],
              ["Duration", fmtDuration(stage.latest?.duration_ms)],
              ["Output", stage.key_stat.join(" · ")],
              ["Why", stage.freshness.causes.map((c) => c.text).join("; ") || "built from the latest inputs"],
            ]} />
          </div>
        )}
      </div>
    </div>
  );
}

/* ============================================================= Diagrams == */
export function DiagramsPage() {
  const q = useQuery({ queryKey: ["diagrams"], queryFn: () => api<DiagramsData>("/diagrams") });
  const [sel, setSel] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const cur = d.diagrams.find((x) => x.file === sel) ?? d.diagrams[0];
  return (
    <div>
      <PageHeader title="Diagrams" subtitle={`${d.diagrams.length} diagrams generated by 06_diagram — data flow, entity lifecycles and one process flow per program. Rendered in isolated frames.`} />
      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="panel self-start overflow-hidden">
          {d.diagrams.map((x) => (
            <button key={x.file} type="button" onClick={() => setSel(x.file)} aria-pressed={cur?.file === x.file}
              className="block w-full border-b border-l-2 border-line px-3.5 py-2.5 text-left last:border-b-0 hover:bg-surface-2"
              style={{ borderLeftColor: cur?.file === x.file ? "var(--color-accent)" : "transparent", background: cur?.file === x.file ? "var(--color-surface-2)" : undefined }}>
              <div className="text-[13px] font-semibold">{x.title}</div>
              <div className="mt-0.5 flex gap-2 text-[11px] text-fg-3">
                <span>{x.type.replace("_", " ")}</span><span>· {x.nodes} nodes</span>{x.oversize && <span style={{ color: "var(--color-amber)" }}>· over budget</span>}
              </div>
            </button>
          ))}
        </div>
        <div className="card min-w-0">
          {cur ? (
            <>
              <div className="mb-3 flex flex-wrap items-baseline gap-3">
                <div className="text-[15px] font-bold">{cur.title}</div>
                <span className="mono text-[11px] text-fg-3">{cur.file}</span>
                {cur.object_id && <Link to="/evidence/$kind/$id" params={{ kind: "object", id: cur.object_id }} className="text-[12px]">object evidence →</Link>}
              </div>
              {cur.source ? <MermaidView key={cur.file} source={cur.source} title={cur.title} height="68vh" /> : <Empty title="Diagram source missing" />}
              {d.warnings.filter((w) => w.diagram === cur.file.replace(".mmd", "")).map((w, i) => (
                <div key={i} className="callout mt-3"><b className="text-fg">{w.kind}</b> — {w.detail}</div>
              ))}
            </>
          ) : <Empty title="No diagrams in this run" />}
        </div>
      </div>
    </div>
  );
}

/* ================================================================ Rules == */
export function RulesPage() {
  const q = useQuery({ queryKey: ["rules"], queryFn: () => api<RulesData>("/rules"), refetchInterval: 15000 });
  const [cat, setCat] = useState("ALL");
  const [conf, setConf] = useState("ALL");
  const [sme, setSme] = useState(false);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  if (q.isLoading) return <Loading what="Loading rules" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const rules = q.data!.rules;
  const cats = ["ALL", ...Array.from(new Set(rules.map((r) => r.category)))];
  const confs = ["ALL", ...["confirmed", "high", "medium", "low"].filter((c) => rules.some((r) => r.confidence === c))];
  const s = search.toLowerCase();
  const shown = rules.filter((r) => (cat === "ALL" || r.category === cat) && (conf === "ALL" || r.confidence === conf) && (!sme || r.requires_sme_review)
    && (!s || `${r.rule_id} ${r.name} ${r.condition} ${r.description}`.toLowerCase().includes(s)));
  return (
    <div>
      <PageHeader title="Rules explorer" subtitle={`${rules.length} business rules mined from the PL/SQL and DDL — click a row to expand. Rule ids are renumbered when the rule set changes.`} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input className="input w-[220px]" placeholder="Search rules…" aria-label="Search rules" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="flex flex-wrap gap-1.5">{cats.map((c) => <button key={c} type="button" className={`pill${cat === c ? " active" : ""}`} onClick={() => setCat(c)}>{c.replace("_", " ")}</button>)}</div>
        <div className="flex flex-wrap gap-1.5">{confs.map((c) => <button key={c} type="button" className={`pill${conf === c ? " active" : ""}`} onClick={() => setConf(c)}>{c}</button>)}</div>
        <button type="button" className={`pill${sme ? " active" : ""}`} aria-pressed={sme} onClick={() => setSme((x) => !x)}>⚑ SME review only</button>
        <span className="ml-auto text-[12px] text-fg-3">{shown.length} of {rules.length} rules</span>
      </div>
      <div className="panel overflow-x-auto">
        <table className="dt">
          <thead><tr><th style={{ width: 80 }}>ID</th><th>Name</th><th>Category</th><th>Confidence</th><th>Source</th><th>Line</th><th style={{ width: 50 }}>SME</th></tr></thead>
          <tbody>
            {shown.map((r) => (
              <Fragment key={r.rule_id}>
                <tr className="cursor-pointer" onClick={() => setOpen(open === r.rule_id ? null : r.rule_id)} style={{ background: open === r.rule_id ? "var(--color-surface-2)" : undefined }}>
                  <td><button type="button" className="mono text-[12px] font-bold" style={{ color: "var(--color-accent-text)" }} aria-expanded={open === r.rule_id}
                    onClick={(e) => { e.stopPropagation(); setOpen(open === r.rule_id ? null : r.rule_id); }}>{r.rule_id}</button></td>
                  <td className="font-medium">{r.name}</td>
                  <td><span className="rounded px-2 py-0.5 text-[11px] font-semibold" style={{ color: CAT_COLOR[r.category] ?? "var(--color-text)", background: `color-mix(in srgb, ${CAT_COLOR[r.category] ?? "#888"} 15%, transparent)` }}>{r.category}</span></td>
                  <td className="text-[12px] font-semibold capitalize" style={{ color: CONF_COLOR[r.confidence] }}>{r.confidence}</td>
                  <td className="mono text-[11px] text-fg-3">{r.object_id ? r.object_id.replace(/^[A-Z]+-\./, "") : r.table ? `${r.table} · ${r.constraint}` : "—"}</td>
                  <td className="mono text-[11px] text-fg-3">{r.line ?? "—"}</td>
                  <td className="text-center">{r.requires_sme_review && <span title="Needs SME review" style={{ color: "var(--color-accent-text)" }}>⚑<span className="sr-only">needs SME review</span></span>}</td>
                </tr>
                {open === r.rule_id && (
                  <tr style={{ background: "var(--color-surface-2)" }}>
                    <td colSpan={7} className="!px-4 !py-3">
                      <div className="grid gap-4 text-[12px] md:grid-cols-2">
                        <div>
                          <div className="label mb-1">Requirement (as stated in the BRD)</div>
                          <div className="leading-relaxed">{r.requirement ?? r.description}</div>
                          <div className="mt-2 text-fg-3">{r.modality} · verified by {r.verification ?? "—"} · rule set {r.rule_set ?? "—"}</div>
                        </div>
                        <div>
                          <div className="label mb-1">Condition</div>
                          <div className="mono rounded-md border border-line bg-surface px-2.5 py-1.5">{r.condition || "—"}</div>
                          <div className="mt-1.5 text-fg-3">Pattern {r.pattern} · source {r.source_kind}{r.is_enforced === true ? " · enforced by the database" : r.is_enforced === false ? " · NOT enforced" : ""}</div>
                          <div className="mt-2 flex gap-3">
                            <Link to="/evidence/$kind/$id" params={{ kind: "rule", id: r.rule_id }}>Trace to source →</Link>
                            {r.object_id && <Link to="/evidence/$kind/$id" params={{ kind: "object", id: r.object_id }}>Object →</Link>}
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {!shown.length && <Empty title="No rules match these filters" />}
      </div>
      {q.data!.error_handling.length > 0 && (
        <div className="mt-4 text-[12px] text-fg-3">Also catalogued (not promoted to rules): {q.data!.error_handling.length} generic error handlers.</div>
      )}
    </div>
  );
}

/* =========================================================== Data model == */
export function DataModelPage() {
  const q = useQuery({ queryKey: ["data-model"], queryFn: () => api<DataModel>("/data-model") });
  const [search, setSearch] = useState("");
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const st = d.stats;
  const shown = d.tables.filter((t) => !search || t.table.toLowerCase().includes(search.toLowerCase()));
  const crud = (ops: string) => ops.split("").map((c) => (
    <span key={c} className="mono mr-0.5 inline-block w-4 rounded text-center text-[10px] font-bold"
      style={{ color: { C: "var(--color-green)", R: "var(--color-blue-text)", U: "var(--color-accent-text)", D: "var(--color-red)" }[c], background: "var(--color-surface-2)" }}>{c}</span>));
  return (
    <div>
      <PageHeader title="Data model" subtitle="The physical data dictionary recovered from the DDL by 03_data, with constraint enforcement state and which programs use each table." />
      <div className="mb-4 grid grid-cols-2 gap-2.5 md:grid-cols-6">
        {[["Tables", st.tables_found], ["Columns", st.columns_total], ["Foreign keys", `${st.declared_foreign_keys ?? 0} + ${st.inferred_foreign_keys ?? 0} inferred`],
          ["CHECK constraints", st.check_constraints], ["Disabled constraints", st.disabled_constraints], ["Comment-only enums", st.comment_only_enums]].map(([l, v]) => (
          <div key={String(l)} className="kpi-tile"><div className="kpi-label">{l}</div><div className="kpi-value !text-[22px]">{v ?? "—"}</div></div>
        ))}
      </div>
      <div className="grid gap-4 2xl:grid-cols-2">
        <div className="panel overflow-x-auto">
          <div className="panel-h"><h2>Tables</h2><input className="input ml-auto w-[180px] !py-1" placeholder="Filter tables…" aria-label="Filter tables" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
          <table className="dt">
            <thead><tr><th>Table</th><th className="num">Columns</th><th>References</th><th className="num">Checks</th><th>Used by (CRUD)</th></tr></thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.table}>
                  <td><Link to="/evidence/$kind/$id" params={{ kind: "table", id: t.table }} className="mono text-[12px] font-semibold">{t.table}</Link></td>
                  <td className="num">{t.columns}</td>
                  <td className="mono text-[11px] text-fg-3">{t.fks.join(", ") || "—"}</td>
                  <td className="num">{t.checks || "—"}</td>
                  <td className="text-[11px]">
                    {Object.keys(t.used_by).length ? Object.entries(t.used_by).map(([o, ops]) => (
                      <div key={o} className="whitespace-nowrap">{crud(ops)} <Link to="/evidence/$kind/$id" params={{ kind: "object", id: o }} className="mono">{o.replace(/^[A-Z]+-\./, "")}</Link></div>
                    )) : <span className="text-fg-3">no program in this corpus</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="mb-1 text-[14px] font-bold">Entity-relationship diagram</div>
          <div className="mb-3 text-[12px] text-fg-3">From <span className="mono">erd.mmd</span> (03_data run <span className="mono">{d.run_version}</span>); inferred relationships are dashed.</div>
          {d.erd ? <MermaidView source={d.erd} title="Entity-relationship diagram" height="70vh" /> : <Empty title="No ERD in this run" />}
        </div>
      </div>
      <p className="mt-3 text-[12px] text-fg-3"><span className="mono">{stageNo("03_data")}</span> data run · C create · R read · U update · D delete (from 04_logic's CRUD matrix).</p>
    </div>
  );
}
