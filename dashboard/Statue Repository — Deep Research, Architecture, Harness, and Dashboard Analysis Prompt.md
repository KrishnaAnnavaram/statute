# Statue — Deep Repository Inspection, Architecture Research, Harness Analysis, and Dashboard Proposal

You are acting as a **Principal Software Architect, AI/Agent Systems Architect, Observability Architect, Developer Platform Architect, Enterprise UX Architect, and Technical Product Designer**.

The repository/project to analyze is:

**Statue**

Statue is a repository in my GitHub account.

Your job is to deeply inspect Statue, understand what the system actually does, reconstruct its architecture and runtime behavior, identify any harness/agent/workflow/orchestration mechanisms, research comparable systems and dashboards, and determine what observability, status, control, and dashboard capabilities Statue should have.

This is a **research and architecture task first**.

---

# IMPORTANT — DO NOT IMPLEMENT YET

Do not immediately create a dashboard or modify the system.

Do NOT:

- redesign the repository before understanding it
- add React
- install dashboard libraries
- add dependencies
- modify runtime behavior
- modify agents
- modify skills
- modify scripts
- change workflow contracts
- change databases
- change CI/CD
- create APIs
- introduce OpenTelemetry
- modify production code
- create speculative infrastructure

First perform:

**repository inspection → architecture reconstruction → runtime analysis → observability-gap analysis → external research → dashboard research → architecture proposal.**

Implementation should happen only after the proposal is reviewed.

---

# 1. Deeply Inspect the Statue Repository

Start by exploring the entire repository.

Do not rely only on the root README.

Inspect:

- root files
- README files
- documentation
- source directories
- configuration
- manifests
- package/build files
- scripts
- CLI commands
- workflows
- GitHub Actions
- CI/CD
- Docker/container files
- environment configuration
- database configuration
- API definitions
- schemas
- agent definitions
- skill definitions
- prompt files
- hooks
- tools
- plugins
- MCP integrations
- workflow definitions
- orchestration code
- queues
- schedulers
- workers
- event systems
- logging
- tracing
- generated artifacts
- test infrastructure
- synthetic tests
- fixtures
- examples
- deployment configuration
- security controls
- approval mechanisms
- external integrations

If Statue contains hidden/configuration directories that define important runtime behavior, inspect those as well.

Search the repository rather than assuming file names.

---

# 2. First Answer: What Is Statue?

Before proposing anything, determine:

**What is Statue actually designed to do?**

Explain:

- the project's purpose
- primary users
- primary workflows
- main components
- inputs
- outputs
- runtime model
- execution model
- persistence model
- external systems
- automation
- human interaction
- security boundaries
- deployment model

Distinguish clearly between:

### Documented architecture

What README/docs claim.

### Implemented architecture

What the code actually does.

### Intended architecture

What incomplete code/configuration suggests is planned.

Do not mix these categories.

---

# 3. Detect Documentation Drift

Compare documentation against the actual repository.

Identify discrepancies such as:

- documented components that no longer exist
- undocumented components
- outdated diagrams
- outdated dependency versions
- incorrect workflow descriptions
- mismatched counts
- obsolete scripts
- unused configuration
- stale CI/CD
- abandoned features
- duplicated functionality
- naming inconsistencies

Produce a documentation-drift section.

---

# 4. Reconstruct the System Architecture

Create a complete conceptual architecture of Statue.

Identify:

- frontend
- backend
- APIs
- workers
- agents
- skills
- scripts
- tools
- queues
- databases
- graph databases
- vector databases
- artifact stores
- caches
- event buses
- model providers
- external APIs
- authentication
- authorization
- CI/CD
- deployment
- observability
- user-facing applications

Only include components that actually exist or are strongly evidenced.

Label speculative/future components separately.

---

# 5. Determine Whether Statue Contains a Harness

Investigate specifically whether Statue contains anything that functions as a:

- agent harness
- workflow engine
- orchestration layer
- task runner
- remediation harness
- evaluation harness
- testing harness
- automation framework
- multi-agent system
- job scheduler
- event-driven workflow
- pipeline system

If it does, reconstruct that harness.

If it does not, do not force MARS concepts onto Statue.

Instead determine Statue's actual runtime abstraction.

---

# 6. Reconstruct the Runtime Hierarchy

Determine the real runtime hierarchy.

Possible concepts might include:

Project
→ Run
→ Workflow
→ Stage
→ Agent
→ Skill
→ Task
→ Operation
→ Tool
→ Script
→ Event
→ Artifact

But DO NOT assume this is correct.

Derive the hierarchy from Statue.

If Statue uses concepts such as:

- jobs
- steps
- workers
- commands
- nodes
- pipelines
- sessions
- requests
- transactions
- evaluations
- scans
- tasks

use Statue's native concepts.

Produce the recommended canonical runtime hierarchy.

---

# 7. Trace One Complete Execution

Select a representative Statue workflow and trace it from beginning to end.

Document:

1. what initiates execution
2. what receives the request
3. what component acts first
4. what state is created
5. which components execute
6. which scripts/tools are called
7. which external systems are contacted
8. which data is read
9. which data is written
10. which artifacts are generated
11. what errors can occur
12. what retries occur
13. whether humans participate
14. how completion is determined
15. what final result is produced

Include file references and code references.

---

# 8. Inventory Statue

Create an inventory of important runtime components.

For each component include:

- ID/name
- type
- purpose
- source location
- inputs
- outputs
- dependencies
- callers
- downstream consumers
- persistence
- generated artifacts
- error behavior
- logging behavior
- tests
- observability

Where applicable, separately inventory:

- agents
- skills
- tools
- scripts
- workers
- workflows
- APIs
- services
- queues
- scheduled jobs
- database entities
- generated artifacts

---

# 9. Investigate Existing Status and Observability

Determine what Statue currently exposes about its own operation.

Search for:

- logs
- structured logs
- tracing
- metrics
- status endpoints
- health endpoints
- progress tracking
- audit events
- run IDs
- job IDs
- correlation IDs
- trace IDs
- event IDs
- error reporting
- execution timing
- performance metrics
- dashboards
- admin pages
- debug pages
- CLI status commands

Determine whether a developer can currently answer:

**What is Statue doing right now?**

If yes, explain how.

If not, identify exactly what is missing.

---

# 10. Define the "Exact Current State" Requirement

Assume that a future Statue operational interface should let a developer answer, without opening a terminal:

- What is currently running?
- Why is it running?
- What triggered it?
- What component owns it?
- What operation is currently executing?
- What happened immediately before?
- What happens next?
- What inputs were consumed?
- What outputs were produced?
- What external tools/services were called?
- What artifacts were generated?
- What failed?
- What is retrying?
- What is waiting?
- What is blocked?
- Is it waiting for a human?
- How long has it been running?
- Where in the code did this originate?

Determine which of these questions are relevant to Statue.

---

# 11. Research Existing Dashboards and Harness Systems

Perform external deep research.

Do not design Statue's dashboard solely from intuition.

Research mature systems that solve similar problems.

The purpose is to identify proven patterns.

---

# 12. Research Agent Harness and Agent Observability Platforms

Where relevant, investigate systems such as:

- LangSmith
- Langfuse
- Arize Phoenix
- Braintrust
- Weights & Biases Weave
- AgentOps
- Helicone
- OpenLLMetry
- OpenTelemetry GenAI conventions
- OpenAI agent/tracing systems where publicly documented
- other credible agent-runtime observability systems

Investigate:

- run representation
- trace representation
- nested operations
- agent execution
- tool calls
- inputs/outputs
- latency
- token usage
- cost
- errors
- retries
- evaluation
- debugging
- artifact linkage

Determine which patterns actually apply to Statue.

---

# 13. Research Workflow and Orchestration Dashboards

Research systems such as:

- Temporal
- Prefect
- Dagster
- Apache Airflow
- Argo Workflows
- GitHub Actions
- GitLab CI/CD
- Jenkins
- Kubernetes operational dashboards

Study how they visualize:

- workflows
- DAGs
- jobs
- tasks
- dependencies
- queued work
- active work
- failures
- retries
- duration
- artifacts
- logs
- historical runs

Compare these patterns with Statue's execution model.

---

# 14. Research Distributed Tracing and APM

Research patterns from:

- OpenTelemetry
- Grafana
- Jaeger
- Zipkin
- Honeycomb
- Datadog APM
- New Relic
- Elastic Observability

Focus on:

- traces
- spans
- events
- logs
- metrics
- service maps
- waterfall views
- latency
- parent-child relationships
- dependency graphs
- trace-to-log correlation
- metrics-to-trace correlation
- high-cardinality metadata

Determine whether Statue would benefit from distributed-tracing concepts.

---

# 15. Research Developer Platform Dashboards

Research mature developer-facing operational interfaces.

Investigate:

- Backstage
- GitHub
- GitLab
- Vercel
- Cloudflare
- Kubernetes tooling
- deployment platforms
- developer portals
- CI/CD consoles

Study:

- navigation
- project organization
- environment switching
- deployment history
- activity streams
- logs
- system health
- ownership
- drill-down
- search
- command palettes

Identify applicable Statue patterns.

---

# 16. Research Harness-Specific Dashboards

Look specifically for systems that expose the internals of:

- AI harnesses
- evaluation harnesses
- autonomous-agent frameworks
- multi-agent systems
- coding agents
- remediation agents
- test harnesses
- workflow engines
- security automation platforms

Investigate whether they expose:

- agent
- skill
- task
- tool
- script
- operation
- state transition
- artifact
- evidence
- approval
- evaluation
- verdict

Pay special attention to how they avoid overwhelming users with implementation detail.

---

# 17. Research Human-in-the-Loop Systems

If Statue includes or could require human approval, research patterns for:

- approval queues
- decision requests
- review screens
- approve/reject
- request changes
- comments
- evidence
- diff review
- identity
- timestamps
- expiration
- escalation
- audit history

Determine whether Statue needs human approval as a first-class runtime entity.

Do not add approval merely because MARS has it.

---

# 18. Build a Competitive / Pattern Matrix

Create a matrix comparing relevant researched systems.

For each include:

- product/system
- primary use case
- runtime model
- live status model
- trace model
- workflow visualization
- logs
- metrics
- artifacts
- approvals
- debugging
- history
- replay
- architecture/dependency visualization
- strengths
- weaknesses
- concepts Statue could adopt
- concepts Statue should avoid

Do not choose a single system to clone.

Synthesize patterns.

---

# 19. Determine Whether Statue Needs a Dashboard

Do not assume that it does.

After repository analysis, explicitly answer:

**Would a dedicated operational dashboard materially improve Statue?**

Evaluate:

- number of concurrent operations
- execution complexity
- workflow depth
- debugging difficulty
- human approvals
- artifacts
- failures
- retries
- historical analysis
- multiple users
- multiple environments
- system complexity

If a dashboard is justified, define its purpose.

---

# 20. Define Statue Mission Control / Live Status

If justified, propose the appropriate product concept.

Possible purposes include:

- runtime observability
- workflow monitoring
- developer debugging
- operational command center
- agent observability
- approval center
- system health
- artifact/evidence browser
- analytics

Determine the correct hierarchy for Statue.

Do not simply call it "Mission Control" unless that framing fits.

---

# 21. Design the Main Live Status Screen

The primary screen should answer within seconds:

**What is Statue doing right now?**

Determine whether it should show:

- active runs
- active workflows
- current operation
- status
- owner/component
- elapsed time
- dependencies
- waiting states
- retries
- errors
- human action required
- recently completed work
- next expected operation

Design the information hierarchy.

Avoid a homepage made primarily from KPI cards.

---

# 22. Design Runtime Drill-Down

A developer should be able to navigate from:

System
→ Run
→ Workflow
→ Component
→ Operation
→ Event
→ Artifact

or whatever hierarchy actually fits Statue.

For each level define:

- summary
- status
- inputs
- outputs
- timing
- dependencies
- errors
- retries
- logs
- events
- artifacts
- source references
- downstream effects

---

# 23. Design Graph Visualization

Determine whether Statue needs an interactive graph.

Possible graph types:

## Runtime graph

What is executing right now?

## Dependency graph

Which components depend on each other?

## Data-flow graph

How does information move?

## Application architecture graph

How is Statue structured?

## Artifact lineage graph

Where did this output come from?

Do not combine unrelated graph types into one unreadable visualization.

Recommend separate graph experiences where necessary.

---

# 24. Design the Event Console

Determine whether Statue should have a unified event stream.

Possible fields:

- timestamp
- event type
- severity
- run
- workflow
- component
- operation
- tool/script
- status
- duration
- correlation ID
- trace ID
- span ID
- artifact
- error

Research and recommend:

- filtering
- search
- follow-live
- pause
- resume
- JSON view
- export
- correlation
- redaction
- retention

Do not dump every raw log on the main dashboard.

---

# 25. Define Safe AI Observability

If Statue uses LLMs or agents:

DO NOT design the dashboard around private chain-of-thought.

Instead expose structured operational information:

- declared objective
- current task
- tool invocation
- sanitized inputs
- sanitized outputs
- explicit decisions
- evidence
- artifacts
- errors
- timing
- status
- model metadata where useful

Distinguish:

**operational trace**

from

**private model reasoning**.

---

# 26. Design Artifact and Evidence Lineage

If Statue generates outputs, determine whether they should become first-class dashboard entities.

For each artifact potentially show:

- ID
- type
- producer
- run
- workflow
- operation
- creation time
- version
- source inputs
- downstream consumers
- hash
- storage location
- preview
- related events

Determine whether lineage visualization would materially improve debugging.

---

# 27. Define a Canonical Event Model

If live observability is appropriate, propose a normalized event envelope.

Possible fields:

event_id  
event_type  
timestamp  
project_id  
repository_id  
environment  
run_id  
workflow_id  
stage_id  
agent_id  
skill_id  
task_id  
operation_id  
tool_id  
script_id  
trace_id  
span_id  
parent_span_id  
status  
progress  
description  
input_refs  
output_refs  
artifact_refs  
error  
retry  
duration  
metadata

Only retain fields relevant to Statue.

Derive the final schema from the actual runtime.

---

# 28. Define Lifecycle Events

Determine which lifecycle events Statue actually needs.

Examples:

run.started  
run.completed  
run.failed

workflow.started  
workflow.completed  
workflow.failed

task.started  
task.progress  
task.completed  
task.failed

tool.invoked  
tool.completed  
tool.failed

script.started  
script.completed  
script.failed

artifact.created

approval.requested  
approval.approved  
approval.rejected

retry.scheduled

system.warning

Do not mechanically adopt these.

Create a Statue-specific event vocabulary.

---

# 29. Evaluate OpenTelemetry

Research current OpenTelemetry capabilities.

Determine whether Statue should use:

1. OpenTelemetry directly
2. a Statue-specific event model exported to OpenTelemetry
3. OpenTelemetry traces plus a domain-event system
4. another architecture

Define what should become:

- trace
- span
- event
- log
- metric
- resource
- attribute

Explain tradeoffs.

---

# 30. Real-Time Architecture

If live status is needed, compare:

- polling
- Server-Sent Events
- WebSockets
- event brokers
- message queues

Determine the simplest architecture that satisfies Statue.

A possible conceptual architecture is:

Statue Runtime
→ Structured Instrumentation
→ Event Collector
→ Event/Trace Store
→ Statue API
→ Live Stream
→ Dashboard

Do not adopt this unless repository analysis supports it.

---

# 31. Define Source of Truth

Avoid creating a second conflicting state machine.

For every important entity determine the authoritative source.

Create a table:

Entity  
Authoritative Source  
Derived Source  
Live Representation  
Historical Representation

Include relevant entities such as:

- run
- task
- workflow
- status
- artifact
- user decision
- error
- deployment
- configuration

---

# 32. Define Frontend Architecture

If a dedicated dashboard is recommended, assume the preferred frontend direction is:

- React
- TypeScript
- Tailwind CSS

Evaluate supporting libraries instead of blindly installing them.

Research candidates such as:

- Vite
- shadcn/ui
- React Flow / XYFlow
- TanStack Query
- TanStack Table
- virtualization libraries
- Recharts
- Cytoscape
- Monaco
- CodeMirror

For each recommended dependency explain:

- purpose
- advantages
- disadvantages
- scalability
- accessibility
- maintenance risk
- alternatives

---

# 33. Manager vs Developer Views

Determine whether Statue has multiple operational personas.

If appropriate, define:

## Developer view

Potentially:

- runtime trace
- detailed operations
- logs
- errors
- dependencies
- scripts
- tools
- artifacts
- source references
- timing

## Manager/Operator view

Potentially:

- active work
- failures
- stuck operations
- throughput
- reliability
- bottlenecks
- human-action queue
- system health
- historical trends

Avoid vanity metrics.

Every metric should answer an operational question.

---

# 34. Design Historical Run Analysis

Determine whether Statue needs:

- run history
- search
- filtering
- timeline replay
- run comparison
- version comparison
- failure comparison
- artifact comparison
- duration comparison
- environment comparison

Identify telemetry required to support each capability.

---

# 35. Design Replay

Evaluate whether a user should be able to replay an execution visually.

Replay should reconstruct:

- state transitions
- active component
- events
- graph state
- artifacts
- errors
- approvals

Determine whether replay is valuable enough to justify storing the necessary event history.

---

# 36. Design Synthetic / Harness Testing

Determine whether Statue should monitor itself.

Potential synthetic checks:

- runtime availability
- workflow discovery
- agent discovery
- skill discovery
- event pipeline
- external integrations
- database connectivity
- artifact creation
- queue processing
- test execution
- telemetry health

Only include checks relevant to Statue.

---

# 37. Enterprise Requirements

Evaluate future requirements for:

- RBAC
- authentication
- authorization
- SSO
- project isolation
- repository isolation
- environment isolation
- audit
- retention
- sensitive data handling
- secrets
- source-code protection
- telemetry redaction
- exports
- multi-project support
- multi-repository support

Do not over-engineer the MVP.

---

# 38. Security Threat Analysis

Evaluate threats introduced by an operational dashboard.

Consider:

- forged events
- event tampering
- stale status
- unauthorized actions
- replay attacks
- artifact tampering
- secret leakage
- prompt leakage
- source-code leakage
- XSS from generated content
- malicious Markdown
- cross-project leakage
- unsafe links
- privilege escalation
- approval forgery

Recommend protections.

---

# 39. Visual Design Research

Research serious developer and observability consoles.

The design should feel like:

- engineering infrastructure
- operations
- observability
- mission control

Avoid stereotypical AI UI.

Avoid:

- neon gradients everywhere
- meaningless AI animations
- fake thinking indicators
- excessive cards
- oversized metrics
- uncontrolled graphs

Recommend:

- typography
- density
- spacing
- tables
- timelines
- graphs
- badges
- semantic status colors
- drawers
- panels
- code views
- log views
- artifact views
- light mode
- dark mode

Accessibility must be considered.

---

# 40. What Should NOT Be Exposed

Explicitly define what should not appear by default.

Potential examples:

- private chain-of-thought
- secrets
- credentials
- authentication tokens
- sensitive prompts
- unnecessary PII
- unrestricted source
- complete raw logs
- hidden system instructions
- model internals
- misleading "AI thoughts"

Recommend safe alternatives.

---

# 41. What Should NOT Be Built

Identify unnecessary or harmful dashboard ideas.

Examples:

- generic KPI dashboard
- fake AI activity visualizer
- raw-log homepage
- hardcoded workflow graph
- duplicated state machine
- excessive real-time animation
- graph containing every entity simultaneously
- metrics without operational value

Create a Statue-specific anti-pattern list.

---

# 42. Determine Immediate vs Future Capabilities

Classify proposed capabilities as:

## Available today

Can be derived from the existing repository/runtime.

## Requires small instrumentation

Structured events or IDs.

## Requires backend infrastructure

Event collector/API/store.

## Requires significant architecture changes

Major runtime changes.

This distinction is essential.

---

# 43. Produce Detailed Screen Specifications

If a dashboard is justified, define each proposed page.

Potential pages:

- Live Status
- Runs
- Run Detail
- Workflows
- Components
- Agents
- Skills
- Tasks
- Trace
- Events
- Logs
- Artifacts
- Approvals
- Architecture
- System Health
- Audit
- Analytics
- Synthetic Tests

Do not automatically create all of them.

For each recommended screen provide:

- purpose
- persona
- widgets
- fields
- filters
- interactions
- drill-downs
- real-time behavior
- empty state
- error state

---

# 44. Produce Text Wireframes

For important screens create detailed text wireframes.

At minimum, if relevant:

### Live Status

Header  
Navigation  
Current Runtime  
Workflow Graph  
Active Operations  
Event Stream  
Errors/Warnings  
Human Action Required  
Recent Results

### Run Detail

Run Summary  
Execution Graph  
Trace/Waterfall  
Current Operation  
Events  
Artifacts  
Errors  
Timing  
Dependencies

### Component / Agent / Worker Detail

Identity  
Purpose  
Current State  
Operations  
Dependencies  
History  
Artifacts  
Failures

Adapt these to Statue's real model.

---

# 45. Use Real Statue Data

Do not demonstrate the proposed dashboard using fictional workflows unless necessary.

Use actual:

- components
- workflows
- agents
- tasks
- scripts
- jobs
- artifacts
- errors
- tests

from Statue.

Select one representative real execution and show how it would appear in the proposed interface.

---

# 46. Compare Statue and MARS Where Useful

I also have a system called **MARS** that uses an agentic remediation harness.

Do NOT assume Statue and MARS are the same product.

After independently understanding Statue, identify whether there are architectural concepts that could eventually be shared between them.

Potential shared concepts could include:

- run
- event
- trace
- artifact
- approval
- agent
- skill
- task
- observability
- audit
- dashboard components
- telemetry infrastructure

Answer:

### What should be shared?

### What should remain Statue-specific?

### What should remain MARS-specific?

### Could they eventually use a common observability/event platform?

### Could a single Mission Control frontend support both through adapters?

### Would doing so create excessive coupling?

Do not force consolidation.

Only recommend shared architecture if technically justified.

---

# 47. Research Dashboard Reuse

Specifically investigate whether it would be better to build:

### Option A
A Statue-specific dashboard.

### Option B
A MARS-specific dashboard.

### Option C
A common harness observability platform with MARS and Statue adapters.

### Option D
A shared frontend design system but separate backend/domain models.

### Option E
A common telemetry/event layer but separate product experiences.

Analyze tradeoffs before recommending an architecture.

---

# 48. Architecture Diagrams

Produce diagrams for:

1. Current Statue architecture
2. Current Statue runtime/execution model
3. Proposed observability architecture
4. Proposed dashboard architecture
5. Event flow
6. Data/source-of-truth architecture
7. Optional MARS + Statue shared observability architecture

Use Mermaid where useful.

---

# 49. Domain Model

Define the minimum required domain model.

Potential entities may include:

Project  
Repository  
Environment  
Run  
Workflow  
Stage  
Agent  
Skill  
Task  
Operation  
ToolInvocation  
ScriptExecution  
Trace  
Span  
Event  
Artifact  
Approval  
Error  
User

Do not create entities Statue does not need.

For each entity specify:

- purpose
- ID
- important fields
- relationships
- source of truth
- lifecycle

---

# 50. API Requirements

Do not implement APIs.

Define future dashboard requirements.

Potential examples:

GET /status  
GET /runs  
GET /runs/:id  
GET /runs/:id/trace  
GET /runs/:id/events  
GET /workflows  
GET /components  
GET /agents  
GET /skills  
GET /artifacts  
GET /health  
GET /analytics  
GET /events/stream

If human actions exist, separate state-changing APIs from observational APIs.

Do not create endpoints that bypass Statue's existing authority model.

---

# 51. Performance and Scale

Analyze how the proposed dashboard behaves with:

- 1 run
- 10 runs
- 1,000 runs
- 10 events
- 100,000 events
- large logs
- large graphs
- long-running workflows
- concurrent users

Research:

- virtualization
- pagination
- incremental loading
- graph clustering
- server-side filtering
- event retention
- aggregation
- sampling where appropriate

Do not assume everything can remain in browser memory.

---

# 52. Define Success Criteria

Define measurable success criteria.

Examples:

A developer can determine the current operation within 5 seconds.

A developer can navigate from an error to its producing operation and artifact.

A developer can determine why a run is waiting.

A manager can identify blocked work without reading logs.

Live state appears within an acceptable latency.

Reconnect restores missing events.

Historical traces are complete.

Displayed state can be traced to authoritative evidence.

Sensitive information is not exposed by default.

Adapt the final criteria to Statue.

---

# 53. Recommend an MVP

After all research, determine the smallest valuable implementation.

Do not make the MVP a giant enterprise platform.

Prioritize the capabilities necessary to answer:

**What is Statue doing, what just happened, what happens next, and what needs attention?**

---

# 54. Recommend an Implementation Roadmap

Create a phased roadmap.

Potential structure:

Phase 0 — Domain/event contract

Phase 1 — Read-only operational UI

Phase 2 — Structured runtime events

Phase 3 — Live status

Phase 4 — Deep trace/drill-down

Phase 5 — Artifact lineage

Phase 6 — Human actions if required

Phase 7 — Analytics/history/replay

Phase 8 — Enterprise controls

Change this based on Statue's actual architecture.

---

# 55. Final Deliverable

Produce a report titled:

# Statue — Architecture, Harness, Observability, and Dashboard Research

Structure it approximately as:

1. Executive Summary
2. What Statue Actually Is
3. Repository Findings
4. Documentation vs Implementation
5. Current Architecture
6. Runtime Model
7. Representative End-to-End Execution
8. Component Inventory
9. Harness / Workflow Analysis
10. Current Observability
11. Observability Gaps
12. External Research
13. Agent/Harness Dashboard Research
14. Workflow Dashboard Research
15. Distributed Tracing Research
16. Developer Platform Research
17. Comparable Systems Matrix
18. Patterns Statue Should Adopt
19. Patterns Statue Should Avoid
20. Statue Operational Product Definition
21. Personas
22. Information Architecture
23. Live Status
24. Run Explorer
25. Runtime Graph
26. Trace / Timeline
27. Event Console
28. Artifact Lineage
29. Human Approval, if applicable
30. Historical Runs
31. Analytics
32. Synthetic/Harness Health
33. Domain Model
34. Event Model
35. OpenTelemetry Strategy
36. Source-of-Truth Matrix
37. Backend Architecture
38. Real-Time Architecture
39. Frontend Architecture
40. Security Architecture
41. Enterprise Considerations
42. Visual Design System
43. Detailed Screen Specifications
44. Wireframes
45. Real Statue Workflow Walkthrough
46. MARS vs Statue Comparison
47. Shared Platform Opportunities
48. What Not to Build
49. MVP
50. Roadmap
51. Required Instrumentation Changes
52. Risks
53. Open Questions
54. Final Architecture Recommendation

---

# 56. Required Final Answers

End the report by answering clearly:

### A. What is Statue actually doing today?

### B. What is Statue's true runtime hierarchy?

### C. Does Statue have a harness/orchestration layer?

### D. What can developers observe today?

### E. What important runtime state is currently invisible?

### F. Does Statue need a dedicated Live Status / Mission Control dashboard?

### G. If yes, what should its main screen show?

### H. What should its primary screens be?

### I. What should its canonical event model be?

### J. Should Statue use OpenTelemetry?

### K. How should live updates work?

### L. What should be the source of truth?

### M. What should never be exposed in telemetry?

### N. What can be built immediately without changing Statue?

### O. What instrumentation changes are required?

### P. Which existing dashboards/tools provide the best patterns for Statue?

### Q. What should Statue copy conceptually from those systems?

### R. What should Statue explicitly avoid copying?

### S. Should MARS and Statue share observability infrastructure?

### T. Should they share a frontend/design system?

### U. Should they remain completely independent?

### V. What is the smallest useful MVP?

### W. What is the recommended implementation sequence?

---

# Core Principle

Do not start with:

**"What dashboard should we build?"**

Start with:

**"What actually happens inside Statue, what information exists, what information is missing, and what does a human need to understand the system?"**

Then research how mature agent platforms, harnesses, workflow engines, CI/CD systems, tracing platforms, and developer tools solve those problems.

Only after that should you propose the dashboard.

The final recommendation must be grounded in:

**actual Statue code + actual runtime behavior + external research + proven observability patterns + realistic implementation constraints.**

Do not implement anything until the architecture and research proposal has been reviewed.