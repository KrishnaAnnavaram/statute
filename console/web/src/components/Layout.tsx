import { lazy, Suspense, useEffect, useState } from "react";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { api, runPath, type StageCard, type Status } from "../api";
import { useStatus } from "../queries";
import { fmtBytes, fmtDuration, stageName } from "../lib/format";
import { Icon } from "./ui";

const BrdModal = lazy(() => import("./BrdModal"));

export const TABS: { to: string; label: string; match?: RegExp }[] = [
  { to: "/", label: "Pipeline" },
  { to: "/agents", label: "Agents", match: /^\/(agents|stages)$/ },
  { to: "/artifacts", label: "Artifacts" },
  { to: "/trace", label: "Statement Trace" },
  { to: "/testing", label: "Synthetic Testing" },
  { to: "/workflow", label: "Interactive Workflow" },
  { to: "/diagrams", label: "Diagrams" },
  { to: "/timeline", label: "Timeline" },
  { to: "/rules", label: "Rules" },
  { to: "/data", label: "Data Model" },
  { to: "/findings", label: "Findings" },
  { to: "/evidence", label: "Evidence", match: /^\/evidence/ },
  { to: "/runs", label: "Runs", match: /^\/(runs|compare|stages\/[^/]+\/runs)/ },
  { to: "/events", label: "Events" },
  { to: "/health", label: "Health" },
  { to: "/state", label: "State" },
];

const isNarrow = () => typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches === true;

type Theme = "dark" | "light";
function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try { return (localStorage.getItem("statute-theme") as Theme) || "dark"; } catch { return "dark"; }
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("statute-theme", theme); } catch { /* storage unavailable */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

export function Layout() {
  const { data: s, error, dataUpdatedAt, isError } = useStatus();
  const [theme, toggleTheme] = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    if (isNarrow()) return false;   // on phones the sidebar is an overlay, opened on demand
    try { return localStorage.getItem("statute-sidebar") !== "closed"; } catch { return true; }
  });
  const [showBrd, setShowBrd] = useState(false);
  const path = useRouterState({ select: (r) => r.location.pathname });
  useEffect(() => {
    if (isNarrow()) return;
    try { localStorage.setItem("statute-sidebar", sidebarOpen ? "open" : "closed"); } catch { /* ignore */ }
  }, [sidebarOpen]);
  useEffect(() => { if (isNarrow()) setSidebarOpen(false); }, [path]);
  // 16 sections overflow narrower screens: keep the active one visible in the scrolling tab bar.
  useEffect(() => { document.querySelector('nav[aria-label="Dashboard sections"] [aria-current="page"]')?.scrollIntoView({ block: "nearest", inline: "nearest" }); }, [path]);

  const exportJson = async () => {
    const data = await api<Status>("/status");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `statute-status-${new Date().toISOString().slice(0, 19).replace(/:/g, "")}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  const isActive = (t: (typeof TABS)[number]) => (t.match ? t.match.test(path) : t.to === "/" ? path === "/" : path === t.to);
  const running = s?.running ?? [];
  const ws = s?.workspace;
  const updated = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : null;

  return (
    <div className="flex h-full overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
      {showBrd && <Suspense fallback={null}><BrdModal onClose={() => setShowBrd(false)} /></Suspense>}
      <Sidebar stages={s?.stages ?? []} open={sidebarOpen} onToggle={() => setSidebarOpen((o) => !o)} path={path} />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="shrink-0 border-b border-line bg-surface px-4 pt-4 md:px-6">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="m-0 text-[20px] font-bold text-fg">PL/SQL Reverse Engineering</h1>
              <div className="mt-0.5 text-[11px] text-fg-3" aria-live="polite">
                {isError ? <span style={{ color: "var(--color-red)" }}>API unreachable — showing data from {updated ?? "—"}</span>
                  : <>Live · updated {updated ?? "…"} · polling every 2 s</>}
              </div>
            </div>
            <div className="header-actions flex flex-wrap items-center gap-2">
              {isError ? (
                <span className="badge tone-fail"><span className="dot" />offline</span>
              ) : running.length ? (
                <span className="badge tone-run" role="status"><Icon name="ring" size={11} />live · {running.join(", ")} running</span>
              ) : (
                <span className="badge tone-ok"><span className="dot live-dot" />live · idle</span>
              )}
              <button type="button" className="btn" onClick={toggleTheme}>{theme === "dark" ? "Light theme" : "Dark theme"}</button>
              <button type="button" className="btn" onClick={() => setShowBrd(true)} disabled={!ws?.brd_name}>View BRD</button>
              <button type="button" className="btn" onClick={exportJson}>Export JSON</button>
              <button type="button" className="btn btn-gold" onClick={() => window.print()}>Export PDF</button>
            </div>
          </div>

          <div className="mb-3.5 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              ["Project directory", ws?.project ?? "—"],
              ["Source directory", s?.corpus.source_display ?? ws?.source_dir ?? "—"],
              ["Output directory", ws?.output_dir ?? "—"],
              ["BRD name", ws?.brd_name ? `${ws.brd_name} · ${ws.system ?? ""}` : "not synthesised yet"],
            ].map(([label, val]) => (
              <div key={label} className="min-w-0">
                <div className="label mb-0.5">{label}</div>
                <div className="truncate text-[12px] text-fg" title={val}>{val}</div>
              </div>
            ))}
          </div>

          {s && <StatsRow s={s} />}
          {error && !s && <div className="callout-fail mb-3">{String(error)}</div>}

          <nav aria-label="Dashboard sections" className="tab-bar mt-3">
            {TABS.map((t) => (
              <Link key={t.to} to={t.to} className="tab-btn" aria-current={isActive(t) ? "page" : undefined}>{t.label}</Link>
            ))}
          </nav>
        </header>

        <main id="main" tabIndex={-1} className="main-scroll min-h-0 flex-1 overflow-auto p-6">
          <Suspense fallback={<div className="py-10 text-center text-fg-3" role="status">Loading…</div>}><Outlet /></Suspense>
        </main>
      </div>
    </div>
  );
}

function StatsRow({ s }: { s: Status }) {
  const k = s.kpis;
  const tiles: [string, string, string][] = [
    ["Overall", `${k.overall_pct}%`, `${k.stages_done}/${k.stages_total} stages current`],
    ["Objects", fmtN(k.objects), `${fmtN(k.statements)} statements parsed`],
    ["Tables", fmtN(k.tables), `${fmtN(k.columns)} columns in dictionary`],
    ["Rules", fmtN(k.rules), `${fmtN(k.sme)} need SME review`],
    ["Requirements", fmtN(k.requirements), "in the BRD"],
    ["Open matters", fmtN(k.gaps), `${k.gaps_high} critical or high`],
    ["Artifacts", fmtN(k.artifacts), `${fmtBytes(k.artifact_bytes)} produced`],
    ["Build time", k.span_ms ? fmtDuration(k.span_ms) : "—", `${fmtN(k.files)} files · ${fmtN(k.code_lines)} code lines`],
  ];
  return (
    <div className="mb-1 grid grid-cols-2 gap-2.5 md:grid-cols-4 2xl:grid-cols-8">
      {tiles.map(([label, value, sub]) => (
        <div key={label} className="kpi-tile">
          <div className="kpi-label">{label}</div>
          <div className="kpi-value">{value}</div>
          <div className="kpi-sub" title={sub}>{sub}</div>
        </div>
      ))}
    </div>
  );
}
const fmtN = (n: number | null | undefined) => (n === null || n === undefined ? "—" : n.toLocaleString());

function phaseStatus(st: StageCard): { label: string; tone: string; circle: string; fill: string; pct: number } {
  const newest = st.newest, latest = st.latest;
  if (newest?.state === "running") {
    const p = newest.progress;
    return { label: "running", tone: "tone-run", circle: "running", fill: "var(--color-blue)", pct: p?.total ? (p.done / p.total) * 100 : 8 };
  }
  if (newest && newest.id !== latest?.id && (newest.state === "failed" || newest.state === "crashed"))
    return { label: newest.state, tone: "tone-fail", circle: "failed", fill: "var(--color-red)", pct: 100 };
  if (!latest) return { label: "pending", tone: "tone-muted", circle: "pending", fill: "var(--color-border)", pct: 0 };
  const f = st.freshness.value;
  if (f === "unsynced" || f === "upstream_unsynced") return { label: "stale", tone: "tone-stale", circle: "", fill: "var(--color-amber)", pct: 100 };
  return { label: "done", tone: "tone-ok", circle: "", fill: "var(--color-green)", pct: 100 };
}

function Sidebar({ stages, open, onToggle, path }: { stages: StageCard[]; open: boolean; onToggle: () => void; path: string }) {
  return (
    <aside className={`sidebar no-print${open ? "" : " collapsed"}`} aria-label="Pipeline stages">
      {open ? (
        <div className="flex items-center gap-2.5 border-b border-line px-3.5 pb-3 pt-4">
          <div className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-lg text-[11px] font-extrabold tracking-tight"
            style={{ background: "var(--color-accent)", color: "#111" }} aria-hidden>P→B</div>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-bold">PL/SQL → BRD</div>
            <div className="text-[11px] text-fg-3">STATUTE pipeline dashboard</div>
          </div>
          <button type="button" onClick={onToggle} className="rounded p-1 text-fg-3 hover:text-fg" aria-label="Collapse sidebar" title="Collapse sidebar"><Icon name="chev-l" size={16} /></button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2 border-b border-line py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md text-[9.5px] font-extrabold" style={{ background: "var(--color-accent)", color: "#111" }} aria-hidden>P→B</div>
          <button type="button" onClick={onToggle} className="rounded p-1 text-fg-3 hover:text-fg" aria-label="Expand sidebar" title="Expand sidebar"><Icon name="chev-r" size={16} /></button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto py-3">
        {open && <div className="label px-3.5 pb-2.5 pt-1">Pipeline · {stages.length} stages</div>}
        {stages.map((st) => {
          const ps = phaseStatus(st);
          const run = st.newest?.state === "running" || (st.newest && st.newest.id !== st.latest?.id) ? st.newest : st.latest;
          const to = run ? runPath(st.stage, run.id) : "/agents";
          const current = run ? path === `/stages/${st.stage}/runs/${encodeURIComponent(run.id)}` || path === `/stages/${st.stage}/runs/${run.id}` : false;
          return (
            <Link key={st.stage} to={to} className="phase-row" aria-current={current ? "page" : undefined}
              title={`${st.n}. ${st.title} — ${ps.label}`} aria-label={`Stage ${st.n}, ${st.title}: ${ps.label}`} style={open ? undefined : { padding: "8px 15px" }}>
              <div className={`phase-circle ${ps.circle}`}>{st.n}</div>
              {open && (
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-1.5">
                    <span className="truncate text-[13px] font-medium text-fg capitalize">{stageName(st.stage)}</span>
                    <span className={`badge ${ps.tone}`}>{ps.label === "running" ? <Icon name="ring" size={10} /> : <span className="dot" />}{ps.label}</span>
                  </div>
                  <div className="mono mt-px truncate text-[10px] text-fg-3">{st.agent}</div>
                  <div className="progress-bar mt-1.5" aria-hidden><div className="progress-bar-fill" style={{ width: `${ps.pct}%`, background: ps.fill }} /></div>
                </div>
              )}
            </Link>
          );
        })}
      </div>
      {open && (
        <div className="border-t border-line px-3.5 py-2.5 text-[11px] leading-relaxed text-fg-3">
          Read-only · local · files are the source of truth
        </div>
      )}
    </aside>
  );
}
