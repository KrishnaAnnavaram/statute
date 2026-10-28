import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type BrdDoc } from "../api";
import { fmtBytes } from "../lib/format";
import { Loading } from "./ui";
import { MarkdownView, slugify } from "./viewers";

interface TocEntry { id: string; text: string; level: number }

/** Headings outside fenced code blocks, slugged exactly as the renderer slugs them. */
function buildToc(md: string): TocEntry[] {
  const out: TocEntry[] = [];
  let fence = false;
  for (const line of md.split(/\r?\n/)) {
    if (/^\s*```/.test(line)) { fence = !fence; continue; }
    if (fence) continue;
    const m = /^(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (m) {
      const text = m[2].replace(/[*_`[\]]/g, "").replace(/\(([^)]*)\)/g, (_, x) => (x.startsWith("#") ? "" : `(${x})`)).trim();
      out.push({ id: slugify(text), text, level: m[1].length });
    }
  }
  return out;
}

export default function BrdModal({ onClose }: { onClose: () => void }) {
  const q = useQuery({ queryKey: ["brd"], queryFn: () => api<BrdDoc>("/brd"), staleTime: 30000 });
  const toc = useMemo(() => (q.data ? buildToc(q.data.content) : []), [q.data]);
  const [active, setActive] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const diagrams = useMemo(() => (q.data?.content.match(/```mermaid/g) ?? []).length, [q.data]);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [onClose]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !toc.length) return;
    const handler = () => {
      for (let i = toc.length - 1; i >= 0; i--) {
        const h = document.getElementById(toc[i].id);
        if (h && h.getBoundingClientRect().top <= 140) { setActive(toc[i].id); return; }
      }
      setActive(toc[0].id);
    };
    el.addEventListener("scroll", handler, { passive: true });
    handler();
    return () => el.removeEventListener("scroll", handler);
  }, [toc]);

  const download = () => {
    if (!q.data) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([q.data.content], { type: "text/markdown" }));
    a.download = q.data.name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4 py-6" style={{ background: "rgba(0,0,0,0.82)" }}
      onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="brd-title"
        className="flex w-full max-w-[1180px] flex-col rounded-xl border border-line bg-surface outline-none" style={{ maxHeight: "calc(100vh - 48px)" }}>
        <div className="flex shrink-0 items-center justify-between gap-3 rounded-t-xl border-b border-line px-6 py-4">
          <div>
            <div id="brd-title" className="text-[16px] font-extrabold">Business Requirements Document</div>
            <div className="mt-0.5 text-[12px] text-fg-3">
              {q.data ? <>{fmtBytes(q.data.bytes)} · {q.data.name} · {q.data.system} · run <span className="mono">{q.data.run_version}</span>
                {diagrams ? <span style={{ color: "var(--color-accent-text)" }}> · {diagrams} diagrams (sandboxed)</span> : null}</> : "Loading…"}
            </div>
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn" onClick={download} disabled={!q.data}>Download .md</button>
            <button type="button" className="btn btn-gold" onClick={onClose}>Close</button>
          </div>
        </div>
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {toc.length > 0 && (
            <nav aria-label="BRD contents" className="w-[240px] shrink-0 overflow-y-auto border-r border-line py-4">
              <div className="label px-3.5 pb-2.5">Contents</div>
              {toc.map((e, i) => (
                <button key={`${e.id}-${i}`} type="button"
                  onClick={() => { document.getElementById(e.id)?.scrollIntoView({ behavior: "smooth", block: "start" }); setActive(e.id); }}
                  className="block w-full border-l-2 bg-transparent py-1 pr-3.5 text-left leading-snug"
                  style={{ paddingLeft: e.level === 1 ? 14 : e.level === 2 ? 22 : 30, fontSize: e.level === 1 ? 13 : 12,
                    fontWeight: e.level === 1 ? 700 : 400, cursor: "pointer",
                    color: active === e.id ? "var(--color-accent-text)" : "var(--color-text-muted)",
                    borderLeftColor: active === e.id ? "var(--color-accent)" : "transparent" }}>
                  {e.text}
                </button>
              ))}
            </nav>
          )}
          <div ref={scrollRef} className="min-w-0 flex-1 overflow-y-auto px-9 py-7" tabIndex={0} aria-label="BRD text">
            {q.isLoading ? <Loading what="Loading BRD" /> : q.error ? <div className="callout-fail">{String(q.error)}</div> : <MarkdownView text={q.data!.content} maxWidth={860} />}
          </div>
        </div>
      </div>
    </div>
  );
}
