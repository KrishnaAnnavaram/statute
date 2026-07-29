#!/usr/bin/env python3
"""
Stage 7: BRD SYNTHESIS (deterministic, no LLM)
========================================================

Assembles every upstream artifact into a single specification document that
four different readers can each use:

    a business sponsor  - what the system does and what it costs to change
    a business analyst  - the rules, in reviewable and signable form
    a build team        - enough detail to rebuild the system from scratch
    a machine           - stable identifiers and a companion JSON index

WHY THIS AGENT WAS REDESIGNED
-----------------------------
The predecessor produced a competent reverse-engineering report and called it
a Business Requirements Document. Measured problems with that output:

  - the executive summary described the ANALYSIS ("124 statements parsed"),
    never the business
  - the word "scope" did not appear anywhere in the document
  - identifiers leaked into prose a reader cannot parse: "PROC-.SP_TRANSFER_
    FUNDS is a procedure classified as SINGLE_RECORD_TRANSACTION"
  - computed findings were silently discarded, including a HIGH severity
    transaction hazard and all 20 procedure parameters — the system's actual
    interface contract
  - no traceability matrix, despite every join being available and exact
  - no glossary, no stakeholder guidance, no navigation

DESIGN DECISIONS
----------------
1.  Business language everywhere. `lib_business_language` is the single
    translation point; machine identifiers are carried alongside prose, never
    substituted for it, so the same sentence serves a sponsor and a builder
    and a machine can still recover the join key.

2.  Structured in four parts by AUDIENCE, not by pipeline stage. Aghajani et
    al. (ICSE 2020) find documentation needs are task-dependent; one
    undifferentiated voice serves nobody.

3.  Rules carry SBVR modality. An enforced database constraint is ALETHIC —
    violation is impossible, "it is necessary that". A code guard is DEONTIC —
    violation is possible, which is why enforcement code exists, "it is
    obligatory that". We compute this distinction upstream and previously
    flattened it into a uniform "the system SHALL".

4.  A traceability matrix is published. Twenty years of IR-based traceability
    research fights for 19-32% precision on INFERRED links; ours are
    constructed from statement_id and are exact. It is the one place this
    pipeline categorically beats the state of the art.

5.  Human annotations survive regeneration. Every commercial tool in this
    space (IBM ADDI, CAST, EvolveWare, Micro Focus Business Rule Manager) is
    built around a human curation loop, because the domain knowledge that
    makes a rule meaningful is not recoverable from code (Biggerstaff's
    concept assignment problem). Annotations live in a sidecar keyed by stable
    id; machine facts regenerate, human meaning persists.

6.  Honest epistemology. Chikofsky & Cross (1990) separate REDOCUMENTATION
    (same abstraction level, near-certain) from DESIGN RECOVERY (higher
    abstraction, inferential). Each part states which it is, so a reader can
    calibrate trust rather than guess.

DESIGN REFERENCES
-----------------
  ISO/IEC/IEEE 29148:2018       requirement attributes and document structure
  OMG SBVR 1.5                  alethic vs deontic modality, obligation phrasing
  IIBA BABOK v3                 requirements classification, scope, glossary
  Chikofsky & Cross (1990)      redocumentation vs design recovery
  Biggerstaff et al. (1993)     concept assignment: why humans must annotate
  Aghajani et al. (ICSE 2020)   documentation needs are task-dependent
  Lethbridge et al. (2003)      regenerable docs beat hand-maintained ones
  Cosentino et al. (WCRE 2013)  controlled vocabulary linking terms to code
  EARS (Mavin et al., Rolls-Royce) formal requirement phrasing
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_business_language import (  # noqa: E402
    humanise, object_title, entity_title, object_kind_phrase, shape_phrase,
    anchor, sentence_case, plain_type, humanise_condition, humanise_identifiers,
)

DESIGN_REFERENCES = [
    {"work": "ISO/IEC/IEEE 29148:2018 Requirements Engineering",
     "applied": "Requirement attribute schema (Id, Heading, Text, Source, Rationale, "
                "Type, Verification Method); unresolvable attributes are shown as "
                "explicit blanks rather than omitted, so they read as action items."},
    {"work": "OMG SBVR 1.5 (Semantics of Business Vocabulary and Business Rules)",
     "applied": "Alethic modality ('it is necessary that') for rules the database "
                "makes impossible to violate; deontic ('it is obligatory that') for "
                "rules enforced by code, which can be violated."},
    {"work": "IIBA BABOK v3",
     "applied": "Scope statement, business glossary, and honest classification of "
                "these requirements as Solution/Functional rather than Business."},
    {"work": "Chikofsky & Cross (1990), IEEE Software 7(1)",
     "applied": "Each part declares whether it is redocumentation (near-certain) or "
                "design recovery (inferential)."},
    {"work": "Biggerstaff, Mitbander & Webster (1993), concept assignment problem",
     "applied": "Domain concepts cannot be recovered from source; the document "
                "provides an annotation layer for humans to supply them instead of "
                "pretending they were extracted."},
    {"work": "Aghajani et al. (ICSE 2020), practitioners' perspective",
     "applied": "Document is partitioned by audience because documentation needs "
                "are task-dependent."},
    {"work": "Mavin et al., EARS (Easy Approach to Requirements Syntax)",
     "applied": "Formal requirement statements alongside plain-English description."},
]

CONFIDENCE_MARK = {
    "confirmed": "Confirmed", "high": "High", "medium": "Medium", "low": "Needs review",
}
SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def generate_run_version() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H.%M.%S.") + f"{now.microsecond // 1000:03d}Z"


def load_run(root: str, run: str, artifact_filename: str) -> tuple:
    root_path = Path(root)
    if run == "latest":
        run_version = json.loads((root_path / "latest.json").read_text(encoding="utf-8"))["run_version"]
    else:
        run_version = run
    return json.loads((root_path / run_version / artifact_filename).read_text(encoding="utf-8")), run_version


# ---------------------------------------------------------------------------
# Annotation sidecar — the curation layer
# ---------------------------------------------------------------------------

def load_annotations(path: Path) -> dict:
    """
    Human knowledge keyed by stable id, merged in at synthesis time.

    Static analysis can prove that a threshold of 365 days exists; it can never
    discover that the threshold is mandated by regulation rather than chosen.
    That sentence is the most valuable in the document and there is nowhere in
    a regenerate-from-scratch pipeline for it to live — which is why every
    commercial tool in this space ships a curation workbench.

    Machine facts regenerate every run; this file is never written by the
    pipeline, only read.
    """
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("annotations", data) if isinstance(data, dict) else {}


def annotation_for(annotations: dict, key: str) -> dict:
    entry = annotations.get(key)
    return entry if isinstance(entry, dict) else ({"note": entry} if entry else {})


# ---------------------------------------------------------------------------
# Requirement statements — SBVR modality + EARS
# ---------------------------------------------------------------------------

_DDL_KINDS = {"ddl_check_constraint", "ddl_virtual_column", "ddl_unique_constraint",
              "ddl_unique_index", "ddl_view_filter"}


def rule_modality(rule: dict) -> str:
    """
    SBVR splits rules by whether violation is POSSIBLE.

    A database constraint that is ENABLED and VALIDATED makes violation
    impossible — that is a definitional (alethic) rule. A guard in code that
    raises an exception exists precisely because violation is possible — that
    is a behavioural (deontic) rule. Collapsing both into "the system SHALL"
    discards a distinction we already compute.
    """
    kind = rule["source"]["kind"]
    if kind in _DDL_KINDS and rule.get("is_enforced") is not False:
        return "alethic"
    return "deontic"


def formal_statement(rule: dict) -> str:
    kind = rule["source"]["kind"]
    cond = rule.get("condition_text", "")

    if rule.get("is_enforced") is False:
        return (f"The system is INTENDED to ensure: {cond}. This constraint is currently "
                f"DISABLED in the database and is NOT being enforced.")

    if rule_modality(rule) == "alethic":
        if kind == "ddl_virtual_column":
            return f"It is necessary that this value is always derived as: {cond}."
        if kind in ("ddl_unique_constraint", "ddl_unique_index"):
            return f"It is necessary that no two records share the same {cond}."
        if kind == "ddl_view_filter":
            return f"It is necessary that only records where {cond} are exposed."
        return f"It is necessary that {cond}."

    if kind == "variable_derivation":
        return f"It is obligatory that this value is calculated as: {cond}."
    if kind == "cursor_eligibility":
        return f"It is obligatory that only records where {cond} are processed."
    if rule.get("structural_pattern") == "EXISTENCE_CHECK":
        raises = f", raising {rule['raises']}" if rule.get("raises") else ""
        return f"It is obligatory that the operation is rejected unless {cond}{raises}."
    if rule.get("raises"):
        return (f"It is obligatory that the operation is rejected when {cond}, "
                f"raising {rule['raises']}.")
    if rule.get("outcome_text"):
        return (f"When {cond}, it is obligatory that the system "
                f"{humanise_identifiers(rule['outcome_text'])}.")
    return f"When {cond}, it is obligatory that the system applies the handling described above."


def verification_method(rule: dict) -> str:
    """
    29148 requires a verification method per requirement. Two are derivable.

    A rule the database enforces can be verified by reading the schema —
    Inspection. A rule enforced by a code path can only be verified by
    exercising it — Test.
    """
    if rule["source"]["kind"] in _DDL_KINDS:
        return "Inspection (database schema)" if rule.get("is_enforced") is not False \
            else "Inspection — currently DISABLED, verify intent with data owner"
    return "Test (exercise the code path)"


def requirement_type(rule: dict) -> str:
    return {"CALCULATION": "Functional — calculation",
            "VALIDATION": "Functional — validation",
            "LIMIT_CHECK": "Functional — threshold",
            "ROUTING": "Functional — routing",
            "ERROR_HANDLING": "Non-functional — resilience",
            "COMPLIANCE": "Non-functional — compliance"}.get(rule["category"], "Functional")


_PROVENANCE_TAIL = re.compile(
    r"\s*(?:Implemented|Defined|Declared)\s+in\s+.*?,\s*line\s+\d+\.?", re.IGNORECASE)
_PROVENANCE_PAREN = re.compile(r"\s*\([A-Z]{3,6}-[^)]*?,\s*line\s+\d+\)", re.IGNORECASE)


def humanise_description(text: str, object_names: dict, table_titles: dict,
                         condition: str = "") -> str:
    """
    Upstream descriptions embed provenance and raw identifiers in prose:
    "...and e_account_not_found is raised (PROC-.SP_TRANSFER_FUNDS, line 30)."

    That is correct for an artifact and unreadable in a document — and the
    provenance is already shown as a labelled attribute beside the rule, so
    repeating it inside the sentence is duplication as well as noise.
    """
    if not text:
        return ""
    out = _PROVENANCE_TAIL.sub("", text)
    out = _PROVENANCE_PAREN.sub("", out)
    if condition and condition in out:
        out = out.replace(condition, humanise_condition(condition))
    # Exception and parameter names (e_insufficient_balance, p_amount) read as
    # code, not as business language, wherever they survive in prose.
    out = re.sub(r"([ep]_[a-zA-Z0-9_$#]+)", lambda m: humanise(m.group(1)), out)
    for oid, name in object_names.items():
        out = out.replace(oid, name)
    # Table names arrive in whatever case the source used (`accounts`).
    for raw, title in table_titles.items():
        out = re.sub(rf"\b{re.escape(raw)}\b", title, out, flags=re.IGNORECASE)
    out = re.sub(r"\s+([.,;])", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    if out and not out.endswith((".", "!", "?")):
        out += "."
    return out


def rule_source_phrase(src: dict, object_names: dict) -> str:
    kind = src.get("kind", "")
    if kind.startswith("ddl_"):
        target = src.get("table") or src.get("view") or "the schema"
        detail = src.get("constraint_name") or src.get("index_name") or src.get("column")
        return f"Database definition of {entity_title(target)}" + (f" ({detail})" if detail else "")
    oid = src.get("object_id", "")
    where = object_names.get(oid, object_title(oid))
    line = src.get("line")
    return f"{where}" + (f", line {line}" if line else "")


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def detect_gaps(inventory, parser_artifact, data_artifact, logic_artifact, rules_artifact,
                diagrams_artifact, logic_records, object_names) -> list:
    gaps, gid = [], [0]

    def add(gap_type, severity, title, description, source, **extra):
        gid[0] += 1
        gaps.append({"gap_id": f"GAP-{gid[0]:03d}", "gap_type": gap_type, "severity": severity,
                     "title": title, "description": description, "detected_in": [source], **extra})

    for f in inventory.get("summary", {}).get("files_with_warnings", []):
        add("FILE_WARNING", "low", f"Source file warning: {f['file']}",
            "; ".join(f.get("warnings", [])), "inventory")

    for i in parser_artifact.get("issues", []):
        if i["type"] == "syntax_error":
            add("PARSE_FAILURE", "critical", f"Could not read source: {i.get('file', '?')}",
                f"{i['message']} Anything defined in this file is missing from this document.",
                "parser")
        elif i["type"] == "unresolved_reference":
            add("UNRESOLVED_CALL", "high",
                f"Call to something outside this codebase in {object_names.get(i.get('object_id'), i.get('object_id', '?'))}",
                f"{i['message']} The behaviour of the called routine is unknown and must be "
                f"obtained separately before rebuilding.", "parser")

    for table_name, table in data_artifact.get("tables", {}).items():
        for col in table.get("columns", []):
            if col.get("enum_source") == "comment_only":
                add("UNDOCUMENTED_ENUM", "medium",
                    f"Permitted values not enforced: {entity_title(table_name)} — {humanise(col['name'])}",
                    f"Valid values appear only in a source comment, not as a database rule: "
                    f"{', '.join(col.get('enum_values', []))}. Data may already violate them.",
                    "data")

    for r in rules_artifact.get("business_rules", []):
        if r.get("requires_sme_review"):
            add("SME_REVIEW_REQUIRED", "high",
                f"Needs business confirmation: {r['name']} ({r['rule_id']})",
                r["description"], "rules", related_rule_ids=[r["rule_id"]])
        elif r["confidence"] == "medium":
            add("MEDIUM_CONFIDENCE_RULE", "low",
                f"Worth confirming: {r['name']} ({r['rule_id']})",
                "This rule is likely correct but was inferred rather than stated outright.",
                "rules", related_rule_ids=[r["rule_id"]])
        if r.get("is_enforced") is False:
            add("CONSTRAINT_DISABLED", "high", f"Rule not enforced by the database: {r['name']}",
                "The database records this rule but is not applying it. Existing data may "
                "already violate it and new data will not be stopped.", "data",
                related_rule_ids=[r["rule_id"]])

    for oid, rec in logic_records.items():
        name = object_names.get(oid, object_title(oid))
        for loop in rec.get("loops") or []:
            if loop.get("warning"):
                add("LOOP_RISK", "high", f"Loop with no visible exit in {name}",
                    loop["warning"], "logic")
        for hz in (rec.get("transactions") or {}).get("hazards", []):
            sev = {"high": "high", "medium": "medium"}.get(hz.get("severity"), "low")
            add("TRANSACTION_HAZARD", sev,
                f"Transaction behaviour to preserve in {name}: {humanise(hz['hazard'])}",
                hz.get("explanation", ""), "logic")
        cx = (rec.get("complexity") or {}).get("cyclomatic", {})
        if cx.get("exceeds_threshold"):
            add("HIGH_COMPLEXITY", "medium", f"Unusually complex process: {name}",
                f"This process has {cx.get('score')} independent decision paths against a "
                f"threshold of {cx.get('threshold')}. It is harder to test exhaustively and "
                f"is a candidate for being split up when rebuilt.", "logic")

    for w in (diagrams_artifact or {}).get("warnings", []):
        if w["kind"] == "OVERSIZE":
            add("DIAGRAM_OVERSIZE", "medium",
                f"Process too large to diagram comfortably: "
                f"{object_names.get(w.get('object_id'), w['diagram'])}",
                f"{w['detail']}. Every decision and error path is still shown — nothing was "
                f"dropped — but this is a candidate for decomposition.", "diagram")
        elif w["kind"] == "DETAIL_COLLAPSED":
            add("DIAGRAM_DETAIL_COLLAPSED", "low", f"Diagram detail merged: {w['diagram']}",
                f"{w['detail']}. Straight-line steps were merged for readability; decisions, "
                f"loops and error paths are shown in full.", "diagram")
        elif w["kind"] == "DIAGRAM_NOTE":
            add("DIAGRAM_NOTE", "low", f"Observation from {w['diagram']}", w["detail"], "diagram")

    return gaps


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

class Doc:
    """Collects markdown and records headings so the contents page can link them."""

    def __init__(self):
        self.lines = []
        self.toc = []       # (level, text, anchor)

    def h(self, level: int, text: str, in_toc: bool = True):
        a = anchor(text)
        self.lines.append(f"{'#' * level} {text}\n")
        if in_toc:
            self.toc.append((level, text, a))

    def p(self, text: str = ""):
        self.lines.append(text + "\n" if text else "")

    def raw(self, text: str):
        self.lines.append(text)

    def table(self, headers: list, rows: list):
        if not rows:
            return
        self.lines.append("| " + " | ".join(headers) + " |")
        self.lines.append("|" + "---|" * len(headers))
        for r in rows:
            self.lines.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
        self.lines.append("")

    def mermaid(self, text: str):
        self.lines.append("```mermaid")
        self.lines.append(text.rstrip())
        self.lines.append("```\n")

    def render(self) -> str:
        body = "\n".join(self.lines)
        return body

    def contents_block(self) -> str:
        out = ["<!-- CONTENTS -->", "## Contents\n"]
        for level, text, a in self.toc:
            # Depth 5 is individual rules — 41 of them would swamp the contents
            # page and bury the chapter structure a reader is looking for.
            if level <= 1 or level > 4:
                continue
            indent = "  " * max(0, level - 2)
            out.append(f"{indent}- [{text}](#{a})")
        out.append("")
        return "\n".join(out)


def build_document(ctx: dict) -> str:
    d = Doc()
    A = ctx["annotations"]
    rules = ctx["rules_artifact"]["business_rules"]
    object_names = ctx["object_names"]
    logic_records = ctx["logic_records"]
    parser_records = ctx["parser_records"]
    tables = ctx["data_artifact"].get("tables", {})
    diagrams = ctx["diagrams_artifact"]
    diagrams_dir = ctx["diagrams_dir"]
    gaps = ctx["gaps"]

    def diagram_text(fname):
        p = diagrams_dir / fname
        return p.read_text(encoding="utf-8") if p.exists() else None

    # ---------------------------------------------------------------- Title
    d.h(1, f"{ctx['system_name']} — Business Requirements Document", in_toc=False)
    d.p()
    d.p("> **What this document is.** A Business Requirements Document for an existing "
        "Oracle PL/SQL system, recovered automatically from its source code. It is written so "
        "that a business reader can understand what the system does, a business analyst "
        "can review and sign off its rules, and a development team can rebuild the system "
        "from it without reading the original code.")
    d.p()
    d.p("> **What it is not.** It does not say *why* the business wanted these behaviours. "
        "That intent was never written into the code and cannot be recovered from it. "
        "Section 13 lists every place a person needs to supply it.")
    d.p()

    # ------------------------------------------------------ Document control
    d.h(2, "Document Control")
    up = ctx["upstream"]
    d.table(["Item", "Value"], [
        ["Document type", "Business Requirements Document (BRD)"],
        ["System", ctx["system_name"]],
        ["Generated", ctx["generated_at"]],
        ["Generated by", "Deterministic analysis pipeline — Python analysers driven by an "
                         "AI agent harness. No AI model wrote or judged any content in this "
                         "document; every statement is derived by rule from source code."],
        ["Source analysed", f"{ctx['stats']['files']} files, {ctx['stats']['loc']:,} lines of code"],
        ["Analysis run", up.get("parser_run_version", "—")],
        ["Human annotations", f"{len(A)} applied" if A else "none supplied yet — see section 13"],
        ["Status", "Draft for review — not yet confirmed by a business owner"],
    ])
    d.p("**Approval.** This document has not been reviewed or approved. It records what "
        "the code does, not what the business intends.")
    d.p()
    d.table(["Role", "Name", "Date", "Signature"],
            [["Business owner", "", "", ""], ["Business analyst", "", "", ""],
             ["Technical lead", "", "", ""], ["Data owner", "", "", ""]])

    # --------------------------------------------------------- How to read
    d.h(2, "How to Read This Document")
    d.p("The document is in four parts. You do not need to read all of them.")
    d.table(["If you are…", "Read", "You will learn"], [
        ["A sponsor or manager", "Part I", "What the system does, what it covers, what it costs to change"],
        ["A business analyst", "Parts I and II", "Every rule the system enforces, in reviewable form"],
        ["A developer or architect", "Parts II and III", "Everything needed to rebuild it"],
        ["An auditor or tester", "Part IV", "Where each rule lives in the source, and what is uncertain"],
        ["A machine", "`brd_index.json`", "The same content as structured data"],
    ])
    d.p()
    d.p("**How certain is each part?** Static analysis is not equally sure of everything, "
        "so each part says which it is:")
    d.table(["Marking", "Meaning"], [
        ["**Recorded**", "Read directly from the source. Near-certain — the code says this."],
        ["**Recovered**", "Inferred from code structure. Very likely, but the business "
                          "meaning behind it is interpretation."],
        ["**Needs review**", "Flagged for a person to confirm. Do not rely on it yet."],
    ])

    # ================================================================ PART I
    d.h(2, "Part I — Business View")
    d.p("*Reliability of this part: **Recorded**. Everything here is counted or read "
        "directly from the source code.*")

    d.h(3, "1. Executive Summary")
    caps = ctx["capabilities"]
    d.p(f"**{ctx['system_name']}** is a banking system that performs "
        f"**{len(caps)} distinct business capabilities** over "
        f"**{len(tables)} kinds of business record**.")
    d.p()
    d.p("In plain terms, the system can:")
    for c in caps:
        d.p(f"- **{c['title']}** — {c['summary']}")
    d.p()
    high_gaps = [g for g in gaps if g["severity"] in ("critical", "high")]
    d.p(f"**{len(rules)} business rules** were recovered from the code, every one traced "
        f"to the exact line that implements it. "
        f"**{len([r for r in rules if r['confidence'] == 'confirmed'])}** are certain; "
        f"**{len([r for r in rules if r.get('requires_sme_review')])}** need a person to "
        f"confirm what they mean.")
    d.p()
    if high_gaps:
        d.p(f"**Before relying on this document**, {len(high_gaps)} significant matters need "
            f"attention — see section 13. The most important are:")
        for g in high_gaps[:4]:
            d.p(f"- {g['title']}")
    d.p()
    note = annotation_for(A, "executive_summary").get("note")
    if note:
        d.p(f"> **Business context (added by a reviewer):** {note}")

    d.h(3, "2. Scope")
    d.p("**In scope.** This document describes, completely, the behaviour implemented in "
        "the source code supplied for analysis:")
    d.table(["Included", "Count", "Meaning"], [
        ["Business capabilities", len(caps), "Distinct things the system can do"],
        ["Business rules", len(rules), "Decisions, calculations, limits and checks it enforces"],
        ["Business records", len(tables), "Kinds of information it stores"],
        ["Data fields", ctx["stats"]["columns"], "Individual pieces of information held"],
        ["Interfaces", ctx["stats"]["parameters"], "Values passed in and out of the system"],
    ])
    d.p("**Out of scope.** These are genuinely absent and must be obtained elsewhere "
        "before any rebuild:")
    d.p("- **Why the business chose these rules.** Thresholds, rates and limits are "
        "recorded, but the policy or regulation behind them is not in the code.")
    d.p("- **Anything that calls this system.** Schedulers, screens, batch jobs and "
        "external systems are outside the supplied source.")
    d.p("- **Volumes, timings and service levels.** How many records, how often, and how "
        "fast are operational facts, not code facts.")
    d.p("- **Security and access control.** Who is permitted to run these processes is "
        "not expressed in the analysed code.")
    d.p("- **Data quality of existing records.** Rules are described as written; whether "
        "current data complies is a separate exercise.")

    d.h(3, "3. Business Glossary")
    d.p("Every term used in this document, and the technical name behind it. This is the "
        "bridge between business language and the code — and the place to record what "
        "each term actually means to the business.")
    gl = ctx["glossary"]
    d.table(["Business term", "Technical name", "What it holds", "Used by", "Business meaning"],
            [[g["term"], f"`{g['identifier']}`", g["type"], g["used_by"],
              annotation_for(A, g["key"]).get("note", "_to be supplied_")] for g in gl])
    d.p(f"*{len([g for g in gl if not annotation_for(A, g['key']).get('note')])} terms still "
        f"need a business definition. See section 13 for how to supply them.*")

    d.h(3, "4. What the System Does")
    d.p("Each capability, in business terms. Full specifications are in Part III.")
    for c in caps:
        d.p(f"**{c['title']}** — {c['kind_label']}")
        d.p(f"{c['summary']}")
        d.p(f"Enforces {c['rule_count']} rule{'s' if c['rule_count'] != 1 else ''}; "
            f"touches {c['tables_phrase']}.")
        d.p()
    dt = diagram_text("system_dataflow.mmd")
    if dt:
        d.h(4, "Figure 1 — How the capabilities use the business records")
        d.mermaid(dt)
        d.p("*Rounded boxes are business processes; cylinders are stored records. Arrows "
            "show what each process does to each record: C = creates, R = reads, "
            "U = updates, D = deletes. Amber processes are unusually complex.*")
    crud = (diagrams or {}).get("crud_matrix", {}).get("markdown", "")
    if crud:
        d.h(4, "Which capability touches which records")
        d.raw(crud + "\n")

    # =============================================================== PART II
    d.h(2, "Part II — Business Rules and Behaviour")
    d.p("*Reliability of this part: **Recovered**. The rules are read from code with "
        "certainty; naming them in business language is interpretation. Anything marked "
        "**Needs review** is not yet dependable.*")

    d.h(3, "5. Business Rules Catalogue")
    d.p("Every rule the system enforces. Each is stated twice — once in plain English, "
        "once in formal language suitable for building and testing — and points at the "
        "exact line of source that implements it.")
    d.p()
    d.p("**Two kinds of rule appear here.** A rule the database itself enforces cannot be "
        "broken, and is written *“it is necessary that…”*. A rule enforced by program code "
        "*can* be broken — that is precisely why the code checks for it — and is written "
        "*“it is obligatory that…”*.")
    d.p()
    by_cat = {}
    for r in rules:
        by_cat.setdefault(r["category"], []).append(r)
    for cat in ["VALIDATION", "LIMIT_CHECK", "CALCULATION", "ROUTING", "COMPLIANCE", "ERROR_HANDLING"]:
        group = by_cat.get(cat)
        if not group:
            continue
        d.h(4, f"5.{['VALIDATION','LIMIT_CHECK','CALCULATION','ROUTING','COMPLIANCE','ERROR_HANDLING'].index(cat)+1} "
               f"{humanise(cat)} rules")
        for r in sorted(group, key=lambda x: x["rule_id"]):
            d.h(5, f"{r['rule_id']} — {r['name']}")
            d.table(["Attribute", "Value"], [
                ["Requirement type", requirement_type(r)],
                ["Confidence", CONFIDENCE_MARK.get(r["confidence"], r["confidence"])],
                ["Applies to", rule_source_phrase(r["source"], object_names)],
                ["How to verify", verification_method(r)],
                ["Owner", annotation_for(A, r["rule_id"]).get("owner", "_to be assigned_")],
                ["Priority", annotation_for(A, r["rule_id"]).get("priority", "_to be assigned_")],
                ["Exact condition in code", f"`{r.get('condition_text', '')}`"
                    if r.get("condition_text") else "—"],
            ])
            if r.get("condition_text"):
                d.p(f"**In plain terms.** {sentence_case(humanise_condition(r['condition_text']))}."
                    + (f" When this happens, the system "
                       f"{humanise_identifiers(r['outcome_text'])}."
                       if r.get("outcome_text") else ""))
            d.p(sentence_case(humanise_description(r["description"], object_names,
                                                   ctx["table_titles"], r.get("condition_text", ""))))
            d.p()
            d.p(f"**Formal statement.** {humanise_description(formal_statement(r), object_names, ctx['table_titles'], r.get('condition_text', ''))}")
            note = annotation_for(A, r["rule_id"]).get("note")
            if note:
                d.p(f"> **Business context (added by a reviewer):** {note}")
            if r.get("is_enforced") is False:
                d.p("> **Warning — not enforced.** The database records this rule but is not "
                    "applying it. Existing records may already break it.")
            if r.get("requires_sme_review"):
                d.p("> **Needs review.** This rule was inferred from code structure and its "
                    "business purpose is not certain. Confirm before relying on it.")
            d.p()

    d.h(3, "6. Record Lifecycles")
    state_files = [(f, m) for f, m in (diagrams or {}).get("diagram_index", {}).items()
                   if m.get("type") == "state"]
    if state_files:
        d.p("Some records move through a defined series of states. The permitted states come "
            "from the database; the moves between them come from the code that performs them.")
        for i, (fname, meta) in enumerate(sorted(state_files), start=1):
            txt = diagram_text(fname)
            if not txt:
                continue
            d.h(4, f"Figure 2.{i} — {entity_title(meta.get('entity', ''))} lifecycle")
            d.mermaid(txt)
            for n in meta.get("notes", []):
                d.p(f"> **Note.** {n}")
            d.p()
    else:
        d.p("No record in this system has a defined set of states with code that moves "
            "between them.")

    d.h(3, "7. Error Handling and Guarantees")
    d.p("What the system promises to do when something goes wrong. These are contracts — "
        "anything calling this system may depend on them.")
    err_rules = [r for r in rules if r["category"] == "ERROR_HANDLING"]
    d.table(["Reference", "Guarantee", "Where"],
            [[r["rule_id"], sentence_case(humanise_description(r["description"], object_names, ctx["table_titles"]).split(".")[0]),
              rule_source_phrase(r["source"], object_names)] for r in err_rules])
    cat = ctx["rules_artifact"].get("error_handling_catalogue", [])
    if cat:
        d.p("**Technical error handling.** The following were judged to be technical "
            "plumbing rather than business behaviour, and are listed for completeness only.")
        d.table(["Where", "Handles", "Note"],
                [[object_names.get(e["source"].get("object_id"), "—"),
                  e.get("condition_text", "—"),
                  "Needs review" if e.get("requires_sme_review") else "Technical only"]
                 for e in cat])

    # ============================================================== PART III
    d.h(2, "Part III — Build Specification")
    d.p("*Reliability of this part: **Recorded**. Structures, types and interfaces are read "
        "directly from source. This part contains what is needed to rebuild the system.*")

    d.h(3, "8. Data Model")
    erd = ctx["erd_path"]
    if erd and erd.exists():
        d.h(4, "Figure 3 — How the business records relate")
        d.mermaid(erd.read_text(encoding="utf-8"))
        d.p("*Solid connectors are relationships declared in the database. Dotted connectors "
            "were inferred from matching names and types and are not guaranteed.*")
    d.p("Every record type, with every field, in build-ready detail. The **Rebuild as** "
        "column gives the equivalent type for a modern data platform.")
    for tname in sorted(tables):
        t = tables[tname]
        d.h(4, f"8.{sorted(tables).index(tname)+1} {entity_title(tname)}")
        meta_bits = []
        if t.get("temporary"):
            meta_bits.append("temporary working table")
        if t.get("partitioning"):
            meta_bits.append("partitioned")
        if t.get("comment"):
            meta_bits.append(t["comment"])
        d.p(f"*Technical name: `{tname}`" + (f" — {'; '.join(meta_bits)}" if meta_bits else "") + "*")
        note = annotation_for(A, f"table:{tname}").get("note")
        if note:
            d.p(f"> **Business meaning (added by a reviewer):** {note}")
        rows = []
        for c in t.get("columns", []):
            flags = []
            if c["name"] in (t.get("primary_key") or []):
                flags.append("identifier")
            if not c.get("nullable", True):
                flags.append("required")
            if c.get("is_virtual"):
                flags.append("calculated")
            if c.get("is_identity"):
                flags.append("auto-numbered")
            default = (c.get("default") or {}).get("value") if isinstance(c.get("default"), dict) else c.get("default")
            rows.append([humanise(c["name"]), f"`{c['name']}`", plain_type(c.get("oracle_type", "")),
                         c.get("pyspark_type", "—"), ", ".join(flags) or "—",
                         f"`{default}`" if default else "—"])
        d.table(["Field", "Technical name", "Holds", "Rebuild as", "Rules", "Default"], rows)
        fks = t.get("foreign_keys") or []
        if fks:
            d.p("**Relationships.**")
            d.table(["This field", "Points to", "On delete", "Enforced?"],
                    [[", ".join(humanise(c) for c in fk["columns"]),
                      f"{entity_title(fk.get('references_table') or '?')}"
                      f" ({', '.join(fk.get('references_columns') or [])})",
                      humanise(fk.get("on_delete", "NO_ACTION")),
                      "Yes" if (fk.get("enforcement") or {}).get("is_enforced") else "**No**"]
                     for fk in fks])
        checks = t.get("check_constraints") or []
        if checks:
            d.p("**Value rules enforced by the database.**")
            d.table(["Rule", "Condition", "Active?"],
                    [[c.get("name", "—"), f"`{c.get('expression', '')}`",
                      "Yes" if (c.get("enforcement") or {}).get("is_enforced", True) else "**No**"]
                     for c in checks])
        d.p()
    seqs = ctx["data_artifact"].get("sequences") or {}
    if seqs:
        d.h(4, "8.x Number generators")
        d.p("Automatically generated reference numbers. A rebuild must preserve these ranges.")
        d.table(["Generator", "Starts at", "Steps by", "Caches", "Used for"],
                [[humanise(k), v.get("start_with"), v.get("increment_by"), v.get("cache"),
                  ", ".join(humanise(u.get("column", "")) for u in
                            ctx["data_artifact"].get("sequence_usages", [])
                            if u.get("sequence") == k) or "—"]
                 for k, v in sorted(seqs.items())])

    d.h(3, "9. Interface Contracts")
    d.p("Exactly how each capability is called and what it gives back. **A rebuild must "
        "preserve these signatures** or every caller breaks.")
    for oid, prec in parser_records.items():
        params = prec.get("parameters") or []
        if not params:
            continue
        d.h(4, f"{object_names.get(oid, object_title(oid))}")
        d.p(f"*Technical name: `{prec.get('name', oid)}`*")
        d.table(["Value", "Technical name", "Direction", "Type", "Meaning"],
                [[humanise(p["name"]), f"`{p['name']}`",
                  {"IN": "Supplied by caller", "OUT": "Returned to caller",
                   "IN OUT": "Supplied and updated"}.get(p.get("mode", "IN"), p.get("mode")),
                  plain_type(p.get("type", "")),
                  annotation_for(A, f"param:{oid}:{p['name']}").get("note", "_to be supplied_")]
                 for p in params])

    d.h(3, "10. Process Specifications")
    d.p("One section per capability: what it is for, what it does step by step, which rules "
        "it applies, and how it behaves inside a transaction.")
    for idx, c in enumerate(caps, start=1):
        oid = c["object_id"]
        rec = logic_records.get(oid, {})
        prec = parser_records.get(oid, {})
        d.h(4, f"10.{idx} {c['title']}")
        d.p(f"*Technical name: `{oid}` — {c['kind_label']}*")
        d.p(f"**Purpose.** {c['summary']}")
        note = annotation_for(A, f"object:{oid}").get("note")
        if note:
            d.p(f"> **Business context (added by a reviewer):** {note}")
        cx = (rec.get("complexity") or {}).get("cyclomatic", {})
        tx = rec.get("transactions") or {}
        d.table(["Characteristic", "Value"], [
            ["Processing style", c["kind_label"]],
            ["Decision paths", f"{cx.get('score', '—')} (threshold {cx.get('threshold', '—')})"
                               + (" — **above threshold**" if cx.get("exceeds_threshold") else "")],
            ["Records touched", c["tables_phrase"]],
            ["Rules enforced", c["rule_count"]],
            ["Transaction boundary", ctx["tx_phrases"].get(oid, "—")],
        ])
        rule_ids = c["rule_ids"]
        if rule_ids:
            d.p("**Rules applied here.**")
            d.table(["Rule", "Statement"],
                    [[rid, next((r["name"] for r in rules if r["rule_id"] == rid), "")]
                     for rid in rule_ids])
        pseudo = rec.get("pseudocode") or []
        if pseudo:
            d.p("**Step by step.** A faithful restatement of the logic — not the original code.")
            d.raw("```text\n" + "\n".join(pseudo) + "\n```\n")
        flow = ctx["flow_by_object"].get(oid)
        if flow:
            txt = diagram_text(flow)
            if txt:
                d.h(5, f"Figure 4.{idx} — {c['title']}: process flow")
                d.mermaid(txt)
                meta = (diagrams or {}).get("diagram_index", {}).get(flow, {})
                if meta.get("rule_ids"):
                    d.p(f"*Decisions are labelled with the rule they enact — "
                        f"{', '.join(meta['rule_ids'][:8])}"
                        f"{' and others' if len(meta['rule_ids']) > 8 else ''}. "
                        f"Full statements are in section 5.*")
                b = meta.get("budget") or {}
                if b.get("collapsed"):
                    d.p(f"> Straight-line steps were merged for readability "
                        f"({'; '.join(b['collapsed'])}). Decisions, loops and error paths are complete.")
                if b.get("oversize"):
                    d.p(f"> This process needs {meta.get('nodes')} steps to show its decisions and "
                        f"error paths. Nothing was dropped, but it is a candidate for splitting up.")
        haz = tx.get("hazards") or []
        if haz:
            d.p("**Transaction behaviour that must be preserved.**")
            d.table(["Severity", "Behaviour", "Why it matters"],
                    [[h.get("severity", "").title(), humanise(h["hazard"]), h.get("explanation", "")]
                     for h in haz])
        d.p()

    d.h(3, "11. Operational Characteristics")
    d.p("Properties a rebuild must preserve that are not business rules.")
    d.table(["Capability", "Style", "Decision paths", "Transaction boundary", "Records touched"],
            [[c["title"], c["kind_label"],
              str(((logic_records.get(c["object_id"], {}).get("complexity") or {})
                   .get("cyclomatic") or {}).get("score", "—")),
              ctx["tx_phrases"].get(c["object_id"], "—"), c["tables_phrase"]] for c in caps])
    all_haz = [(object_names.get(oid, oid), h)
               for oid, rec in logic_records.items()
               for h in (rec.get("transactions") or {}).get("hazards", [])]
    if all_haz:
        d.p("**Transaction and consistency risks across the system.**")
        d.table(["Severity", "Capability", "Behaviour", "Explanation"],
                [[h.get("severity", "").title(), name, humanise(h["hazard"]), h.get("explanation", "")]
                 for name, h in sorted(all_haz, key=lambda x: SEVERITY_ORDER.index(
                     x[1].get("severity", "low")) if x[1].get("severity") in SEVERITY_ORDER else 9)])

    # =============================================================== PART IV
    d.h(2, "Part IV — Assurance and Handover")
    d.p("*Reliability of this part: **Recorded**. Every link below is constructed from "
        "source positions, not inferred from wording.*")

    d.h(3, "12. Requirements Traceability Matrix")
    d.p("Every rule, mapped to where it lives in the source, which records it touches, and "
        "which diagram shows it. Because these links are constructed from exact source "
        "positions rather than guessed from wording, **the matrix is complete and has no "
        "false entries** — each row can be checked in seconds.")
    d.table(["Rule", "Statement", "Capability", "Source line", "Records", "Shown in", "Confidence"],
            [[r["rule_id"], r["name"],
              object_names.get(r["source"].get("object_id"), "Database schema"),
              r["source"].get("line") or "—",
              ctx["rule_tables"].get(r["rule_id"], "—"),
              ctx["rule_figure"].get(r["rule_id"], "—"),
              CONFIDENCE_MARK.get(r["confidence"], r["confidence"])]
             for r in sorted(rules, key=lambda x: x["rule_id"])])

    d.h(3, "13. Gaps, Assumptions and Questions for the Business")
    d.p("Everything this document cannot settle by itself. **This section is the handover "
        "list** — each item is either a question for a person or a risk to manage.")
    if not gaps:
        d.p("No gaps were detected.")
    for sev in SEVERITY_ORDER:
        group = [g for g in gaps if g["severity"] == sev]
        if not group:
            continue
        d.h(4, f"{sev.title()} priority ({len(group)})")
        d.table(["Ref", "Matter", "Detail", "Related rules"],
                [[g["gap_id"], g["title"], humanise_description(g["description"], object_names, ctx["table_titles"]),
                  ", ".join(g.get("related_rule_ids", [])) or "—"] for g in group])
    d.h(4, "How to answer these")
    d.p("Answers belong in the annotation file, not in this document — this document is "
        "regenerated from source every time the code changes, and anything written directly "
        "into it would be lost. Annotations are keyed by the reference shown above and are "
        "merged in automatically on the next run.")
    d.raw("```json\n" + json.dumps({
        "annotations": {
            "BR-001": {"note": "365-day threshold is set by regulation, not policy.",
                       "owner": "Head of Retail Operations", "priority": "Must have"},
            "table:ACCOUNTS": {"note": "The master record for every customer account."},
            "term:ACCOUNTS.BALANCE": {"note": "Cleared balance, excluding pending items."},
            "executive_summary": {"note": "Core retail banking ledger, in service since 2004."}
        }
    }, indent=2) + "\n```\n")
    d.p(f"Save as `{ctx['annotations_filename']}` beside the source folder and re-run the "
        f"pipeline. Machine facts are regenerated; your notes are preserved.")

    d.h(3, "14. Rebuilding This System")
    d.p("A checklist for building a replacement that behaves identically. Work top to bottom "
        "— each step depends on the ones above it.")
    d.table(["#", "Build this", "From section", "Done when"], [
        ["1", "The data structures — every record type, field, type and default",
         "Section 8", f"All {len(tables)} record types created with all "
                      f"{ctx['stats']['columns']} fields"],
        ["2", "The database-enforced rules — keys, relationships, permitted values",
         "Sections 8 and 5", "Every rule marked *it is necessary that* is enforced by the "
                             "platform, not by code"],
        ["3", "The number generators, preserving their current ranges",
         "Section 8", "Reference numbers continue without collision"],
        ["4", "The interfaces — exact names, order, direction and types",
         "Section 9", f"All {ctx['stats']['parameters']} values match; existing callers "
                      f"need no change"],
        ["5", "The business rules enforced in code",
         "Section 5", "Every rule marked *it is obligatory that* has a test that proves it"],
        ["6", "The processing logic for each capability",
         "Section 10", "Step-by-step behaviour matches, including decision order"],
        ["7", "The record lifecycles", "Section 6", "Only the permitted state moves are possible"],
        ["8", "The error contracts and their exact codes",
         "Section 7", "Callers receive the same signals in the same situations"],
        ["9", "The transaction boundaries and consistency behaviour",
         "Sections 10 and 11", "Commit and rollback points preserved; hazards addressed"],
        ["10", "Answers to every open question", "Section 13", "No item left unresolved"],
    ])
    d.p("**Test the rebuild against section 12.** Every rule has a verification method and a "
        "source line. A rebuild is complete when each row of the traceability matrix has a "
        "passing test against it.")
    d.p()
    d.p("**Two warnings for the build team.**")
    d.p(f"1. Rules marked *Needs review* ({len([r for r in rules if r.get('requires_sme_review')])} "
        f"of them) were inferred from code structure. Confirm them before implementing.")
    d.p("2. Any rule the database records but does not enforce is listed as such. Existing "
        "data may already break it — decide whether to enforce it in the new system before "
        "migrating.")

    # ------------------------------------------------------------ Appendices
    d.h(2, "Appendix A — How This Document Was Produced")
    d.p("This document was generated by a deterministic analysis pipeline: a set of Python "
        "analysers driven by an AI agent harness. The harness orchestrates the run; **no AI "
        "model wrote, judged, summarised or invented any content in this document**. Every "
        "sentence is produced by rule from the source code, which is why every statement can "
        "be traced to a line number.")
    d.p()
    d.table(["Stage", "What it did", "Result"], [
        ["1. Inventory", "Catalogued every source file and gave each a stable identifier",
         f"{ctx['stats']['files']} files"],
        ["2. Structure", "Parsed the code into statements and control flow using a formal "
                         "Oracle PL/SQL grammar",
         f"{ctx['stats']['statements']} statements"],
        ["3. Data", "Read the database definitions — records, fields, keys, rules",
         f"{len(tables)} record types"],
        ["4. Logic", "Translated control flow into readable steps; measured complexity; "
                     "traced how each value is calculated",
         f"{len(logic_records)} capabilities"],
        ["5. Rules", "Identified the business decisions and stated them as requirements",
         f"{len(rules)} rules"],
        ["6. Diagrams", "Drew the data flow, process flows and record lifecycles",
         f"{len((diagrams or {}).get('diagram_index', {}))} figures"],
        ["7. Specification", "Assembled this document and the machine-readable index", "—"],
    ])
    d.p("**What this method cannot do.** It reads what the code does. It cannot read what "
        "anyone intended. Where meaning matters — why a threshold is 365 days, who owns a "
        "rule, what a field represents to the business — the document asks rather than "
        "guesses. That is the purpose of section 13.")

    d.h(2, "Appendix B — Reference Scheme")
    d.p("For machine consumers and for anyone cross-checking against the source.")
    d.table(["Reference", "Form", "Example", "Meaning"], [
        ["Rule", "BR-nnn", "BR-001", "A business rule in section 5"],
        ["Gap", "GAP-nnn", "GAP-001", "An open matter in section 13"],
        ["Capability", "TYPE-.NAME", "PROC-.SP_TRANSFER_FUNDS", "A program object"],
        ["Field", "TABLE.COLUMN", "ACCOUNTS.BALANCE", "A single data field"],
    ])
    d.p("The same content is published as `brd_index.json` alongside this document, keyed by "
        "these references, for tools that need to consume it directly.")

    d.h(2, "Appendix C — Method References")
    d.table(["Standard or study", "How it was applied"],
            [[r["work"], r["applied"]] for r in DESIGN_REFERENCES])

    # Splice the contents block in after the opening statement.
    body = d.render()
    marker = "## Document Control"
    toc = d.contents_block()
    return body.replace(marker, toc + "\n" + marker, 1)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def build_context(args, artifacts) -> dict:
    (inventory, parser_artifact, data_artifact, logic_artifact, rules_artifact,
     diagrams_artifact) = artifacts["payloads"]
    parser_root, logic_root = artifacts["parser_root"], artifacts["logic_root"]

    parser_records, logic_records = {}, {}
    for oid, rel in parser_artifact["object_index"].items():
        p = parser_root / rel
        if p.exists():
            parser_records[oid] = json.loads(p.read_text(encoding="utf-8"))
    for oid, rel in (logic_artifact.get("object_index") or {}).items():
        p = logic_root / rel
        if p.exists():
            logic_records[oid] = json.loads(p.read_text(encoding="utf-8"))

    object_names = {oid: object_title(oid) for oid in parser_artifact["object_index"]}
    # Source prose refers to tables in whatever case the code used (`accounts`),
    # so the lookup is keyed on the raw name and matched case-insensitively.
    table_titles = {t: entity_title(t) for t in data_artifact.get("tables", {})}

    rules = rules_artifact["business_rules"]
    rules_by_object = {}
    for r in rules:
        oid = r["source"].get("object_id")
        if oid:
            rules_by_object.setdefault(oid, []).append(r["rule_id"])

    crud = logic_artifact.get("crud_matrix", {}) or {}
    caps = []
    for oid, prec in parser_records.items():
        rec = logic_records.get(oid, {})
        label, blurb = shape_phrase((rec.get("shape") or {}).get("shape", ""))
        tabs = sorted((crud.get(oid) or {}).keys())
        caps.append({
            "object_id": oid, "title": object_names[oid],
            "kind_label": label,
            "summary": blurb,
            "kind_phrase": object_kind_phrase(prec.get("type")),
            "rule_count": len(rules_by_object.get(oid, [])),
            "rule_ids": sorted(rules_by_object.get(oid, [])),
            "tables_phrase": ", ".join(entity_title(t) for t in tabs) or "no stored records",
        })
    caps.sort(key=lambda c: -c["rule_count"])

    # Glossary from the column catalogue — the controlled vocabulary linking
    # business terms to the identifiers that implement them.
    glossary = []
    for c in data_artifact.get("column_catalogue", []):
        if not c.get("used_by_objects"):
            continue
        glossary.append({
            "key": f"term:{c['column_id']}", "term": humanise(c["column"]),
            "identifier": c["column_id"], "type": plain_type(c.get("oracle_type", "")),
            "used_by": ", ".join(object_names.get(o, object_title(o))
                                 for o in c["used_by_objects"][:4]) or "—",
        })
    glossary.sort(key=lambda g: (-len(g["used_by"]), g["term"]))
    glossary = glossary[:60]

    tx_phrases = {}
    for oid, rec in logic_records.items():
        tx = rec.get("transactions") or {}
        commits, rollbacks = len(tx.get("commits") or []), len(tx.get("rollbacks") or [])
        if commits == 0 and rollbacks == 0:
            tx_phrases[oid] = "None of its own — the caller decides when to save or undo"
        else:
            tx_phrases[oid] = (f"Saves its own work ({commits} commit point"
                               f"{'s' if commits != 1 else ''}"
                               + (f", {rollbacks} undo point{'s' if rollbacks != 1 else ''}"
                                  if rollbacks else "") + ")")

    flow_by_object = {m["object_id"]: f
                      for f, m in (diagrams_artifact or {}).get("diagram_index", {}).items()
                      if m.get("type") == "process_flow" and m.get("object_id")}
    rule_figure, fig_no = {}, {}
    for i, c in enumerate(caps, start=1):
        fig_no[c["object_id"]] = f"Figure 4.{i}"
    for r in rules:
        oid = r["source"].get("object_id")
        if oid in fig_no:
            rule_figure[r["rule_id"]] = fig_no[oid]

    rule_tables = {}
    for r in rules:
        src = r["source"]
        if src.get("table"):
            rule_tables[r["rule_id"]] = entity_title(src["table"])
        else:
            tabs = sorted((crud.get(src.get("object_id")) or {}).keys())
            rule_tables[r["rule_id"]] = ", ".join(entity_title(t) for t in tabs[:3]) or "—"

    summary = inventory.get("summary", {})
    stats = {
        "files": summary.get("total_files_included", len(inventory.get("file_index", {}))),
        "loc": summary.get("total_lines_of_code", 0),
        "statements": parser_artifact.get("stats", {}).get("statements_extracted", 0),
        "columns": len(data_artifact.get("column_catalogue", [])),
        "parameters": sum(len(p.get("parameters") or []) for p in parser_records.values()),
    }

    annotations = load_annotations(Path(args.annotations)) if args.annotations else {}

    gaps = detect_gaps(inventory, parser_artifact, data_artifact, logic_artifact,
                       rules_artifact, diagrams_artifact, logic_records, object_names)

    return {
        "system_name": args.system_name, "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": artifacts["upstream"], "inventory": inventory,
        "parser_artifact": parser_artifact, "data_artifact": data_artifact,
        "logic_artifact": logic_artifact, "rules_artifact": rules_artifact,
        "diagrams_artifact": diagrams_artifact, "diagrams_dir": artifacts["diagrams_dir"],
        "erd_path": artifacts["erd_path"], "parser_records": parser_records,
        "logic_records": logic_records, "object_names": object_names,
        "table_titles": table_titles, "capabilities": caps,
        "glossary": glossary, "tx_phrases": tx_phrases, "flow_by_object": flow_by_object,
        "rule_figure": rule_figure, "rule_tables": rule_tables, "stats": stats,
        "annotations": annotations, "annotations_filename": Path(args.annotations).name,
        "gaps": gaps,
    }


def build_machine_index(ctx: dict) -> dict:
    """Same content as structured data, for tools rather than people."""
    return {
        "document": "Business Requirements Document", "schema_version": "2.0",
        "system": ctx["system_name"], "generated_at": ctx["generated_at"],
        "upstream": ctx["upstream"],
        "capabilities": [{"id": c["object_id"], "title": c["title"], "style": c["kind_label"],
                          "rule_ids": c["rule_ids"], "records": c["tables_phrase"]}
                         for c in ctx["capabilities"]],
        "requirements": [{
            "id": r["rule_id"], "heading": r["name"],
            "text": humanise_description(r["description"], ctx["object_names"], ctx["table_titles"]),
            "formal": formal_statement(r), "modality": rule_modality(r),
            "type": requirement_type(r), "confidence": r["confidence"],
            "verification_method": verification_method(r),
            "source": r["source"], "needs_review": bool(r.get("requires_sme_review")),
            "owner": annotation_for(ctx["annotations"], r["rule_id"]).get("owner"),
            "priority": annotation_for(ctx["annotations"], r["rule_id"]).get("priority"),
        } for r in ctx["rules_artifact"]["business_rules"]],
        "glossary": ctx["glossary"],
        "gaps": ctx["gaps"],
        "traceability": [{"rule_id": r["rule_id"], "object_id": r["source"].get("object_id"),
                          "line": r["source"].get("line"),
                          "records": ctx["rule_tables"].get(r["rule_id"]),
                          "figure": ctx["rule_figure"].get(r["rule_id"])}
                         for r in ctx["rules_artifact"]["business_rules"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 7: Business Requirements Document generator")
    ap.add_argument("--inventory-root", default="output/inventory")
    ap.add_argument("--parser-root", default="output/parser")
    ap.add_argument("--data-root", default="output/data")
    ap.add_argument("--logic-root", default="output/logic")
    ap.add_argument("--rules-root", default="output/rules")
    ap.add_argument("--diagram-root", default="output/diagram")
    ap.add_argument("--run", default="latest")
    ap.add_argument("--output-root", default="output/final_report")
    ap.add_argument("--output", default=None)
    ap.add_argument("--system-name", default="PL/SQL Banking System")
    ap.add_argument("--annotations", default="brd_annotations.json",
                    help="Human annotations merged in at synthesis time; never written to.")
    args = ap.parse_args()

    inventory, inv_rv = load_run(args.inventory_root, args.run, "inventory-artifact.json")
    parser_artifact, parser_rv = load_run(args.parser_root, args.run, "parser_artifact.json")
    data_artifact, data_rv = load_run(args.data_root, args.run, "data_artifact.json")
    logic_artifact, logic_rv = load_run(args.logic_root, args.run, "logic_artifact.json")
    rules_artifact, rules_rv = load_run(args.rules_root, args.run, "rules_artifact.json")
    diagrams_artifact, diagram_rv = load_run(args.diagram_root, args.run, "diagrams_artifact.json")

    artifacts = {
        "payloads": (inventory, parser_artifact, data_artifact, logic_artifact,
                     rules_artifact, diagrams_artifact),
        "parser_root": Path(args.parser_root) / parser_rv,
        "logic_root": Path(args.logic_root) / logic_rv,
        "diagrams_dir": Path(args.diagram_root) / diagram_rv / "diagrams",
        "erd_path": Path(args.data_root) / data_rv / "erd.mmd",
        "upstream": {"inventory_run_version": inv_rv, "parser_run_version": parser_rv,
                     "data_run_version": data_rv, "logic_run_version": logic_rv,
                     "rules_run_version": rules_rv, "diagram_run_version": diagram_rv},
    }

    ctx = build_context(args, artifacts)
    document = build_document(ctx)
    index = build_machine_index(ctx)

    versioned = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned else Path(args.output)
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "brd.md").write_text(document, encoding="utf-8")
    (run_dir / "brd_index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    (run_dir / "gaps_register.json").write_text(
        json.dumps({"gaps": ctx["gaps"]}, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned:
        (run_dir / "run_meta.json").write_text(json.dumps(
            {"stage": "7_synthesis", "run_version": run_version, "status": "success",
             "generated_at": ctx["generated_at"], "upstream": ctx["upstream"],
             "counts": {"requirements": len(index["requirements"]), "gaps": len(ctx["gaps"]),
                        "capabilities": len(ctx["capabilities"]),
                        "annotations_applied": len(ctx["annotations"])}},
            indent=2), encoding="utf-8")
        (Path(args.output_root) / "latest.json").write_text(json.dumps(
            {"run_version": run_version, "path": f"{run_version}/brd.md",
             "updated_at": ctx["generated_at"]}, indent=2), encoding="utf-8")

    by_sev = {s: sum(1 for g in ctx["gaps"] if g["severity"] == s) for s in SEVERITY_ORDER}
    print("=== BRD Synthesis Complete ===")
    print(f"Capabilities documented : {len(ctx['capabilities'])}")
    print(f"Requirements            : {len(index['requirements'])}")
    print(f"Glossary terms          : {len(ctx['glossary'])}")
    print(f"Traceability rows       : {len(index['traceability'])}")
    print(f"Open matters            : " + ", ".join(f"{k} {v}" for k, v in by_sev.items() if v))
    print(f"Annotations applied     : {len(ctx['annotations'])}")
    print(f"Document                : {run_dir / 'brd.md'}")
    print(f"Machine index           : {run_dir / 'brd_index.json'}")
    print("========================================")


if __name__ == "__main__":
    main()
