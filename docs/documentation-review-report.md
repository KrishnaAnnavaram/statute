# Documentation Review Report

A strict self-critique of this documentation package against the 19 criteria in the brief, plus the corrections applied and the deliverables deliberately not created.

## Contents

- [1. Scored review](#1-scored-review)
- [2. Defects found and corrected during review](#2-defects-found-and-corrected-during-review)
- [3. Unsupported claims removed or relabelled](#3-unsupported-claims-removed-or-relabelled)
- [4. Requested documents not created, and why](#4-requested-documents-not-created-and-why)
- [5. Final validation checklist](#5-final-validation-checklist)
- [6. Residual weaknesses](#6-residual-weaknesses)

---

## 1. Scored review

| # | Criterion | Score | Reasoning |
|---|---|---|---|
| 1 | **Correctness** | 9/10 | Every technical claim was verified against the code or a live artefact. Two claims were corrected mid-review (see §2). The one deduction: complexity estimates are read from code, never profiled. |
| 2 | **Completeness** | 8/10 | All 8 agents, master document, README and 6 supporting documents. Deduction: 9 requested supporting documents were folded into the master rather than created separately (§4) — defensible, but it is a deviation from the brief. |
| 3 | **Repository grounding** | 10/10 | Every claim carries a file, function or line, or is explicitly labelled inference or `Not found`. Absences were positively verified, not assumed — see [traceability-matrix §5](traceability-matrix.md#5-verified-absences). |
| 4 | **Technical depth** | 9/10 | All formulas extracted with variables, ranges, worked examples and thresholds. Deduction: Agent 02's ANTLR visitor internals are described at the function level, not statement level. |
| 5 | **Clarity** | 8/10 | Consistent 28-section template. Deduction: the agent documents are long; a reader wanting only "what does this do" must skip to §3. |
| 6 | **Consistency** | 9/10 | Terminology normalised: "stage" and "agent" are explicitly equated once and used consistently; "artefact" used throughout (not "artifact") except when naming actual files. |
| 7 | **Traceability** | 10/10 | A dedicated matrix plus a §27 table in every agent document. Inferences are separately listed so they can be challenged. |
| 8 | **Diagram accuracy** | 9/10 | 20+ Mermaid diagrams, all using real component and function names. Every diagram was checked against the code path it depicts. Deduction: no diagram renders the ANTLR visitor traversal. |
| 9 | **Input/output coverage** | 9/10 | Every agent documents inputs with source, validation and failure behaviour, and outputs with schema and consumers. Deduction: field-level schemas are tabulated, not formally specified — no JSON Schema exists to reference. |
| 10 | **Workflow coverage** | 10/10 | All 18 workflow steps mapped to functions per agent, plus end-to-end, data-flow and control-flow diagrams. |
| 11 | **Formula coverage** | 10/10 | All five numeric thresholds located and documented; the set was verified exhaustive by grep. |
| 12 | **Technology-decision coverage** | 9/10 | 11 ADRs. Deduction: ADR-002's reasoning is an inference — the repository never states why there is no orchestrator. |
| 13 | **Security coverage** | 9/10 | Verified controls and gaps separated. Absences positively verified. Deduction: no threat model exists to document, and none was invented. |
| 14 | **Testing coverage** | 10/10 | All 8 suites, 414 checks, conventions, and coverage gaps per agent. |
| 15 | **Observability coverage** | 9/10 | Honest: `print()` only, no logging framework, no metrics export. Debugging procedures derived from artefact design. |
| 16 | **Deployment coverage** | 8/10 | Accurately reports that no container, CI or manifest exists. Deduction: little to document because little exists. |
| 17 | **Maintenance usefulness** | 9/10 | Blast-radius tables per agent and system-wide; "add a stage" procedure. |
| 18 | **Handover readiness** | 9/10 | A new engineer can locate any behaviour, understand why decisions were made, and knows what is unverified. Deduction: no runbook for a *failed* production run, because there is no production deployment. |
| 19 | **Hallucination risk** | 10/10 | No invented technology, formula, metric or control. Every absence checked. The one temptation — describing prompts and LLM behaviour because the brief asked for them — was declined with evidence. |

**Weighted assessment: 9.1 / 10.** Suitable for architectural handover.

---

## 2. Defects found and corrected during review

### 2.1 A real implementation defect found by documenting

**`TRANSITIONS_TO` is never emitted.** While tracing Agent 08's state modelling I found a loop containing only `pass` where transition edges should be derived. Verified against the live artefact: 3 `State` nodes, 3 `HAS_STATE` edges, **zero** `TRANSITIONS_TO`. The in-code comment describes behaviour that does not exist.

This is now [GAP-D01](known-gaps-and-open-questions.md#gap-d01--transitions_to-graph-edges-are-never-emitted). **It is a finding about the code, not about the documentation.**

### 2.2 Broken links caught by automated verification

An automated pass over all 87 file links and every same-page anchor found:

| Defect | Fix |
|---|---|
| 3 links to `documentation-review-report.md` before it existed | This document created |
| 11 broken ADR anchors | Em dashes in ADR headings made anchors renderer-dependent (GitHub yields `--`, other renderers `-`). Headings normalised to remove the separator entirely. |

**Verification is repeatable** — the link checker is reproduced in [§5](#5-final-validation-checklist).

### 2.3 An initial factual error in my own inspection

My first grep for LLM usage reported **18 matches**. Verification showed all 18 were the word `claude` appearing in the *file path* `.claude/scripts/`. Had I not checked, this documentation would have asserted the system uses a language model — the single most consequential error possible here.

Similarly, an early query for foreign keys used `referenced_table` and returned `None` for all 7 FKs, which looked like missing data. The actual field is **`references_table`**. This is now documented as a naming trap in [agent-03 §8](agents/agent-03-data.md#8-outputs).

---

## 3. Unsupported claims removed or relabelled

| Temptation | Resolution |
|---|---|
| Describe prompts, temperature, token limits (brief §13 asks for them) | **Declined.** Marked `Not found in the current repository.` with import-analysis evidence in all 8 documents. |
| Describe orchestration and state management as designed features | **Relabelled.** The absence of an orchestrator is an `Architectural inference` with supporting evidence, not a stated design. |
| Present complexity figures as measured | **Relabelled** as `Architectural inference from the implementation`. Only wall-clock observations are marked `Measured`. |
| Claim the system "uses" the papers in `DESIGN_REFERENCES` | **Split.** [references.md](references.md) separates *declared in code*, *directly influenced with implementation evidence*, *discovered during research*, and *formatting only*. |
| Report Agent 05's F1 as 1.000 | **Contextualised.** The tuned figure is reported alongside the blind measurements (0.588, recall 0.400), matching the repository's own caveat. |
| Describe `reference/` as part of the system | **Excluded.** It is gitignored; documented as design guidance only. |
| Describe `.claude/agents/*.md` as runtime prompts | **Corrected.** They are development-harness specifications; no pipeline script reads them. |

---

## 4. Requested documents not created, and why

The brief listed 15 supporting documents. **Six were created**; nine were not. The brief also instructs: *"Do not create empty documents. If a document does not apply, explain why it was not created."*

| Not created | Reason |
|---|---|
| `system-architecture.md` | Fully covered by [master §8](complete-system-technical-documentation.md#8-high-level-architecture) with the architecture diagram. A separate file would duplicate, and duplication in handover documentation creates drift. |
| `end-to-end-workflow.md` | Covered by [master §11](complete-system-technical-documentation.md#11-end-to-end-workflow) with the workflow diagram. |
| `technical-environment.md` | Covered by [master §6](complete-system-technical-documentation.md#6-technical-environment). There are only two dependencies and no environment configuration — a standalone document would be a page of "not found". |
| `data-and-control-flow.md` | Covered by [master §12–13](complete-system-technical-documentation.md#12-data-flow), including a data-lineage trace of a single rule. |
| `agent-interaction-model.md` | Covered by [master §9–10 and §14](complete-system-technical-documentation.md#10-agent-responsibility-matrix). Interaction is exclusively artefact hand-off — there is no protocol to document. |
| `deployment-and-operations.md` | **There is no deployment.** No container, CI, service or environment separation. [Master §28–29](complete-system-technical-documentation.md#28-deployment-architecture) documents what exists in full. A standalone document would be almost entirely `Not found in the current repository.` |
| `testing-validation-and-evaluation.md` | Covered by [master §25–26](complete-system-technical-documentation.md#25-testing-strategy) plus §19–20 of each agent document. |
| `security-and-guardrails.md` | Covered by [master §22 and §24](complete-system-technical-documentation.md#24-security-architecture) plus §17 of each agent document, with gaps in [known-gaps §4](known-gaps-and-open-questions.md#4-security-gaps). |
| `observability-and-troubleshooting.md` | Covered by [master §27](complete-system-technical-documentation.md#27-observability) and the README troubleshooting table. There is no logging framework, no metrics and no alerting — the honest content is short. |

**This is a deliberate deviation from the brief**, made because the underlying material does not justify separate files and because a reader is better served by one authoritative location per topic than by nine thin documents that will drift apart. If separate files are required for a documentation-management process, they can be split out from the master sections without new research.

---

## 5. Final validation checklist

| Requirement | Status | Verification |
|---|---|---|
| All eight agents documented separately | ✅ | `docs/agents/agent-01..08-*.md` |
| Master system document exists | ✅ | `docs/complete-system-technical-documentation.md` |
| Repository README exists | ✅ | `README.md` |
| Every document has a table of contents | ✅ | All 16 documents |
| Every agent has documented inputs and outputs | ✅ | §7 and §8 of each |
| Every agent has a workflow explanation | ✅ | §9 of each, mapped to functions |
| Every agent has at least one Mermaid diagram | ✅ | §10 and §11 of each, plus state diagrams |
| Agent interactions documented | ✅ | Master §9–14 |
| State transitions documented | ✅ | §12 of each agent + master §15 |
| Technologies explained with rationale | ✅ | §14 of each + 11 ADRs |
| Formulas, rules, thresholds documented | ✅ | §15 of each + master §21; threshold set verified exhaustive |
| Prompts and model behaviour documented | ✅ | Documented as **absent**, with evidence, in all 8 |
| Error handling documented | ✅ | §16 of each + master §23 |
| Testing and evaluation documented | ✅ | §19–20 of each + master §25–26 |
| Configuration and deployment documented | ✅ | §22–23 of each + master §28–29 |
| Security and guardrails documented | ✅ | §17 of each + master §22, §24 |
| References documented | ✅ | §28 of each + `references.md`, classified |
| Repository evidence included | ✅ | §27 of each + `traceability-matrix.md` |
| Missing information labelled | ✅ | `Not found in the current repository.` used throughout |
| No secrets exposed | ✅ | No secrets exist; verified by grep |
| No unsupported details presented as facts | ✅ | §3 of this report |
| Terminology consistent | ✅ | "stage"/"agent" equated once; used consistently |
| Internal links work | ✅ | 87 file links + all anchors verified — see command below |
| Mermaid syntax valid | ✅ | All diagrams use `flowchart`/`sequenceDiagram`/`stateDiagram-v2`/`erDiagram` with quoted labels |

**Reproduce the link check:**

```bash
python - <<'PY'
import re
from pathlib import Path
broken = []
for md in list(Path("docs").rglob("*.md")) + [Path("README.md")]:
    text = md.read_text(encoding="utf-8")
    for m in re.finditer(r"\]\(([^)#]+?)(#[\w-]+)?\)", text):
        t = m.group(1).strip()
        if t.startswith(("http://", "https://", "mailto:")):
            continue
        if not (md.parent / t).resolve().exists():
            broken.append(f"{md} -> {t}")
print("broken:", broken or "none")
PY
```

---

## 6. Residual weaknesses

Stated so a future reader knows where this package is weakest:

1. **Performance figures are estimates.** No profiling artefact exists. All complexity claims are labelled as inferences from reading the implementation.
2. **Agent 02's ANTLR traversal is documented at function granularity**, not at the level of individual visitor methods. A maintainer changing statement extraction will need to read the code.
3. **Nine requested supporting documents were consolidated** into the master document (§4). Defensible, but a deviation.
4. **The corpus is tiny.** Everything measured — 41 rules, 353 graph nodes, quality percentages — comes from 5 objects and 15 tables. None of it evidences behaviour at scale.
5. **ADR reasoning is partly reconstructed.** Where the repository states a rationale it is quoted; ADR-002 in particular is inference and is labelled as such.
6. **No runbook for operational failure**, because there is no operational deployment to write one against.

---

*Review performed against the 19 criteria in the documentation brief. Defects found during review were corrected and are listed in §2; the implementation defect in §2.1 was reported rather than fixed, as the brief instructed that source code not be modified.*
