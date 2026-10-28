import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { api, runPath, type ConsoleEvent } from "../api";
import { fmtClock, fmtTime, stageName } from "../lib/format";
import { Code, Drawer, Empty, ErrorBox, Icon, PageHeader, Panel } from "../components/ui";

const MAX_BUFFER = 5000;   // never hold unlimited telemetry in the browser

export interface EventsSearch { stage?: string; type?: string; q?: string; severity?: string }

/** Follow-live tails /events with a time cursor. Pausing keeps polling into a
 *  buffer and shows how many new events are waiting; resume appends them. */
export function EventsPage({ search }: { search: EventsSearch }) {
  const navigate = useNavigate();
  const [events, setEvents] = useState<ConsoleEvent[]>([]);
  const [pending, setPending] = useState<ConsoleEvent[]>([]);
  const [follow, setFollow] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [meta, setMeta] = useState<{ uninstrumented_runs: number; truncated: boolean } | null>(null);
  const [open, setOpen] = useState<ConsoleEvent | null>(null);
  const cursor = useRef<string | null>(null);
  const seen = useRef(new Set<string>());
  const followRef = useRef(follow);
  followRef.current = follow;

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await api<{ events: ConsoleEvent[]; cursor: string | null; uninstrumented_runs: number; truncated: boolean }>("/events", { since: cursor.current ?? undefined, limit: 2000 });
        if (!alive) return;
        setError(null);
        setMeta({ uninstrumented_runs: r.uninstrumented_runs, truncated: r.truncated && !cursor.current });
        const fresh = r.events.filter((e) => !seen.current.has(e.event_id));    // de-duplicate across polls
        fresh.forEach((e) => seen.current.add(e.event_id));
        if (r.cursor) cursor.current = r.cursor;
        if (fresh.length) {
          if (followRef.current) setEvents((xs) => [...xs, ...fresh].slice(-MAX_BUFFER));
          else setPending((xs) => [...xs, ...fresh].slice(-MAX_BUFFER));
        }
      } catch (e) { if (alive) setError(e); }
    };
    tick();
    const t = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const resume = () => { setEvents((xs) => [...xs, ...pending].slice(-MAX_BUFFER)); setPending([]); setFollow(true); };
  const set = (k: keyof EventsSearch, v: string) => navigate({ to: "/events", search: { ...search, [k]: v || undefined }, replace: true });

  const shown = useMemo(() => {
    const q = (search.q ?? "").toLowerCase();
    return events.filter((e) => (!search.stage || e.stage === search.stage)
      && (!search.type || e.type.startsWith(search.type))
      && (!search.severity || e.severity === search.severity || (search.severity === "problems" && (e.severity === "error" || e.severity === "warning")))
      && (!q || JSON.stringify(e).toLowerCase().includes(q)));
  }, [events, search]);

  const exportJsonl = () => {
    const blob = new Blob([shown.map((e) => JSON.stringify(e)).join("\n") + "\n"], { type: "application/x-ndjson" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "statute-events.jsonl"; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  return (
    <div className="max-w-[1400px]">
      <PageHeader title="Events" subtitle="Structured witnesses written by instrumented stage runs (events.jsonl). run_meta.json and the artifacts remain authoritative.">
        {follow ? (
          <button type="button" onClick={() => setFollow(false)} className="badge tone-run cursor-pointer" aria-pressed="true"><Icon name="dot" />Following live — pause</button>
        ) : (
          <button type="button" onClick={resume} className="badge tone-warn cursor-pointer" aria-pressed="false">Paused · {pending.length} new — resume</button>
        )}
        <button type="button" onClick={exportJsonl} className="rounded border border-line px-2 py-1 text-[12px] hover:bg-surface-2">Export {shown.length} as JSONL</button>
      </PageHeader>
      {error ? <div className="mb-3"><ErrorBox error={error} /></div> : null}
      <Panel>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-[12.5px]">
          <label className="flex items-center gap-1.5">Stage
            <select value={search.stage ?? ""} onChange={(e) => set("stage", e.target.value)} className="rounded border border-line bg-surface px-1 py-0.5">
              <option value="">all</option>
              {["01_inventory", "02_parser", "03_data", "04_logic", "05_rules", "06_diagram", "07_synthesis", "08_graph"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select></label>
          <label className="flex items-center gap-1.5">Type
            <select value={search.type ?? ""} onChange={(e) => set("type", e.target.value)} className="rounded border border-line bg-surface px-1 py-0.5">
              <option value="">all</option><option value="stage_run.">lifecycle</option><option value="item.">items</option>
              <option value="stage_run.input">inputs</option><option value="stage_run.degraded">degraded</option><option value="pointer.">pointer</option>
            </select></label>
          <label className="flex items-center gap-1.5">Severity
            <select value={search.severity ?? ""} onChange={(e) => set("severity", e.target.value)} className="rounded border border-line bg-surface px-1 py-0.5">
              <option value="">all</option><option value="problems">warnings and errors</option><option value="error">errors</option>
            </select></label>
          <input type="search" placeholder="Search events (id, item, message…)" aria-label="Search events" value={search.q ?? ""}
            onChange={(e) => set("q", e.target.value)} className="ml-auto w-72 rounded border border-line bg-surface px-2 py-1" />
          <span className="text-fg-3">{shown.length} of {events.length}</span>
        </div>
        {meta && meta.uninstrumented_runs > 0 && (
          <div className="border-b border-line px-3 py-1.5 text-[12px] text-fg-3">
            {meta.uninstrumented_runs} run(s) predate instrumentation and have no events.{meta.truncated ? " Showing the most recent 2,000 events." : ""}
          </div>
        )}
        {events.length === 0 && !error ? (
          <Empty title="No events yet">Events appear when a stage runs with the instrumented scripts (lib_runlog.py). Runs in output/ produced earlier carry only run_meta.json.</Empty>
        ) : <EventTable events={shown} onOpen={setOpen} />}
      </Panel>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open ? `${open.type} · ${open.stage} #${open.seq}` : ""}>
        {open && (
          <>
            <div className="mb-3 text-[12.5px]">
              {open.run_id && <Link to={runPath(open.stage, open.run_id)}>Open the {open.stage} run →</Link>}
              <div className="text-fg-3">{fmtTime(open.time)}</div>
            </div>
            <Code text={JSON.stringify(open, null, 2)} />
          </>
        )}
      </Drawer>
    </div>
  );
}

const TYPE_TONE: Record<string, string> = { "stage_run.failed": "tone-fail", "item.failed": "tone-fail", "stage_run.degraded": "tone-degrade", "stage_run.succeeded": "tone-ok", "stage_run.started": "tone-run" };

export function EventTable({ events, onOpen }: { events: ConsoleEvent[]; onOpen?: (e: ConsoleEvent) => void }) {
  const [local, setLocal] = useState<ConsoleEvent | null>(null);
  const open = onOpen ?? setLocal;
  const rows = events.slice(-1500);          // DOM cap; the full set stays searchable and exportable
  if (!events.length) return <Empty title="No events match" />;
  return (
    <div className="compact max-h-[640px] overflow-auto">
      {events.length > rows.length && <div className="px-3 py-1 text-[12px] text-fg-3">Showing the latest {rows.length} of {events.length}.</div>}
      <table className="dt">
        <thead><tr><th>Time (UTC)</th><th className="num">#</th><th>Stage</th><th>Type</th><th>Item</th><th>Detail</th></tr></thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.event_id} className="cursor-pointer" onClick={() => open(e)} tabIndex={0} onKeyDown={(k) => { if (k.key === "Enter") open(e); }}>
              <td className="mono whitespace-nowrap text-fg-2">{fmtClock(e.time)}</td>
              <td className="num mono text-fg-3">{e.seq}</td>
              <td className="whitespace-nowrap capitalize">{stageName(e.stage)}</td>
              <td><span className={`badge ${TYPE_TONE[e.type] ?? (e.severity === "warning" ? "tone-warn" : "tone-muted")}`}>{e.type}</span></td>
              <td className="mono max-w-[340px] truncate" title={e.item?.id}>{e.item ? `${e.item.kind} ${e.item.id}` : ""}</td>
              <td className="max-w-[420px] truncate text-fg-2">
                {e.message ?? (e.progress ? `${e.progress.done}/${e.progress.total} ${e.progress.unit}` : e.data && "stage" in e.data && e.type.includes("input") ? `${String(e.data.stage)} ${String(e.data.run_version ?? "absent")} (${String(e.data.resolved)})` : "")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!onOpen && <Drawer open={!!local} onClose={() => setLocal(null)} title={local ? `${local.type} #${local.seq}` : ""}>{local && <Code text={JSON.stringify(local, null, 2)} />}</Drawer>}
    </div>
  );
}
