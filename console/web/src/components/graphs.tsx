import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { runPath, type PipelineDetail } from "../api";
import { fmtDuration, fmtClock, stageName, stageNo } from "../lib/format";

/* Fixed layered layout: STATUTE's stage DAG is small and fixed, so a layout engine
   (dagre/ELK) would add weight without adding clarity. Column = longest-path depth. */
const POS: Record<string, [number, number]> = {
  "01_inventory": [0, 0], "02_parser": [1, 0], "03_data": [2, 0], "04_logic": [2, 1],
  "05_rules": [3, 0], "06_diagram": [4, 0], "07_synthesis": [5, 0], "08_graph": [6, 0],
};
const W = 134, H = 62, GX = 30, GY = 30, PAD = 12;

const STATE_TONE: Record<string, string> = { succeeded: "var(--ok)", failed: "var(--fail)", crashed: "var(--fail)", running: "var(--run)" };

export function LineageGraph({ lineage, onSelect, selected }: { lineage: PipelineDetail["lineage"]; onSelect?: (stage: string) => void; selected?: string | null }) {
  const navigate = useNavigate();
  const [focus, setFocus] = useState<string | null>(null);
  const xy = (k: string) => { const [c, r] = POS[k]; return [PAD + c * (W + GX), PAD + r * (H + GY)] as const; };
  const width = PAD * 2 + 7 * W + 6 * GX, height = PAD * 2 + 2 * H + GY;
  const recorded = lineage.edges.filter((e) => e.resolved !== "unrecorded" && e.run_version);
  return (
    <figure className="m-0">
      <div className="overflow-x-auto">
        <svg role="group" aria-label="Lineage of this pipeline run: each stage run and the exact upstream runs it consumed"
          width="100%" viewBox={`0 0 ${width} ${height}`} className="block min-w-[880px]" style={{ maxWidth: width }}>
          <defs>
            <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0L8 4L0 8z" fill="var(--border-strong)" />
            </marker>
            <marker id="arr-hi" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0L8 4L0 8z" fill="var(--accent)" />
            </marker>
          </defs>
          {recorded.map((e, i) => {
            const [x1, y1] = xy(e.from), [x2, y2] = xy(e.to);
            const sx = x1 + W, sy = y1 + H / 2, tx = x2, ty = y2 + H / 2;
            const hi = focus === e.to || focus === e.from;
            const mismatch = e.matches_member === false;
            const mid = (sx + tx) / 2;
            return (
              <g key={i} opacity={focus && !hi ? 0.18 : 1}>
                <path d={`M${sx} ${sy} C${mid} ${sy} ${mid} ${ty} ${tx} ${ty}`} fill="none"
                  stroke={mismatch ? "var(--fail)" : hi ? "var(--accent)" : "var(--border-strong)"}
                  strokeWidth={hi || mismatch ? 1.8 : 1.1} strokeDasharray={mismatch ? "5 3" : e.resolved === "pinned" ? "2 3" : undefined}
                  markerEnd={`url(#${hi ? "arr-hi" : "arr"})`} />
                {mismatch && <text x={mid} y={(sy + ty) / 2 - 4} textAnchor="middle" fontSize="10" fill="var(--fail)">different run</text>}
              </g>
            );
          })}
          {lineage.nodes.map((n) => {
            const [x, y] = xy(n.stage);
            const tone = n.state ? STATE_TONE[n.state] : "var(--muted)";
            const label = `${n.stage} run ${n.run_version ?? "none"}, ${n.state ?? "no run"}${n.inferred ? ", membership inferred" : ""}`;
            return (
              <g key={n.stage} role="link" tabIndex={n.run_version ? 0 : -1} aria-label={label}
                style={{ cursor: n.run_version ? "pointer" : "default", outline: "none" }}
                onMouseEnter={() => setFocus(n.stage)} onMouseLeave={() => setFocus(null)}
                onFocus={() => setFocus(n.stage)} onBlur={() => setFocus(null)}
                onClick={() => { if (onSelect) onSelect(n.stage); else if (n.run_version) navigate({ to: runPath(n.stage, n.run_version) }); }}
                onKeyDown={(e) => { if (e.key !== "Enter") return; if (onSelect) onSelect(n.stage); else if (n.run_version) navigate({ to: runPath(n.stage, n.run_version) }); }}>
                <rect x={x} y={y} width={W} height={H} rx="5" fill="var(--surface)"
                  stroke={focus === n.stage || selected === n.stage ? "var(--accent)" : "var(--border-strong)"} strokeWidth={focus === n.stage || selected === n.stage ? 2 : 1}
                  strokeDasharray={n.inferred ? "4 3" : undefined} />
                <rect x={x} y={y} width="4" height={H} rx="2" fill={tone} />
                <text x={x + 12} y={y + 18} fontSize="12" fontWeight="600" fill="var(--text)">{stageNo(n.stage)} {stageName(n.stage)}</text>
                <text x={x + 12} y={y + 34} fontSize="10.5" fill="var(--text-2)" fontFamily="IBM Plex Mono, monospace">
                  {n.run_version ? n.run_version.slice(5, 19).replace("T", " ") : "not in this run"}
                </text>
                <text x={x + 12} y={y + 50} fontSize="10.5" fill={n.provenance_gaps.length ? "var(--unknown)" : "var(--text-3)"}>
                  {n.inferred ? "membership inferred" : n.provenance_gaps.length ? `${n.provenance_gaps.length} input(s) unrecorded` : n.freshness === "superseded" ? "superseded" : (n.state ?? "")}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <figcaption className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-fg-3">
        <span>Hover or focus a stage to highlight the runs it consumed · Enter opens it</span>
        <span>— recorded input</span><span>- - - dashed node: membership inferred by time</span>
        <span className="text-[color:var(--fail)]">red dashed: consumed a different run than this pipeline run's member</span>
      </figcaption>
    </figure>
  );
}

export function Timeline({ t }: { t: PipelineDetail["timeline"] }) {
  if (!t.rows.length) return <div className="text-fg-3">No timing recorded for this pipeline run.</div>;
  const t0 = Date.parse(t.rows[0].start);
  const t1 = Math.max(...t.rows.map((r) => Date.parse(r.end)));
  const span = Math.max(1, t1 - t0);
  const pct = (iso: string) => ((Date.parse(iso) - t0) / span) * 100;
  const between = t.gaps.filter((g) => g.ms > 1000);
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-6 gap-y-1 text-[12.5px]">
        <span>Span <b className="mono">{fmtDuration(t.span_ms)}</b></span>
        <span>Inside stages <b className="mono">{fmtDuration(t.in_stage_ms)}</b> ({Math.round((t.in_stage_ms / Math.max(1, t.span_ms)) * 100)}%)</span>
        <span>Between invocations <b className="mono">{fmtDuration(t.between_ms)}</b> ({Math.round((t.between_ms / Math.max(1, t.span_ms)) * 100)}%)</span>
        {t.partial && <span className="text-fg-3">Some durations are partial: un-instrumented runs record only part of their time</span>}
      </div>
      <div className="relative" role="table" aria-label="Pipeline run timeline">
        <div className="mb-1 ml-[150px] flex justify-between text-[11px] text-fg-3 mono" aria-hidden>
          <span>{fmtClock(t.rows[0].start)}</span><span>{fmtClock(new Date(t1).toISOString())}</span>
        </div>
        {t.rows.map((r) => {
          const gap = between.find((g) => g.before === r.stage);
          const left = pct(r.start), width = Math.max(0.4, pct(r.end) - left);
          return (
            <div key={r.stage} role="row" className="flex h-7 items-center">
              <div role="rowheader" className="w-[150px] shrink-0 truncate pr-2 text-[12.5px]">{stageNo(r.stage)} {stageName(r.stage)}</div>
              <div role="cell" className="relative h-5 flex-1 rounded-sm bg-surface-2">
                {gap && (
                  <div className="hatched absolute top-1 h-3 rounded-sm" title={`Between invocations: ${fmtDuration(gap.ms)}`}
                    style={{ left: `${pct(gap.start)}%`, width: `${Math.max(0.3, pct(gap.end) - pct(gap.start))}%` }} />
                )}
                <div className="absolute top-0 h-5 rounded-sm"
                  title={`${r.stage} ${fmtDuration(r.duration_ms)} (${r.basis})`}
                  style={{ left: `${left}%`, width: `${width}%`, minWidth: 3,
                    background: r.state === "failed" || r.state === "crashed" ? "var(--fail)" : "var(--accent)",
                    opacity: r.basis === "recorded" ? 1 : 0.7 }} />
                <span className="mono absolute top-0 whitespace-nowrap text-[11px] leading-5 text-fg-2"
                  style={left + width > 82 ? { right: `calc(${100 - left}% + 6px)` } : { left: `calc(${left + width}% + 6px)` }}>
                  {fmtDuration(r.duration_ms)}{r.basis !== "recorded" && r.duration_ms !== null ? "*" : ""}
                </span>
              </div>
            </div>
          );
        })}
        <div className="mt-2 flex gap-4 text-[12px] text-fg-3">
          <span className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-5 rounded-sm" style={{ background: "var(--accent)" }} />inside the stage script</span>
          <span className="inline-flex items-center gap-1.5"><span className="hatched inline-block h-2.5 w-5 rounded-sm" />between invocations (agent or operator)</span>
          <span>* partial: excludes start-up and input loading</span>
        </div>
      </div>
    </div>
  );
}
