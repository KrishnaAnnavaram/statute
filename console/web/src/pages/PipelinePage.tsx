import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { runPath, type Finding, type StageCard, type Status } from "../api";
import { useStatus } from "../queries";
import { fmtAgo, fmtDuration, fmtTime, stageName } from "../lib/format";
import { CopyButton, Empty, ErrorBox, FreshnessBadge, Icon, Loading, Panel, SeverityBadge, StateBadge } from "../components/ui";

/** Pipeline overview: where every stage stands, what needs attention, and what to do next. */
export function PipelinePage() {
  const { data: s, error, isLoading } = useStatus();
  if (isLoading) return <Loading what="Reading the output directory" />;
  if (!s) return <ErrorBox error={error} />;
  return (
    <div className="flex flex-col gap-5">
      <Progress s={s} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-5">
          <Stages stages={s.stages} />
          <Attention items={s.attention} counts={s.finding_counts} />
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <QualityGate s={s} />
          <LatestRun s={s} />
          <NextSteps s={s} />
          <Activity s={s} />
        </div>
      </div>
    </div>
  );
}

function Progress({ s }: { s: Status }) {
  const k = s.kpis;
  const counts = { done: 0, stale: 0, running: 0, failed: 0, pending: 0 };
  for (const c of s.stages) counts[phase(c)]++;
  const unrecorded = s.stages.filter((c) => c.latest && c.freshness.value === "unknown").length;
  return (
    <div className="card">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h2 className="m-0 text-[15px] font-bold">Pipeline overview</h2>
        <span className="text-[12px] text-fg-3">{k.stages_done} of {k.stages_total} stages current · deterministic, no LLM in the generation path</span>
        <span className="ml-auto text-[22px] font-extrabold" style={{ color: "var(--color-accent-text)" }}>{k.overall_pct}%</span>
      </div>
      <div className="progress-bar" style={{ height: 8 }} role="progressbar" aria-valuenow={k.overall_pct} aria-valuemin={0} aria-valuemax={100} aria-label="Stages current">
        <div className="progress-bar-fill" style={{ width: `${k.overall_pct}%`, background: "var(--color-accent)" }} />
      </div>
      <div className="mt-2.5 flex flex-wrap gap-2 text-[12px]">
        <span className="badge tone-ok"><span className="dot" />{counts.done} done</span>
        {counts.running > 0 && <span className="badge tone-run"><Icon name="ring" size={11} />{counts.running} running</span>}
        {counts.stale > 0 && <span className="badge tone-warn"><span className="dot" />{counts.stale} out of date</span>}
        {unrecorded > 0 && <span className="badge tone-unknown" title="Done, but the run does not record every input it consumed, so freshness cannot be proven"><span className="dot" />{unrecorded} provenance unrecorded</span>}
        {counts.failed > 0 && <span className="badge tone-fail"><span className="dot" />{counts.failed} failed</span>}
        {counts.pending > 0 && <span className="badge tone-muted"><span className="dot" />{counts.pending} never run</span>}
      </div>
    </div>
  );
}

type Phase = "done" | "stale" | "running" | "failed" | "pending";
function phase(c: StageCard): Phase {
  const n = c.newest;
  if (n?.state === "running") return "running";
  if (n && (n.state === "failed" || n.state === "crashed")) return "failed";
  if (!c.latest) return "pending";
  // "unknown" means the run finished but did not record every input: done, flagged separately.
  return c.freshness.value === "unsynced" || c.freshness.value === "upstream_unsynced" ? "stale" : "done";
}

function Stages({ stages }: { stages: StageCard[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title="Stages" id="stages-h" actions={<Link to="/agents" className="text-[12px]">All agents →</Link>}>
      <ol className="m-0 grid list-none gap-3 p-4 sm:grid-cols-2 2xl:grid-cols-4">
        {stages.map((c) => {
          const run = c.newest ?? c.latest;
          const p = phase(c);
          const expanded = open === c.stage;
          return (
            <li key={c.stage} className="flex min-w-0 flex-col rounded-lg border bg-surface-2 p-3.5"
              style={{ borderColor: p === "failed" ? "var(--color-red)" : p === "running" ? "var(--color-blue)" : "var(--color-border)" }}>
              <div className="mb-2 flex items-center gap-2.5">
                <span className={`phase-circle ${p === "pending" ? "pending" : p === "failed" ? "failed" : p === "running" ? "running" : ""}`} aria-hidden>{c.n}</span>
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-bold">{c.title}</div>
                  <div className="mono truncate text-[11px] text-fg-3">{c.agent}</div>
                </div>
              </div>
              <div className="mb-2 flex flex-wrap gap-1.5">
                <StateBadge state={run?.state} basis={run?.state_basis} />
                {c.latest && <FreshnessBadge value={c.freshness.value} />}
                {c.worst_finding && (
                  <Link to="/findings" search={{ stage: c.stage }} className="no-underline" title={`Worst open finding for this stage: ${c.worst_finding.severity}`}>
                    <SeverityBadge sev={c.worst_finding.severity} count={c.worst_finding.count} />
                  </Link>
                )}
              </div>
              {run?.progress && run.state === "running" && (
                <div className="mb-2">
                  <div className="progress-bar"><div className="progress-bar-fill" style={{ width: `${Math.round((run.progress.done / Math.max(1, run.progress.total)) * 100)}%`, background: "var(--color-blue)" }} /></div>
                  <div className="mt-1 text-[11px] text-fg-3">{run.progress.done}/{run.progress.total} {run.progress.unit}{run.current_item ? ` · ${run.current_item.id}` : ""}</div>
                </div>
              )}
              <ul className="m-0 mb-2 list-none p-0 text-[12px] text-fg-2">
                {c.key_stat.slice(0, 2).map((k) => <li key={k} className="truncate" title={k}>{k}</li>)}
                {!c.key_stat.length && <li className="text-fg-3">{c.latest ? "No summary recorded" : "Not run yet"}</li>}
              </ul>
              <div className="mt-auto flex items-center gap-2 text-[11px] text-fg-3">
                <span>{run ? `${fmtDuration(run.duration_ms)} · ${fmtAgo(run.finished_at ?? run.started_at ?? run.generated_at)}` : "—"}</span>
                <button type="button" className="btn ml-auto !px-2 !py-0.5 !text-[11px]" aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : c.stage)}>{expanded ? "Less" : "Details"}</button>
              </div>
              {expanded && (
                <div className="mt-2.5 border-t border-line pt-2.5 text-[12px]">
                  <p className="m-0 mb-2 leading-relaxed text-fg-2">{c.purpose}</p>
                  {c.key_stat.slice(2).map((k) => <div key={k} className="text-fg-2">{k}</div>)}
                  {c.freshness.causes.map((x, i) => <div key={i} className="mt-1" style={{ color: "var(--color-accent-text)" }}>{x.text}</div>)}
                  {run?.error && <div className="callout-fail mt-2"><b>{run.error.class}</b> {run.error.message}</div>}
                  <div className="mt-2 text-fg-3">{c.run_count} run{c.run_count === 1 ? "" : "s"}{c.attempt_count ? ` · ${c.attempt_count} failed attempt(s)` : ""}</div>
                  {run && <Link to={runPath(c.stage, run.id)} className="mt-1.5 inline-block">Open run <span className="mono">{run.run_version ?? run.id}</span> →</Link>}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

function Attention({ items, counts }: { items: Finding[]; counts: Status["finding_counts"] }) {
  const order = ["critical", "high", "medium", "low"] as const;
  return (
    <Panel title="Needs attention" id="attention-h" actions={
      <>{order.filter((k) => counts[k]).map((k) => <span key={k} className="text-[11px] text-fg-3">{counts[k]} {k}</span>)}
        <Link to="/findings" className="text-[12px]">All findings →</Link></>}>
      {items.length ? (
        <ul className="m-0 list-none p-0">
          {items.map((f) => (
            <li key={f.id} className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-b-0">
              <SeverityBadge sev={f.severity} />
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-semibold">{f.title}</div>
                {f.detail && <div className="mt-0.5 text-[12px] leading-relaxed text-fg-3">{f.detail}</div>}
                {f.next_step && <div className="mt-1 text-[12px]" style={{ color: "var(--color-accent-text)" }}>→ {f.next_step}</div>}
              </div>
              {f.stage && <span className="mono shrink-0 text-[11px] text-fg-3">{f.stage}</span>}
            </li>
          ))}
        </ul>
      ) : <Empty title="Nothing needs attention">Every stage is current and no open matter is critical or high.</Empty>}
    </Panel>
  );
}

function QualityGate({ s }: { s: Status }) {
  const k = s.kpis;
  const checks: [string, boolean, string][] = [
    ["All stages current", k.stages_done === k.stages_total, `${k.stages_done}/${k.stages_total}`],
    ["Latest run consistent", s.pipeline_run?.consistency === "consistent", s.pipeline_run?.consistency ?? "no run"],
    ["No critical findings", !s.finding_counts.critical, `${s.finding_counts.critical ?? 0} critical`],
    ["Source reachable", s.corpus.source_reachable, s.corpus.source_reachable ? "yes" : "recorded path missing"],
    ["Annotations clean", !s.annotations.problems && !s.annotations.error, s.annotations.present ? `${s.annotations.applied} applied` : "none"],
  ];
  const passed = checks.filter((c) => c[1]).length;
  const verdict = passed === checks.length ? ["PASS", "var(--color-green)"] : passed >= checks.length - 2 ? ["REVIEW", "var(--color-accent-text)"] : ["ATTENTION", "var(--color-red)"];
  return (
    <Panel title="Quality gate" id="gate-h" actions={<Link to="/testing" className="text-[12px]">Synthetic testing →</Link>}>
      <div className="flex items-center gap-4 px-4 pt-4">
        <div className="text-[26px] font-extrabold tracking-wide" style={{ color: verdict[1] }}>{verdict[0]}</div>
        <div className="text-[12px] text-fg-3">{passed} of {checks.length} checks pass.<br />Derived from the output directory, not an LLM judgement.</div>
      </div>
      <ul className="m-0 list-none px-4 py-3">
        {checks.map(([name, ok, detail]) => (
          <li key={name} className="flex items-center gap-2 py-1 text-[12.5px]">
            <span style={{ color: ok ? "var(--color-green)" : "var(--color-orange)" }}><Icon name={ok ? "check" : "warn"} /></span>
            <span>{name}</span><span className="ml-auto text-fg-3">{detail}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function LatestRun({ s }: { s: Status }) {
  const p = s.pipeline_run;
  return (
    <Panel title="Latest pipeline run" id="prun-h" actions={<Link to="/runs" className="text-[12px]">All runs →</Link>}>
      {p ? (
        <div className="p-4 text-[12.5px]">
          <Link to="/runs/$pid" params={{ pid: p.id }} className="mono break-all font-semibold">{p.id}</Link>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className={`badge ${p.consistency === "consistent" ? "tone-ok" : p.consistency === "inconsistent" ? "tone-fail" : "tone-warn"}`}><span className="dot" />{p.consistency}</span>
            <span className={`badge ${p.is_current ? "tone-gold" : "tone-stale"}`}><span className="dot" />{p.is_current ? "latest BRD" : "latest BRD · inputs superseded"}</span>
            {p.inferred_members.length > 0 && <span className="badge tone-unknown" title={p.inferred_members.join(", ")}><span className="dot" />{p.inferred_members.length} member(s) inferred</span>}
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1">
            <dt className="text-fg-3">Finished</dt><dd className="m-0">{fmtTime(p.finished_at)}</dd>
            <dt className="text-fg-3">Span</dt><dd className="m-0">{fmtDuration(p.span_ms)}</dd>
            <dt className="text-fg-3">Diagrams</dt><dd className="m-0">{p.diagrams}</dd>
            <dt className="text-fg-3">Rules to review</dt><dd className="m-0">{p.rules_need_review ?? "—"}</dd>
          </dl>
          {p.deliverables.length > 0 && (
            <div className="mt-3">
              <div className="label mb-1">Deliverables</div>
              {p.deliverables.map((d) => (
                <Link key={d.artifact_id} to={runPath(d.stage, d.run_version)} search={{ tab: "outputs", artifact: d.artifact_id }} className="block truncate">{d.label}</Link>
              ))}
            </div>
          )}
        </div>
      ) : <Empty title="No pipeline run yet">A pipeline run is anchored on a 07_synthesis run.</Empty>}
    </Panel>
  );
}

function NextSteps({ s }: { s: Status }) {
  const n = s.next_steps;
  return (
    <Panel title="Next steps" id="next-h">
      <div className="p-4 text-[12.5px]">
        <p className="m-0 mb-2 leading-relaxed">{n.summary}</p>
        {n.stages.map((x) => <div key={x.stage} className="text-fg-3"><span className="mono text-fg-2">{x.stage}</span> — {x.reason}</div>)}
        {n.commands.length > 0 && (
          <div className="mt-3 flex flex-col gap-1.5">
            {n.commands.map((c) => (
              <div key={c} className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-1.5">
                <code className="mono min-w-0 flex-1 truncate text-[11.5px]" title={c}>{c}</code><CopyButton text={c} />
              </div>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

function Activity({ s }: { s: Status }) {
  return (
    <Panel title="Recent activity" id="recent-h" actions={<Link to="/timeline" className="text-[12px]">Timeline →</Link>}>
      {s.recent.length ? (
        <ul className="m-0 list-none p-0">
          {s.recent.slice(0, 8).map((r) => (
            <li key={`${r.stage}/${r.id}`} className="flex items-center gap-2 border-b border-line px-4 py-2 text-[12px] last:border-b-0">
              <StateBadge state={r.state} basis={r.state_basis} />
              <Link to={runPath(r.stage, r.id)} className="min-w-0 truncate">{stageName(r.stage)}</Link>
              <span className="ml-auto shrink-0 text-fg-3">{fmtAgo(r.finished_at ?? r.started_at)}</span>
            </li>
          ))}
        </ul>
      ) : <Empty title="No runs recorded" />}
    </Panel>
  );
}
