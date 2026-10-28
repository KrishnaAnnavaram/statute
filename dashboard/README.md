# dashboard/ — research only

This folder holds the **research and architecture proposal** for an operational dashboard for STATUTE ("Statue"). Nothing here is code, and nothing in STATUTE was changed to produce it. The folder can be deleted once the proposal has been reviewed and its decisions carried forward.

| File | What it is | Read it if you want… |
|---|---|---|
| [00-statue-dashboard-research-report.md](00-statue-dashboard-research-report.md) | **The report** — *Statue (STATUTE) — Architecture, Harness, Observability, and Dashboard Research*: 55 sections, 8 Mermaid diagrams, final answers A–W | the conclusions and the proposal |
| [01-evidence-repository.md](01-evidence-repository.md) | Appendix A — naming, 42-row documentation drift register, live execution trace, failure probes, write-order semantics, tests, identifiers, MARS facts, branch state | to check a claim about the repository |
| [02-evidence-external-research.md](02-evidence-external-research.md) | Appendix B — cited research on Claude Code telemetry, agent-observability platforms, OTel, workflow/lineage tools, HITL, tracing/APM, developer platforms, frontend libraries, transport, design and rendering security | to check a claim about another product |
| [03-build-and-review-report.md](03-build-and-review-report.md) | **The build**: what was implemented in `console/` and `lib_runlog.py`, tests and results, the two LLM-as-judge passes, the defects found and fixed, and the remaining limitations | what was actually built and how it was verified |
| `Statue Repository — Deep Research, … Prompt.md` | The research brief (supplied separately; not edited) | the original questions |

## Suggested reading order

1. Report §1 *Executive Summary* and §55 *Required Final Answers*.
2. Report §20–§23 (product definition, personas, information architecture, live status) and §44 *Wireframes*.
3. Report §49 *MVP*, §50 *Roadmap*, §51 *Required Instrumentation Changes*, §53 *Open Questions*.
4. Appendices as needed.

## Headline conclusions

- STATUTE is a deterministic, file-mediated eight-stage pipeline; the Claude Code "agents" are thin wrappers, and there is no orchestrator.
- A live "Mission Control" is not justified. A read-only **STATUTE Console**, focused on stage state, lineage and staleness, findings and review, and evidence down to the source line, is.
- Files stay the source of truth. The console is a localhost-only Python read API with a React + TypeScript + Tailwind UI, using polling rather than streaming. A small additive helper makes *running* and *failed* recorded facts.
- Share a design system and event conventions with MARS, not a backend.

## Decisions needed before implementation

See report §53 (Q1–Q11). The four that block the MVP:

1. **Where the console code lives:** a new top-level `console/` is proposed. It should not go in this folder.
2. **Instrumentation:** may the additive run-lifecycle helper (§51 I1–I5) be added to the eight stage scripts?
3. **Stack:** React + Vite + Tailwind, or a Python-rendered first version?
4. **Hooks:** may a project `.claude/settings.json` with observational Claude Code hooks be added (Phase 3)?
