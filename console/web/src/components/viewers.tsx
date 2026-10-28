import { useEffect, useMemo, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { Code } from "./ui";

/**
 * Generated content is untrusted: STATUTE copies identifiers, comments and annotation
 * text from a third-party PL/SQL estate into Markdown, Mermaid labels and JSON.
 *  - Markdown: raw HTML is escaped (react-markdown default, no rehype-raw); links are allow-listed.
 *  - Mermaid: rendered with securityLevel "strict", then shown inside an iframe with an empty
 *    sandbox attribute, so even a renderer bypass cannot run script or reach this page.
 */
const SAFE_HREF = /^(https?:|mailto:|#|\/(?!\/)|\.{0,2}\/)/i;

export function safeHref(href: string | undefined): string | undefined {
  if (!href) return undefined;
  const h = href.trim();
  return SAFE_HREF.test(h) || !/^[a-z][a-z0-9+.-]*:/i.test(h) ? h : undefined;
}

export function slugify(text: string): string {
  return text.toLowerCase().trim().replace(/[^\w\s-]/g, "").replace(/\s+/g, "-");
}
function childText(children: ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(childText).join("");
  if (children && typeof children === "object" && "props" in children) return childText((children as { props: { children?: ReactNode } }).props.children);
  return "";
}

const mdComponents: Components = {
  a: ({ href, children }) => {
    const h = safeHref(href);
    if (!h) return <span title="link removed: unsafe scheme">{children}</span>;
    const external = /^https?:/i.test(h);
    return <a href={h} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{children}</a>;
  },
  h1: ({ children }) => <h1 id={slugify(childText(children))} className="mb-4 mt-0 border-b-2 pb-2.5 text-[24px] font-extrabold" style={{ borderColor: "var(--color-accent)", color: "var(--color-accent-text)" }}>{children}</h1>,
  h2: ({ children }) => <h2 id={slugify(childText(children))} className="mb-2.5 mt-8 border-b border-line pb-1.5 text-[18px] font-bold">{children}</h2>,
  h3: ({ children }) => <h3 id={slugify(childText(children))} className="mb-2 mt-5 text-[15px] font-bold">{children}</h3>,
  h4: ({ children }) => <h4 id={slugify(childText(children))} className="mb-1.5 mt-3.5 text-[12px] font-bold uppercase tracking-wider text-fg-3">{children}</h4>,
  p: ({ children }) => <p className="mb-3 mt-0 leading-[1.75]">{children}</p>,
  table: ({ children }) => <div className="my-3 overflow-x-auto"><table className="dt">{children}</table></div>,
  code: ({ children, className }) => {
    if (className?.includes("language-mermaid")) return <MermaidView source={childText(children)} title="diagram" height={420} compact />;
    return className ? <code className="mono">{children}</code> : <code className="mono rounded bg-surface-2 px-1.5 py-0.5">{children}</code>;
  },
  pre: ({ children }) => {
    const only = Array.isArray(children) ? children[0] : children;
    const cls = (only as { props?: { className?: string } })?.props?.className ?? "";
    if (cls.includes("language-mermaid")) return <>{children}</>;
    return <pre className="mono my-3 overflow-auto rounded-lg border border-line bg-surface-2 px-4 py-3.5 text-[12px]">{children}</pre>;
  },
  ul: ({ children }) => <ul className="mb-3 mt-0 list-disc pl-6">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 mt-0 list-decimal pl-6">{children}</ol>,
  li: ({ children }) => <li className="mb-1">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-3.5 rounded-r-md border-l-[3px] px-4 py-2.5 text-[13px] text-fg-3"
      style={{ borderColor: "var(--color-accent)", background: "color-mix(in srgb, var(--color-accent) 7%, transparent)" }}>{children}</blockquote>
  ),
  hr: () => <hr className="my-7 border-0 border-t border-line" />,
  img: ({ alt }) => <span className="text-fg-3">[image omitted: {alt}]</span>,
};

export function MarkdownView({ text, maxWidth = 920 }: { text: string; maxWidth?: number }) {
  return <div className="text-[14px] leading-[1.75]" style={{ maxWidth }}><ReactMarkdown components={mdComponents} skipHtml>{text}</ReactMarkdown></div>;
}

let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;
let mermaidTheme = "";
function loadMermaid() {
  const dark = document.documentElement.getAttribute("data-theme") !== "light";
  const theme = dark ? "dark" : "default";
  if (!mermaidPromise || mermaidTheme !== theme) {
    mermaidTheme = theme;
    mermaidPromise = import("mermaid").then((m) => {
      m.default.initialize({ startOnLoad: false, securityLevel: "strict", theme, flowchart: { htmlLabels: false, curve: "basis" },
        fontFamily: "-apple-system, Segoe UI, Roboto, sans-serif", maxTextSize: 200000 });
      return m.default;
    });
  }
  return mermaidPromise;
}

// STATUTE's classDefs use pastel fills; keep their labels dark in either theme.
const PASTEL_TEXT = [".dataNode", ".errorNode", ".external", ".inferred", ".warning"]
  .map((c) => `g${c} text,g${c} tspan,g${c} .nodeLabel`).join(",") + "{fill:#1f2937!important;color:#1f2937!important}";

export function MermaidView({ source, title, height = "78vh", compact }: { source: string; title: string; height?: number | string; compact?: boolean }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);
  const clean = useMemo(() => source.replace(/%%\{[\s\S]*?\}%%/g, ""), [source]);   // never honour %%{init}%% directives
  useEffect(() => {
    let alive = true;
    setSvg(null); setErr(null);
    const timer = setTimeout(() => { if (alive) setErr((e) => e ?? "rendering took too long (over 8 s)"); }, 8000);
    loadMermaid()
      .then((m) => m.render(`mmd-${Math.random().toString(36).slice(2)}`, clean))
      .then((r) => { if (alive) setSvg(r.svg); })
      .catch((e: unknown) => { if (alive) setErr(e instanceof Error ? e.message.split("\n")[0] : "render failed"); })
      .finally(() => clearTimeout(timer));
    return () => { alive = false; clearTimeout(timer); };
  }, [clean]);
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--color-surface-2").trim() || "#222";
  const doc = svg && `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:${bg}}svg{max-width:100%;height:auto;display:block;margin:auto;padding:12px}${PASTEL_TEXT}</style>${svg}`;
  return (
    <div className={compact ? "my-4" : ""}>
      <div className="mb-1.5 flex items-center gap-2 text-[11px] text-fg-3">
        <span>Diagram · isolated frame, scripts disabled</span>
        <button type="button" className="btn ml-auto !px-2 !py-0.5 !text-[11px]" onClick={() => setShowSource((s) => !s)}>
          {showSource ? "Show diagram" : "Show Mermaid source"}
        </button>
      </div>
      {showSource || err ? (
        <>
          {err && <div className="mb-2 text-[12px] text-fg-2" role="status">Diagram could not be rendered ({err}); showing its source.</div>}
          <Code text={source} maxHeight={typeof height === "number" ? height : 520} />
        </>
      ) : doc ? (
        <iframe title={title} sandbox="" srcDoc={doc} className="w-full rounded-lg border border-line" style={{ height, background: bg }} />
      ) : <div className="rounded-lg border border-dashed border-line py-10 text-center text-[12px] text-fg-3" role="status">Rendering diagram…</div>}
    </div>
  );
}

export function JsonView({ text }: { text: string }) {
  const pretty = useMemo(() => {
    try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
  }, [text]);
  return <Code text={pretty} maxHeight={640} />;
}

export function ArtifactBody({ path, text, truncated }: { path: string; text: string | null; truncated: boolean }) {
  if (text === null) return <div className="text-fg-3">This file type is not previewed.</div>;
  const note = truncated ? <div className="mb-2 text-[12px] text-fg-2">Preview truncated at 2 MB.</div> : null;
  if (path.endsWith(".mmd")) return <>{note}<MermaidView source={text} title={path} /></>;
  if (path.endsWith(".md")) return <>{note}<MarkdownView text={text} /></>;
  if (path.endsWith(".json")) return <>{note}<JsonView text={text} /></>;
  return <>{note}<Code text={text} maxHeight={640} /></>;
}
