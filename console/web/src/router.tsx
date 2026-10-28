import { createRootRoute, createRoute, createRouter, Link } from "@tanstack/react-router";
import { Layout } from "./components/Layout";
import { Empty, Panel } from "./components/ui";
import { lazy } from "react";
import { PipelinePage } from "./pages/PipelinePage";
import type { FindingsSearch } from "./pages/FindingsPage";
import type { EventsSearch } from "./pages/EventsPage";
import type { Category } from "./api";

// Route-level code splitting: the home page loads first; everything else on demand.
const RunsPage = lazy(() => import("./pages/RunsPage").then((m) => ({ default: m.RunsPage })));
const PipelineRunPage = lazy(() => import("./pages/RunsPage").then((m) => ({ default: m.PipelineRunPage })));
const StageRunPage = lazy(() => import("./pages/StageRunPage").then((m) => ({ default: m.StageRunPage })));
const FindingsPage = lazy(() => import("./pages/FindingsPage").then((m) => ({ default: m.FindingsPage })));
const EvidenceSearchPage = lazy(() => import("./pages/EvidencePage").then((m) => ({ default: m.EvidenceSearchPage })));
const EntityPage = lazy(() => import("./pages/EvidencePage").then((m) => ({ default: m.EntityPage })));
const EventsPage = lazy(() => import("./pages/EventsPage").then((m) => ({ default: m.EventsPage })));
const ComparePage = lazy(() => import("./pages/OtherPages").then((m) => ({ default: m.ComparePage })));
const HealthPage = lazy(() => import("./pages/OtherPages").then((m) => ({ default: m.HealthPage })));
const AgentsPage = lazy(() => import("./pages/HarnessPages").then((m) => ({ default: m.AgentsPage })));
const ArtifactsPage = lazy(() => import("./pages/HarnessPages").then((m) => ({ default: m.ArtifactsPage })));
const TracePage = lazy(() => import("./pages/HarnessPages").then((m) => ({ default: m.TracePage })));
const TimelinePage = lazy(() => import("./pages/HarnessPages").then((m) => ({ default: m.TimelinePage })));
const StatePage = lazy(() => import("./pages/HarnessPages").then((m) => ({ default: m.StatePage })));
const TestingPage = lazy(() => import("./pages/InsightPages").then((m) => ({ default: m.TestingPage })));
const WorkflowPage = lazy(() => import("./pages/InsightPages").then((m) => ({ default: m.WorkflowPage })));
const DiagramsPage = lazy(() => import("./pages/InsightPages").then((m) => ({ default: m.DiagramsPage })));
const RulesPage = lazy(() => import("./pages/InsightPages").then((m) => ({ default: m.RulesPage })));
const DataModelPage = lazy(() => import("./pages/InsightPages").then((m) => ({ default: m.DataModelPage })));

const str = (v: unknown) => (typeof v === "string" && v ? v : undefined);
const TABS = ["summary", "inputs", "outputs", "items", "findings", "events", "raw"] as const;
type Tab = (typeof TABS)[number];

const root = createRootRoute({
  component: Layout,
  notFoundComponent: () => (
    <Panel title="Not found"><Empty title="There is no such page."><Link to="/">Back to the pipeline</Link></Empty></Panel>
  ),
});

const routes = [
  createRoute({ getParentRoute: () => root, path: "/", component: PipelinePage }),
  createRoute({ getParentRoute: () => root, path: "/runs", component: RunsPage }),
  createRoute({ getParentRoute: () => root, path: "/runs/$pid",
    component: function C() { const { pid } = pipelineRun.useParams(); return <PipelineRunPage pid={pid} />; } }),
  createRoute({ getParentRoute: () => root, path: "/stages", component: AgentsPage }),
  createRoute({ getParentRoute: () => root, path: "/agents", component: AgentsPage }),
  createRoute({ getParentRoute: () => root, path: "/artifacts", component: ArtifactsPage }),
  createRoute({ getParentRoute: () => root, path: "/trace", component: TracePage }),
  createRoute({ getParentRoute: () => root, path: "/timeline", component: TimelinePage }),
  createRoute({ getParentRoute: () => root, path: "/state", component: StatePage }),
  createRoute({ getParentRoute: () => root, path: "/testing", component: TestingPage }),
  createRoute({ getParentRoute: () => root, path: "/workflow", component: WorkflowPage }),
  createRoute({ getParentRoute: () => root, path: "/diagrams", component: DiagramsPage }),
  createRoute({ getParentRoute: () => root, path: "/rules", component: RulesPage }),
  createRoute({ getParentRoute: () => root, path: "/data", component: DataModelPage }),
  createRoute({ getParentRoute: () => root, path: "/health", component: HealthPage }),
];
const pipelineRun = routes[2];

const stageRun = createRoute({
  getParentRoute: () => root, path: "/stages/$stage/runs/$rid",
  validateSearch: (s: Record<string, unknown>): { tab?: Tab; artifact?: string } => ({
    tab: TABS.includes(s.tab as Tab) ? (s.tab as Tab) : undefined, artifact: str(s.artifact),
  }),
  component: function C() {
    const { stage, rid } = stageRun.useParams();
    const { tab, artifact } = stageRun.useSearch();
    return <StageRunPage key={`${stage}/${rid}`} stage={stage} rid={rid} tab={tab ?? "summary"} artifact={artifact} />;
  },
});

const findings = createRoute({
  getParentRoute: () => root, path: "/findings",
  validateSearch: (s: Record<string, unknown>): FindingsSearch => ({
    category: (["run", "lineage", "source", "content", "review"].includes(s.category as string) ? s.category : undefined) as Category | undefined,
    severity: str(s.severity), stage: str(s.stage), q: str(s.q),
  }),
  component: function C() { return <FindingsPage search={findings.useSearch()} />; },
});

const evidence = createRoute({
  getParentRoute: () => root, path: "/evidence",
  validateSearch: (s: Record<string, unknown>): { q?: string } => ({ q: str(s.q) }),
  component: function C() { const { q } = evidence.useSearch(); return <EvidenceSearchPage key={q} q={q} />; },
});
const entity = createRoute({
  getParentRoute: () => root, path: "/evidence/$kind/$id",
  component: function C() { const { kind, id } = entity.useParams(); return <EntityPage kind={kind} id={id} />; },
});

const compare = createRoute({
  getParentRoute: () => root, path: "/compare",
  validateSearch: (s: Record<string, unknown>): { a?: string; b?: string } => ({ a: str(s.a), b: str(s.b) }),
  component: function C() { const { a, b } = compare.useSearch(); return <ComparePage a={a} b={b} />; },
});

const events = createRoute({
  getParentRoute: () => root, path: "/events",
  validateSearch: (s: Record<string, unknown>): EventsSearch => ({ stage: str(s.stage), type: str(s.type), q: str(s.q), severity: str(s.severity) }),
  component: function C() { return <EventsPage search={events.useSearch()} />; },
});

const routeTree = root.addChildren([...routes, stageRun, findings, evidence, entity, compare, events]);
export const router = createRouter({ routeTree, defaultPreload: false, scrollRestoration: true });
