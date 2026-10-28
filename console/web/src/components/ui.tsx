import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { Freshness, RunState, Severity } from "../api";
import { middleTruncate } from "../lib/format";

/* ---------------------------------------------------------------- icons -- */
type IconName = "check" | "x" | "ring" | "warn" | "clock" | "pin" | "dash" | "q" | "half" | "info" | "copy" | "arrow" | "dot" | "ext" | "chev-l" | "chev-r";
export function Icon({ name, size = 13, className }: { name: IconName; size?: number; className?: string }) {
  const p = { width: size, height: size, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.8,
    strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, className };
  switch (name) {
    case "check": return <svg {...p}><path d="M3.5 8.4l3 3 6-6.6" /></svg>;
    case "x": return <svg {...p}><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" /></svg>;
    case "ring": return <svg {...p}><circle cx="8" cy="8" r="6" strokeOpacity=".3" /><path className="spin" d="M8 2a6 6 0 0 1 6 6" /></svg>;
    case "warn": return <svg {...p}><path d="M8 1.8l6.6 11.6H1.4z" /><path d="M8 6.2v3.4M8 11.6v.1" /></svg>;
    case "clock": return <svg {...p}><circle cx="8" cy="8" r="6.2" /><path d="M8 4.5V8l2.4 1.6" /></svg>;
    case "pin": return <svg {...p}><path d="M6 2h4l-.6 4 2.6 2.4H4L6.6 6zM8 8.4V14" /></svg>;
    case "dash": return <svg {...p}><path d="M4 8h8" /></svg>;
    case "q": return <svg {...p}><circle cx="8" cy="8" r="6.2" /><path d="M6.2 6.2a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.3M8 11.6v.1" /></svg>;
    case "half": return <svg {...p}><circle cx="8" cy="8" r="6.2" /><path d="M8 1.8v12.4A6.2 6.2 0 0 0 8 1.8z" fill="currentColor" /></svg>;
    case "info": return <svg {...p}><circle cx="8" cy="8" r="6.2" /><path d="M8 7.2v4M8 4.8v.1" /></svg>;
    case "copy": return <svg {...p}><rect x="5" y="5" width="8.5" height="8.5" rx="1.5" /><path d="M10.5 5V3.5A1.5 1.5 0 0 0 9 2H3.5A1.5 1.5 0 0 0 2 3.5V9A1.5 1.5 0 0 0 3.5 10.5H5" /></svg>;
    case "arrow": return <svg {...p}><path d="M3 8h10M9 4l4 4-4 4" /></svg>;
    case "dot": return <svg {...p}><circle cx="8" cy="8" r="3" fill="currentColor" /></svg>;
    case "ext": return <svg {...p}><path d="M9 3h4v4M13 3L7.5 8.5M11 9.5V13H3V5h3.5" /></svg>;
    case "chev-l": return <svg {...p}><path d="M10 3.5L5.5 8l4.5 4.5" /></svg>;
    case "chev-r": return <svg {...p}><path d="M6 3.5L10.5 8 6 12.5" /></svg>;
  }
}

const Dot = () => <span className="dot" aria-hidden />;

/* --------------------------------------------------------------- badges -- */
const STATE: Record<RunState, { tone: string; label: string }> = {
  running: { tone: "tone-run", label: "running" },
  succeeded: { tone: "tone-ok", label: "done" },
  failed: { tone: "tone-fail", label: "failed" },
  crashed: { tone: "tone-fail", label: "crashed" },
};
export function StateBadge({ state, basis, title }: { state: RunState | null | undefined; basis?: string; title?: string }) {
  if (!state) return <span className="badge tone-muted"><Dot />never run</span>;
  const s = STATE[state];
  const inferred = basis === "inferred";
  return (
    <span className={`badge ${s.tone}`} title={title ?? (inferred ? "Inferred from the run directory — no recorded outcome" : undefined)}>
      {state === "running" ? <Icon name="ring" size={11} /> : <Dot />}{s.label}{inferred ? "?" : ""}
    </span>
  );
}

const FRESH: Record<Freshness, { tone: string; label: string; help: string }> = {
  current: { tone: "tone-ok", label: "current", help: "Built from the latest run of every input" },
  unsynced: { tone: "tone-stale", label: "out of date", help: "A newer run of an input exists" },
  upstream_unsynced: { tone: "tone-stale", label: "upstream out of date", help: "An input is itself out of date" },
  pinned: { tone: "tone-muted", label: "pinned", help: "Deliberately built from a pinned, older input" },
  unknown: { tone: "tone-unknown", label: "provenance unrecorded", help: "This run does not record every input it consumed" },
  never_run: { tone: "tone-muted", label: "never run", help: "No run of this stage exists" },
};
export function FreshnessBadge({ value, title }: { value: Freshness | null | undefined; title?: string }) {
  if (!value) return null;
  const f = FRESH[value];
  return <span className={`badge ${f.tone}`} title={title ?? f.help}><Dot />{f.label}</span>;
}

const SEV_TONE: Record<Severity, string> = { critical: "tone-fail", high: "tone-degrade", medium: "tone-warn", low: "tone-run", info: "tone-muted" };
export function SeverityBadge({ sev, compact, count }: { sev: Severity; compact?: boolean; count?: number }) {
  const label = sev.charAt(0).toUpperCase() + sev.slice(1);
  return (
    <span className={`badge ${SEV_TONE[sev] ?? "tone-muted"}`}>
      <Dot />{compact ? <span className="sr-only">{label}</span> : count !== undefined ? `${count} ${sev}` : label}
    </span>
  );
}

export function Pill({ children, tone = "tone-muted", title }: { children: ReactNode; tone?: string; title?: string }) {
  return <span className={`badge ${tone}`} title={title}>{children}</span>;
}

/* --------------------------------------------------------------- layout -- */
export function Panel({ title, actions, children, className = "", id }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section className={`panel ${className}`} aria-labelledby={title ? id : undefined}>
      {title !== undefined && (
        <div className="panel-h"><h2 id={id}>{title}</h2><div className="ml-auto flex items-center gap-2">{actions}</div></div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, children, eyebrow }: { title: ReactNode; subtitle?: ReactNode; children?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="mb-4 flex flex-wrap items-end gap-3">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1 text-[12px] text-fg-3">{eyebrow}</div>}
        <h2 className="page-title">{title}</h2>
        {subtitle && <div className="page-sub">{subtitle}</div>}
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">{children}</div>
    </header>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: ReactNode; count?: number }[]; value: T; onChange: (t: T) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div role="tablist" aria-label={label} className="tab-bar px-2">
      {tabs.map((t, i) => (
        <button key={t.id} ref={(el) => { refs.current[i] = el; }} role="tab" aria-selected={value === t.id}
          tabIndex={value === t.id ? 0 : -1} className="tab-btn" onClick={() => onChange(t.id)}
          onKeyDown={(e) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            const n = (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
            onChange(tabs[n].id); refs.current[n]?.focus();
          }}>
          {t.label}{t.count !== undefined && <span className="mono ml-1.5 text-fg-3">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function KeyValues({ items, cols = 2 }: { items: [string, ReactNode][]; cols?: number }) {
  return (
    <dl className="grid gap-x-6 gap-y-1.5 text-[13px]" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, max-content) minmax(0, 1fr))` }}>
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="whitespace-nowrap text-fg-3">{k}</dt>
          <dd className="m-0 min-w-0 break-words text-fg">{v === null || v === undefined || v === "" ? <span className="text-fg-3">—</span> : v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Mono({ children, max, title }: { children: string; max?: number; title?: string }) {
  return <span className="mono" title={title ?? (max && children.length > max ? children : undefined)}>{max ? middleTruncate(children, max) : children}</span>;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" aria-label={`${label}: ${text}`} title={label} className="btn !px-2 !py-0.5"
      onClick={() => { navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1200); }); }}>
      <Icon name={done ? "check" : "copy"} size={12} />{done ? "Copied" : label}
    </button>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-4 py-10 text-center">
      <div className="font-semibold text-fg-2">{title}</div>
      {children && <div className="mx-auto mt-1.5 max-w-xl text-[13px] leading-relaxed text-fg-3">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return <div role="alert" className="callout-fail"><b style={{ color: "var(--color-red)" }}>The console API did not answer.</b> {msg}</div>;
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-fg-3" role="status" aria-live="polite">
      <span className="spin inline-block h-8 w-8 rounded-full border-[3px]" style={{ borderColor: "var(--color-border)", borderTopColor: "var(--color-accent)" }} />
      <span className="text-[13px]">{what}…</span>
    </div>
  );
}

/* ----------------------------------------------------------- data table -- */
export interface Column<R> { key: string; header: ReactNode; render?: (r: R) => ReactNode; sort?: (r: R) => string | number; num?: boolean; width?: string }
export function DataTable<R>({ rows, columns, rowKey, empty = "Nothing to show", initialSort, onRowClick, caption }: {
  rows: R[]; columns: Column<R>[]; rowKey: (r: R) => string; empty?: ReactNode;
  initialSort?: { key: string; dir: 1 | -1 }; onRowClick?: (r: R) => void; caption?: string;
}) {
  const [sort, setSort] = useState(initialSort);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const c = columns.find((x) => x.key === sort.key);
    if (!c?.sort) return rows;
    const get = c.sort;
    return [...rows].sort((a, b) => {
      const x = get(a), y = get(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [rows, columns, sort]);
  if (!rows.length) return <Empty title={typeof empty === "string" ? empty : "Nothing to show"}>{typeof empty === "string" ? null : empty}</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="dt">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              return (
                <th key={c.key} className={c.num ? "num" : ""} style={{ width: c.width }}
                  aria-sort={active ? (sort!.dir === 1 ? "ascending" : "descending") : undefined}>
                  {c.sort ? (
                    <button type="button" className="inline-flex items-center gap-1 uppercase hover:text-fg"
                      onClick={() => setSort({ key: c.key, dir: active && sort!.dir === 1 ? -1 : 1 })}>
                      {c.header}<span aria-hidden className="text-fg-3">{active ? (sort!.dir === 1 ? "▲" : "▼") : "↕"}</span>
                    </button>
                  ) : c.header}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={rowKey(r)} onClick={onRowClick ? () => onRowClick(r) : undefined} className={onRowClick ? "cursor-pointer" : ""}>
              {columns.map((c) => <td key={c.key} className={c.num ? "num" : ""}>{c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "—")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* --------------------------------------------------------------- drawer -- */
export function Drawer({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0" style={{ background: "rgba(0,0,0,0.7)" }} onClick={onClose} aria-hidden />
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={id}
        className={`relative flex h-full w-full ${wide ? "max-w-[min(1240px,94vw)]" : "max-w-[720px]"} flex-col border-l border-line bg-surface shadow-2xl outline-none`}>
        <div className="flex items-center gap-2 border-b border-line px-5 py-3">
          <h2 id={id} className="m-0 min-w-0 truncate text-[15px] font-bold">{title}</h2>
          <button type="button" onClick={onClose} className="btn btn-gold ml-auto" aria-label="Close panel">Close</button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-5">{children}</div>
      </div>
    </div>
  );
}

export function Code({ text, maxHeight = 480 }: { text: string; maxHeight?: number }) {
  return <pre tabIndex={0} className="mono m-0 overflow-auto whitespace-pre rounded-lg border border-line bg-surface p-4 text-[11.5px] leading-[1.6]" style={{ maxHeight }}>{text}</pre>;
}

/* ----------------------------------------------------------- bar meters -- */
export function Meter({ label, value, total, color, hint }: { label: ReactNode; value: number; total: number; color?: string; hint?: string }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  const id = useId();
  return (
    <div className="mb-2.5">
      <div className="mb-1 flex justify-between text-[12px]">
        <span id={id} style={{ color: color ?? "var(--color-text)" }}>{label}</span>
        <span className="text-fg-3" title={hint}>{value} · {pct}%</span>
      </div>
      <div className="progress-bar" role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={total} aria-labelledby={id}>
        <div className="progress-bar-fill" style={{ width: `${pct}%`, background: color ?? "var(--color-blue)" }} />
      </div>
    </div>
  );
}
