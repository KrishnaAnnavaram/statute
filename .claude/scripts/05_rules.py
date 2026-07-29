#!/usr/bin/env python3
"""
Stage 5: RULES (deterministic, no LLM)
------------------------------------------
Mines business rules from three sources: every IF/ELSIF condition and every
named EXCEPTION_HANDLER in Agent 2's parser output, plus every CHECK
constraint Agent 3 already flagged promotable_to_rule. Classifies each into
a category, scores a confidence level, generates a plain-English name and
description, deduplicates across objects, and groups related rules into
named rule sets.

Design rationale (see design_references in the output artifact):
  - Category signal keywords adapted from the reference COBOL pipeline's
    condition-classifier skill (same six categories: Validation,
    Calculation, Routing, Limit-check, Error-handling, Compliance) — the
    categories are language-agnostic; only the field-naming heuristics
    change (Oracle p_/v_ prefixes vs. COBOL WS-).
  - CHECK constraints and named business exceptions (not WHEN OTHERS) are
    scored at or near the top confidence tier without further inference,
    for the same reason COBOL 88-level conditions are: the check is
    already enforced/named by the source, not inferred from procedural
    logic.
  - Never invents a rule with no source line. Every rule traces back to at
    least one statement_id or DDL constraint name.

Zero LLM calls. 100% deterministic.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DESIGN_REFERENCES = [
    {"claim": "Six rule categories (Validation/Calculation/Routing/Limit-check/Error-handling/Compliance) "
              "and their keyword signals.",
     "source": "reference/.claude/skills/condition-classifier/SKILL.md — categories are language-agnostic; "
               "adapted field-naming heuristics from COBOL WS-/IO- prefixes to Oracle p_/v_ prefixes."},
    {"claim": "CHECK constraints and named business exceptions scored at top confidence without SME review.",
     "source": "reference/.claude/skills/rule-tagger/SKILL.md — same status COBOL 88-level conditions get, "
               "for the identical reason: enforced/named by the source, not inferred from procedural code."},
]


def generate_run_version() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H.%M.%S.") + f"{now.microsecond // 1000:03d}Z"


def load_run(root: str, run: str, artifact_filename: str) -> tuple[dict, str]:
    root_path = Path(root)
    if run == "latest":
        pointer = json.loads((root_path / "latest.json").read_text(encoding="utf-8"))
        run_version = pointer["run_version"]
    else:
        run_version = run
    return json.loads((root_path / run_version / artifact_filename).read_text(encoding="utf-8")), run_version


_SOURCE_CACHE: dict[str, list[str]] = {}


def source_lines(abs_path: str) -> list[str]:
    if abs_path not in _SOURCE_CACHE:
        try:
            _SOURCE_CACHE[abs_path] = Path(abs_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            _SOURCE_CACHE[abs_path] = []
    return _SOURCE_CACHE[abs_path]


def raw_snippet(abs_path: str, start: int, end: int) -> str:
    lines = source_lines(abs_path)
    if not lines or start < 1:
        return ""
    cleaned = [re.sub(r"--.*", "", l).strip() for l in lines[start - 1:end]]
    return re.sub(r"\s+", " ", " ".join(cleaned)).strip()


def extract_if_condition(abs_path: str, start: int, end: int) -> str:
    snippet = raw_snippet(abs_path, start, end)
    m = re.search(r"^\s*IF\s+(.*?)\s+THEN\b", snippet, re.IGNORECASE)
    return m.group(1).strip() if m else snippet


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

CATEGORY_FIELD_SIGNALS = {
    "VALIDATION": ["TYPE", "CODE", "STATUS", "FLAG", "IND", "VALID", "FOUND", "EXIST"],
    "CALCULATION": ["RATE", "INTEREST", "AMOUNT", "TOTAL", "BALANCE", "FEE", "TAX", "COMPUTE"],
    "ROUTING": ["TRANS_TYPE", "TXN_TYPE", "OPTION", "ACTION", "MODE"],
    "LIMIT_CHECK": ["LIMIT", "MAX", "MIN", "THRESHOLD", "CAP", "BALANCE", "DAILY"],
    "ERROR_HANDLING": ["ERROR", "ERR", "EXCEPTION", "OTHERS", "SQLCODE"],
    "COMPLIANCE": ["AUDIT", "REGULAT", "REPORT", "COMPLY"],
}
CATEGORY_PRIORITY = ["ERROR_HANDLING", "LIMIT_CHECK", "COMPLIANCE", "CALCULATION", "ROUTING", "VALIDATION"]


def classify_category(text: str) -> str:
    upper = text.upper()
    scores = {cat: sum(1 for kw in kws if kw in upper) for cat, kws in CATEGORY_FIELD_SIGNALS.items()}
    best = max(CATEGORY_PRIORITY, key=lambda c: (scores[c], -CATEGORY_PRIORITY.index(c)))
    return best if scores[best] > 0 else "VALIDATION"


def classify_pattern(text: str) -> str:
    # Checked first, deliberately: a condition joining multiple sub-clauses
    # with AND/OR is a compound condition even when one sub-clause would
    # also match a single-clause pattern below — MULTI_CONDITION is the
    # more specific and more informative classification in that case.
    if re.search(r"\bAND\b|\bOR\b", text, re.IGNORECASE):
        return "MULTI_CONDITION"
    if re.search(r"=\s*'[A-Z_]+'", text) or re.search(r"'[A-Z_]+'\s*=", text):
        return "FIELD_VALUE_COMPARE"
    if re.search(r">=?|<=?", text) and re.search(r"\d", text):
        return "RANGE_OR_LIMIT_COMPARE"
    if re.search(r"IS\s+NULL|IS\s+NOT\s+NULL", text, re.IGNORECASE):
        return "NULL_CHECK"
    if re.search(r"[<>]=?", text):
        return "FIELD_FIELD_COMPARE"
    return "OTHER"


VERB_BY_CATEGORY = {
    "VALIDATION": "Validate", "CALCULATION": "Calculate", "ROUTING": "Route",
    "LIMIT_CHECK": "Enforce", "ERROR_HANDLING": "Handle", "COMPLIANCE": "Flag for compliance:",
}

ABBREVIATIONS = {
    "ACCT": "Account", "TXN": "Transaction", "AMT": "Amount", "BAL": "Balance",
    "CUST": "Customer", "STAT": "Status", "NUM": "Number", "NBR": "Number",
    "DT": "Date", "PMT": "Payment", "INT": "Interest", "RATE": "Rate",
    "LMT": "Limit", "LIMIT": "Limit", "MIN": "Minimum", "MAX": "Maximum",
    "IND": "Indicator", "FLAG": "Indicator", "ERR": "Error",
}


def business_name(identifier: str) -> str:
    # Dotted record-field access (e.g. `rec.balance` from a cursor FOR loop)
    # carries its business meaning in the field after the dot — `rec` is
    # just a generic loop-variable name with no meaning of its own.
    # "Enforce Rec" is worse than saying nothing; "Enforce Balance" is right.
    if "." in identifier:
        identifier = identifier.split(".")[-1]
    ident = re.sub(r"^[pv]_", "", identifier, flags=re.IGNORECASE)
    parts = [ABBREVIATIONS.get(p.upper(), p.capitalize()) for p in ident.split("_") if p]
    return " ".join(parts) or identifier


_OPERATOR_PHRASE = {
    "=": "is", "!=": "is not", "<>": "is not", "^=": "is not",
    "<": "below", "<=": "at or below", ">": "above", ">=": "at or above",
}
_COMPARISON_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_$#.]*)\s*(<=|>=|!=|<>|\^=|=|<|>)\s*"
    r"('[^']*'|-?\d[\d_]*(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_$#.]*)")


def _format_operand(operand: str) -> str:
    """Render a literal the way a business reader expects to see it."""
    if operand.startswith("'"):
        return operand.strip("'")
    try:
        n = float(operand.replace("_", ""))
    except ValueError:
        return business_name(operand)
    return f"{int(n):,}" if n.is_integer() else f"{n:,}"


def condition_qualifier(cond: str, subject: str, invert: bool = False) -> str:
    """
    A short phrase distinguishing one branch of a decision from its siblings.

    Without this, every tier of a tiered rate emits the identical name
    ("Enforce Balance" three times) and every default branch emits "Apply
    default handling when no condition matches". A BRD in which four rules
    share one name is unusable regardless of how accurate the extraction is.

    Returns "" when no single comparison dominates — a made-up qualifier
    would be worse than none.
    """
    return describe_comparison(cond, [subject] if subject else [], invert)[1]


def describe_comparison(cond: str, known_fields: list[str],
                        invert: bool = False) -> tuple[str, str]:
    """
    Derive the rule's subject and its distinguishing qualifier TOGETHER.

    Picking them independently let them disagree: for `v_from_balance <
    p_amount`, subject resolution chose the parameter `p_amount` while the
    qualifier described the other side, yielding "Calculate Amount at or
    above Amount". Reading both off the same comparison makes the name
    coherent by construction — here, "Enforce Balance at or above Amount".

    Returns (subject, qualifier); qualifier is "" when nothing can be said
    faithfully, which is better than a qualifier that misleads.
    """
    fallback = guess_subject(cond, known_fields)
    matches = _COMPARISON_RE.findall(cond or "")
    if not matches:
        return fallback, ""

    def score(m: tuple) -> int:
        lhs_, op_, rhs_ = m
        s = 0
        # An equality against a literal is the clause that IDENTIFIES which
        # case this is — the one worth putting in the name. In `status =
        # 'ACTIVE' AND days > 365` it is the status clause that distinguishes
        # this rule from its sibling, not the threshold.
        if op_ == "=" and rhs_.startswith("'"):
            s += 2
        # A clause about one of the object's own fields is about the rule's
        # real subject, rather than an incidental intermediate.
        if any(lhs_.lower() == f.lower() or lhs_.lower().endswith("." + f.lower())
               for f in known_fields):
            s += 1
        return s

    lhs, op, rhs = max(matches, key=score)

    if invert:
        op = _OPERATOR_INVERSE.get(op, op)
    phrase = _OPERATOR_PHRASE.get(op)
    if not phrase:
        return lhs or fallback, ""

    # A compound condition cannot be summarised by one of its clauses. An
    # equality against a literal still reads correctly as a scope qualifier
    # ("Validate Current Status is ACTIVE"); an inequality does not — it
    # implies the whole rule is that one threshold, which silently dropped the
    # NULL check from `p_principal IS NULL OR p_principal <= 0`.
    if re.search(r"\bAND\b|\bOR\b", cond, re.IGNORECASE) and op != "=":
        return lhs or fallback, ""

    qualifier = f"{phrase} {_format_operand(rhs)}"
    return (lhs or fallback), (qualifier if len(qualifier) <= 40 else "")


_ZERO_GUARD_RE = re.compile(r"(<=|>=|!=|<>|\^=|=|<|>)\s*0\b")


def _is_zero_guard(cond: str) -> bool:
    """
    A comparison against literal zero is a sanity guard, not a business tier.

    Keyword classification put `v_interest_amount > 0` in CALCULATION because
    the field is named "interest amount", yielding the nonsense rule name
    "Calculate Interest Amount above 0". Tiered business thresholds compare
    against meaningful magnitudes (100000, 365); zero means "is there anything
    to do at all?", which is validation.
    """
    return bool(_ZERO_GUARD_RE.search(cond or ""))


# Inverting a guard states the RULE rather than its violation. `p_amount <= 0`
# guards a rejection, so the business rule is "amount must be above 0" — SBVR's
# point that a rule is stated positively, not as the exception to it.
_OPERATOR_INVERSE = {
    "=": "!=", "!=": "=", "<>": "=", "^=": "=",
    "<": ">=", "<=": ">", ">": "<=", ">=": "<",
}


def make_rule_name(category: str, subject: str, source_text: str, qualifier: str = "") -> str:
    verb = VERB_BY_CATEGORY.get(category, "Enforce")
    name = f"{verb} {business_name(subject)}".strip()
    return f"{name} {qualifier}".strip() if qualifier else name


def guess_subject(condition_text: str, known_fields: list[str]) -> str:
    for f in known_fields:
        if f.lower() in condition_text.lower():
            return f
    m = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)", condition_text)
    return m.group(1) if m else "condition"


# ---------------------------------------------------------------------------
# Rule mining
# ---------------------------------------------------------------------------

# How a DDL candidate's enforcement state maps onto rule confidence.
# A DISABLED constraint is deliberately still surfaced as a rule — dropping it
# would hide a documented business intent from the BRD entirely — but it is
# scored low and flagged for SME review, and its description says plainly that
# the database is NOT enforcing it.
_ENFORCEMENT_TO_CONFIDENCE = {
    "enforced":               (5, "confirmed", False),
    "enforced_new_data_only": (4, "high",      True),
    "not_enforced":           (2, "low",       True),
}


def mine_from_ddl_candidates(data_artifact: dict) -> list[dict]:
    """
    Consume Agent 3's unified ddl_rule_candidates feed: CHECK constraints,
    virtual (computed) column formulas, UNIQUE constraints/indexes, and view
    filter predicates — each carrying its real Oracle enforcement state.
    """
    rules = []
    for cand in data_artifact.get("ddl_rule_candidates", []):
        kind = cand["source_kind"]
        signal, confidence, needs_review = _ENFORCEMENT_TO_CONFIDENCE.get(
            cand.get("confidence", "enforced"), (3, "medium", True))
        expression = cand.get("expression", "")
        table = cand.get("table")
        columns = cand.get("columns") or []

        if kind == "check_constraint":
            subject = guess_subject(expression, [])
            is_set = "IN(" in expression.upper().replace(" ", "")
            name = (f"Restrict {business_name(subject)} to allowed values" if is_set
                    else make_rule_name(classify_category(expression), subject, expression))
            desc = f"The database defines: {expression} (table {table}). {cand['explanation']}"
            rules.append({
                "raw_key": f"CHECK::{table}::{cand.get('constraint_name')}",
                "category": classify_category(expression),
                "structural_pattern": "SET_MEMBERSHIP" if is_set else classify_pattern(expression),
                "name": name, "description": desc, "condition_text": expression,
                "signal_strength": signal, "confidence": confidence,
                "requires_sme_review": needs_review,
                "is_enforced": cand["is_enforced"],
                "source": {"kind": "ddl_check_constraint", "table": table,
                           "constraint_name": cand.get("constraint_name")},
            })

        elif kind == "virtual_column":
            col = cand.get("column", "")
            rules.append({
                "raw_key": f"VCOL::{table}::{col}",
                "category": "CALCULATION", "structural_pattern": "ARITHMETIC_RESULT",
                "name": f"Calculate {business_name(col)}",
                "description": f"{business_name(col)} on table {table} is a computed column, always "
                               f"derived by the database as: {expression}. {cand['explanation']}",
                "condition_text": expression,
                "signal_strength": signal, "confidence": confidence,
                "requires_sme_review": needs_review, "is_enforced": cand["is_enforced"],
                "source": {"kind": "ddl_virtual_column", "table": table, "column": col},
            })

        elif kind in ("unique_constraint", "unique_index"):
            col_phrase = ", ".join(business_name(c) for c in columns) or "the key columns"
            ident = cand.get("constraint_name") or cand.get("index_name")
            rules.append({
                "raw_key": f"UNIQUE::{table}::{'+'.join(columns)}",
                "category": "VALIDATION", "structural_pattern": "UNIQUENESS",
                "name": f"Enforce unique {col_phrase} on {business_name(table or '')}".strip(),
                "description": f"No two rows in {table} may share the same {col_phrase}. "
                               f"Enforced by {ident}. {cand['explanation']}",
                "condition_text": f"UNIQUE({', '.join(columns)})",
                "signal_strength": signal, "confidence": confidence,
                "requires_sme_review": needs_review, "is_enforced": cand["is_enforced"],
                "source": {"kind": f"ddl_{kind}", "table": table, "constraint_name": ident},
            })

        elif kind == "view_filter":
            view = cand.get("view", "")
            rules.append({
                "raw_key": f"VIEW::{view}",
                "category": classify_category(expression), "structural_pattern": classify_pattern(expression),
                "name": f"Define {business_name(view)} population",
                "description": f"The view {view} exposes only the rows matching {expression} from "
                               f"{', '.join(cand.get('references_tables', [])) or 'its backing tables'}. "
                               f"{cand['explanation']}",
                "condition_text": expression,
                "signal_strength": signal, "confidence": confidence,
                "requires_sme_review": needs_review, "is_enforced": cand["is_enforced"],
                "source": {"kind": "ddl_view_filter", "view": view},
            })
    return rules


def _control_ancestors(stmt_id: str, statements: dict) -> list[dict]:
    out, guard = [], 0
    parent_id = statements.get(stmt_id, {}).get("parent_id")
    while parent_id and guard < 200:
        parent = statements.get(parent_id)
        if parent is None:
            break
        out.append(parent)
        parent_id = parent.get("parent_id")
        guard += 1
    return out


def _elsif_conditions(abs_path: str, start: int, end: int) -> list[str]:
    return [m.strip() for m in re.findall(
        r"\bELSIF\s+(.*?)\s+THEN\b", raw_snippet(abs_path, start, end), re.IGNORECASE)]


def _has_else(abs_path: str, start: int, end: int) -> bool:
    return re.search(r"\bELSE\b", raw_snippet(abs_path, start, end), re.IGNORECASE) is not None


def _branch_start_line(if_stmt: dict, statements: dict, suffix: str) -> int | None:
    """First source line of a named branch (THEN / ELSIF1 / ELSE) of an IF."""
    seq = re.search(r"STMT_(\d+)$", if_stmt["statement_id"])
    if not seq:
        return None
    target = f"IF#{int(seq.group(1))}.{suffix}"
    lines = [s["start_line"] for s in statements.values()
             if s.get("parent_id") == if_stmt["statement_id"]
             and s.get("scope_path", [])[-1:] == [target]]
    return min(lines) if lines else None


def _branch_outcome(if_stmt: dict, statements: dict, suffix: str, abs_path: str) -> str:
    """
    What a branch actually DOES, phrased for a requirement statement.

    Without it every conditional rule ends "the system SHALL apply the
    processing described below" — true but vacuous, when the branch plainly
    sets a rate or updates a status. Capped at two clauses: a requirement
    statement should state the outcome, not transcribe the block.
    """
    seq = re.search(r"STMT_(\d+)$", if_stmt["statement_id"])
    if not seq:
        return ""
    target = f"IF#{int(seq.group(1))}.{suffix}"
    kids = sorted((s for s in statements.values()
                   if s.get("parent_id") == if_stmt["statement_id"]
                   and s.get("scope_path", [])[-1:] == [target]),
                  key=lambda s: s["start_line"])

    parts: list[str] = []
    for k in kids:
        st = k["statement_type"]
        if st == "ASSIGNMENT":
            text = raw_snippet(abs_path, k["start_line"], k["end_line"]).rstrip(";")
            lhs, sep, rhs = text.partition(":=")
            if sep:
                parts.append(f"set {business_name(lhs.strip())} to {rhs.strip()}")
        elif st in ("UPDATE", "INSERT", "DELETE"):
            tables = ", ".join(k.get("tables") or []) or "the target table"
            parts.append(f"{st.lower()} {tables}")
        elif st in ("PROCEDURE_CALL", "CALL"):
            # RAISE_APPLICATION_ERROR's message is written by the developer to
            # be read by a human ("Principal amount must be greater than
            # zero") — the clearest statement of the rule available anywhere
            # in the source. Preferring it over any phrasing we could generate.
            text = raw_snippet(abs_path, k["start_line"], k["end_line"])
            m = re.search(r"RAISE_APPLICATION_ERROR\s*\(\s*(-?\d+)\s*,\s*'([^']*)'",
                          text, re.IGNORECASE)
            if m:
                parts.append(f"reject the operation with error {m.group(1)}: {m.group(2)}")
        elif st == "RETURN":
            # A validation guard whose whole body is `RETURN NULL` has no
            # assignment, so without this it falls back to the vacuous form.
            text = raw_snippet(abs_path, k["start_line"], k["end_line"]).rstrip(";")
            value = re.sub(r"^\s*RETURN\s*", "", text, flags=re.IGNORECASE).strip()
            parts.append(f"return {value}" if value else "return without processing")
        if len(parts) == 2:
            break

    outcome = " and ".join(parts)
    return outcome if 0 < len(outcome) <= 160 else ""


def _emit_condition_rule(object_id, stmt, cond, line, known_fields,
                         branch_label=None, outcome="") -> dict:
    """One rule per DECISION BRANCH. A three-way IF/ELSIF/ELSE encodes three
    distinct business outcomes, so it must yield three rules — emitting only
    the IF loses two thirds of the logic (measured: it cost 2 of 5 rules on
    the dormant-account procedure)."""
    # A null/negative guard is input validation regardless of field naming or
    # of being OR-joined; without this, a field called "rate" or "amount"
    # keyword-matches into CALCULATION.
    has_null_check = re.search(r"IS\s+NULL|IS\s+NOT\s+NULL", cond, re.IGNORECASE) is not None
    category = "VALIDATION" if has_null_check or _is_zero_guard(cond) else classify_category(cond)
    subject, qualifier = describe_comparison(cond, known_fields)
    signal = 4 if any(f.lower() in cond.lower() for f in known_fields) else 2
    label = f" ({branch_label})" if branch_label else ""
    return {
        "raw_key": f"IF::{object_id}::{line}",
        "category": category, "structural_pattern": classify_pattern(cond),
        "name": make_rule_name(category, subject, cond, qualifier),
        "description": f"When {cond}, the system applies the corresponding handling{label}. "
                       f"Implemented in {object_id}, line {line}.",
        "condition_text": cond, "signal_strength": signal,
        "outcome_text": outcome,
        "confidence": "high" if signal >= 4 else "low",
        "requires_sme_review": signal < 4,
        "source": {"kind": "conditional_branch", "object_id": object_id,
                   "statement_id": stmt["statement_id"], "line": line},
    }


# Oracle's own predefined exceptions. A handler for one of these detects a
# condition the DATABASE raised, so it carries information not present
# anywhere else. A handler for a user-defined exception (e_*) does not: the
# rule was already captured at its RAISE site, and emitting it again is
# duplicate noise.
_CASE_WHEN_RE = re.compile(r"\bWHEN\s+(.+?)\s+THEN\s+(.+?)\s*$", re.IGNORECASE)
_CASE_ELSE_RE = re.compile(r"\bELSE\s+(.+?)\s*$", re.IGNORECASE)
_CASE_SELECTOR_RE = re.compile(r"\bCASE\b\s*(.*?)\s*$", re.IGNORECASE)


def mine_from_case_expression(object_id, stmt, abs_path, known_fields) -> list[dict]:
    """
    Decompose a CASE expression into one rule per branch.

    A lookup CASE carries no arithmetic, so the derivation scorer scores it 0
    and drops it — yet a table mapping account type to minimum balance is
    almost pure business policy, and each branch is separately changeable.
    Measured on a blind procedure: leaving CASE whole cost 6 of 10 rules
    (recall 0.400).

    Handles both simple CASE (`CASE x WHEN 'A' THEN 1`) and searched CASE
    (`CASE WHEN x > 1 THEN ...`). Branch line numbers come from scanning the
    physical source lines so each rule keeps exact provenance.
    """
    text = raw_snippet(abs_path, stmt["start_line"], stmt["end_line"])
    if not re.search(r"\bCASE\b", text, re.IGNORECASE):
        return []
    target = re.split(r":=", text, maxsplit=1)[0].strip()
    if not target or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$#.]*", target):
        return []

    lines = source_lines(abs_path)
    if len(lines) < stmt["end_line"]:
        return []
    selector = ""
    for n in range(stmt["start_line"], stmt["end_line"] + 1):
        m = _CASE_SELECTOR_RE.search(lines[n - 1])
        if m:
            selector = m.group(1).strip()
            break

    category = classify_category(f"{target} {selector}")
    subject = target
    out = []
    for n in range(stmt["start_line"], stmt["end_line"] + 1):
        src = lines[n - 1].strip().rstrip(",")
        m = _CASE_WHEN_RE.search(src)
        if m:
            operand, result = m.group(1).strip(), m.group(2).strip().rstrip(";")
            cond = f"{selector} = {operand}" if selector else operand
            out.append({
                "raw_key": f"CASE::{object_id}::{n}",
                "category": category, "structural_pattern": classify_pattern(cond),
                "name": f"{VERB_BY_CATEGORY.get(category, 'Enforce')} "
                        f"{business_name(subject)} for {operand.strip(chr(39))}",
                "description": f"When {cond}, {business_name(subject)} is {result}. "
                               f"Implemented in {object_id}, line {n}.",
                "condition_text": cond, "signal_strength": 5,
                # The branch result is known, so the BRD can state it instead of
                # falling back to "apply the processing described below".
                "outcome_text": f"set {business_name(subject)} to {result}",
                "confidence": "confirmed", "requires_sme_review": False,
                "source": {"kind": "case_branch", "object_id": object_id,
                           "statement_id": stmt["statement_id"], "line": n},
            })
            continue
        # ELSE only counts once the CASE has produced at least one WHEN, so an
        # ELSE belonging to an enclosing IF is not mistaken for a CASE default.
        m = _CASE_ELSE_RE.search(src)
        if m and out:
            result = m.group(1).strip().rstrip(";")
            out.append({
                "raw_key": f"CASE::{object_id}::{n}",
                "category": category, "structural_pattern": "DEFAULT_BRANCH",
                "name": f"{VERB_BY_CATEGORY.get(category, 'Enforce')} "
                        f"default {business_name(subject)}",
                "description": f"When no other case matches, {business_name(subject)} "
                               f"defaults to {result}. Implemented in {object_id}, line {n}.",
                "condition_text": "no preceding case matched", "signal_strength": 4,
                "outcome_text": f"default {business_name(subject)} to {result}",
                "confidence": "high", "requires_sme_review": False,
                "source": {"kind": "case_branch", "object_id": object_id,
                           "statement_id": stmt["statement_id"], "line": n},
            })
    return out


_PREDEFINED_EXCEPTIONS = {
    "NO_DATA_FOUND", "TOO_MANY_ROWS", "DUP_VAL_ON_INDEX", "ZERO_DIVIDE",
    "INVALID_NUMBER", "VALUE_ERROR", "INVALID_CURSOR", "CURSOR_ALREADY_OPEN",
    "TIMEOUT_ON_RESOURCE", "STORAGE_ERROR", "PROGRAM_ERROR", "ACCESS_INTO_NULL",
    "COLLECTION_IS_NULL", "SUBSCRIPT_BEYOND_COUNT", "SUBSCRIPT_OUTSIDE_LIMIT",
    "CASE_NOT_FOUND", "SELF_IS_NULL", "ROWTYPE_MISMATCH", "SYS_INVALID_ROWID",
}

_AGGREGATE_RE = re.compile(r"\b(SUM|COUNT|AVG|MAX|MIN)\s*\(", re.IGNORECASE)
_ARITHMETIC_RE = re.compile(r"[-+*/]")
_FUNCALL_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_$#]*\s*\(")

# A derivation counts as a BUSINESS CALCULATION when it composes at least two
# operations. One arithmetic step is mechanics.
#
#   ROUND(bal * (rate/100) * (days/365), 2)     score 5  -> business formula
#   EXTRACT(DAY FROM LAST_DAY(p_run_date))      score 2  -> business definition
#   p_as_of_date - NVL(v_last, p_as_of - 9999)  score 3  -> business formula
#   rec.balance + v_interest_amount             score 1  -> mechanics, skip
#   p_accounts_processed + 1                    score 1  -> counter, skip
#
# Tuned against three procedures; the counter cases were real false positives
# the held-out test surfaced.
_DERIVATION_COMPLEXITY_THRESHOLD = 2

_RAISE_NAME_RE = re.compile(r"\bRAISE\s+([A-Za-z_][A-Za-z0-9_$#]*)", re.IGNORECASE)


def _assigns_variable(stmt: dict, variable: str, abs_path: str) -> bool:
    """
    True only when this statement's assignment TARGET is `variable`.

    A backward slice deliberately includes transitive dependencies, so the
    statement computing v_interest_amount also appears in v_new_balance's
    slice. Without this check both variables emit a rule for the same formula
    — one real, one a duplicate attributed to the wrong variable.
    """
    text = raw_snippet(abs_path, stmt["start_line"], stmt["end_line"])
    var = variable.upper()
    if stmt["statement_type"] == "ASSIGNMENT":
        lhs = re.split(r":=", text, maxsplit=1)[0]
        return var in {t.upper() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_$#.]*", lhs)}
    if stmt["statement_type"] == "SELECT_INTO":
        m = re.search(r"\bINTO\b(.*?)\bFROM\b", text, re.IGNORECASE | re.DOTALL)
        if not m:
            return False
        return var in {t.upper() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_$#.]*", m.group(1))}
    return False


def _is_derivation(stmt: dict, abs_path: str) -> bool:
    """
    True when a statement DEFINES a business quantity rather than merely
    fetching a stored one.

    This distinction is what keeps slice-derived rules precise. Three
    variables can be populated by one plain `SELECT col1, col2, col3 INTO ...
    WHERE pk = :x` — emitting a rule for each would be two false positives
    for one lookup. But `SELECT SUM(txn_amount) ... WHERE txn_type = 'X' AND
    TRUNC(txn_date) = TRUNC(SYSDATE)` genuinely defines "today's outward
    transfer total", and `v := a - NVL(b, c)` genuinely defines a computed
    quantity. Aggregation and arithmetic are the signals.
    """
    st = stmt["statement_type"]
    text = raw_snippet(abs_path, stmt["start_line"], stmt["end_line"])
    if st == "ASSIGNMENT":
        parts = re.split(r":=", text, maxsplit=1)
        if len(parts) != 2:
            return False
        rhs = parts[1]
        if _AGGREGATE_RE.search(rhs):
            return True
        score = len(_ARITHMETIC_RE.findall(rhs)) + len(_FUNCALL_RE.findall(rhs))
        return score >= _DERIVATION_COMPLEXITY_THRESHOLD
    if st == "SELECT_INTO":
        return bool(_AGGREGATE_RE.search(text))
    return False


def mine_from_variable_slices(logic_dir: Path, logic_artifact: dict,
                              parser_root: Path, object_index: dict,
                              file_abs_paths: dict) -> list[dict]:
    """
    Variable-centric rules, consuming Agent 4's backward slices.

    The field's consensus architecture since Huang (1996) is Variable
    Identification -> Slice -> Represent; COBREX (ICSME 2022) organises rules
    around business variables for exactly this reason. Condition-mining alone
    answers "what conditions exist?"; this answers "what determines this
    value?" — the question a BRD reader actually has.
    """
    rules = []
    for object_id, rel in logic_artifact.get("object_index", {}).items():
        logic_path = logic_dir / rel
        parser_rel = object_index.get(object_id)
        if not logic_path.exists() or not parser_rel:
            continue
        logic = json.loads(logic_path.read_text(encoding="utf-8"))
        obj = json.loads((parser_root / parser_rel).read_text(encoding="utf-8"))
        abs_path = file_abs_paths.get(obj.get("file_id"))
        if not abs_path:
            continue
        statements = obj.get("statements", {})

        for sl in logic.get("variable_slices", []):
            # Filter on the DERIVATION, not on slice size. A slice legitimately
            # includes every control ancestor, so a genuine one-line formula can
            # sit inside a nine-statement slice — an earlier size cap silently
            # dropped the interest-calculation rule for exactly that reason.
            deriving = [statements[sid] for sid in sl.get("determined_by_statements", [])
                        if sid in statements
                        and _is_derivation(statements[sid], abs_path)
                        and _assigns_variable(statements[sid], sl["variable"], abs_path)]
            if not deriving:
                continue
            # Assigned by a business formula in several different branches: those
            # branches already produced their own rules, so emitting a merged
            # one here would duplicate them.
            if len(deriving) > 2:
                continue

            anchor = max(deriving, key=lambda s: s["start_line"])
            expr = raw_snippet(abs_path, anchor["start_line"], anchor["end_line"]).rstrip(";")
            var = sl["variable"]
            deps = [d for d in sl.get("depends_on_variables", []) if d.upper() != var.upper()]

            rules.append({
                "raw_key": f"DERIVE::{object_id}::{var}",
                "category": "CALCULATION", "structural_pattern": "VALUE_DERIVATION",
                "name": f"Determine {business_name(var)}",
                "description": f"{business_name(var)} is derived as: {expr}."
                               + (f" It depends on {', '.join(business_name(d) for d in deps[:4])}."
                                  if deps else "")
                               + f" Defined in {object_id}, line {anchor['start_line']}.",
                "condition_text": expr,
                "signal_strength": 4, "confidence": "high", "requires_sme_review": False,
                "source": {"kind": "variable_derivation", "object_id": object_id,
                           "statement_id": anchor["statement_id"], "line": anchor["start_line"]},
            })
    return rules


def _nearest_preceding(statements: dict, before_line: int, wanted_type: str) -> dict | None:
    candidates = [s for s in statements.values()
                  if s["statement_type"] == wanted_type and s["start_line"] < before_line]
    return max(candidates, key=lambda s: s["start_line"]) if candidates else None


def _raise_to_obligation(object_id, raise_stmt, statements, abs_path, known_fields) -> dict | None:
    """
    Restate a RAISE as the positive obligation it enforces.

    SBVR is explicit that an exception is not itself a business rule:
    "there are no exceptions; instead, there are well stated business rules"
    (Chaparro et al., WCRE 2012). Emitting "Handle E Insufficient Balance"
    states the violation, not the rule — and anchors it at the HANDLER, far
    from the logic. Measured cost of the old behaviour: five false positives
    on a single procedure.

    Two shapes are recognised:
      IF <cond> THEN RAISE e_x            -> "must not proceed when <cond>"
      WHEN NO_DATA_FOUND THEN RAISE e_x   -> "the queried row must exist"
    """
    text = raw_snippet(abs_path, raise_stmt["start_line"], raise_stmt["end_line"])
    m = _RAISE_NAME_RE.search(text)
    if not m:
        return None
    exc = m.group(1)
    if exc.upper() in ("", "OTHERS"):
        return None

    line = raise_stmt["start_line"]

    # Shape 1 — guarded by an IF: that condition IS the violation condition.
    controlling_if = next((a for a in _control_ancestors(raise_stmt["statement_id"], statements)
                           if a["statement_type"] == "IF"), None)
    if controlling_if is not None:
        cond = extract_if_condition(abs_path, controlling_if["start_line"], controlling_if["end_line"])
        # The IF condition is the VIOLATION; the rule is its negation.
        subject, qualifier = describe_comparison(cond, known_fields, invert=True)
        category = classify_category(cond)
        if re.search(r"IS\s+NULL|IS\s+NOT\s+NULL", cond, re.IGNORECASE) or _is_zero_guard(cond):
            category = "VALIDATION"
        # A guard that rejects the operation is never a calculation, whatever
        # its field names suggest. `v_from_balance < p_amount` keyword-matched
        # CALCULATION on "balance"/"amount"; it is an insufficient-funds check.
        if category == "CALCULATION":
            category = "LIMIT_CHECK" if re.search(r"[<>]", cond) else "VALIDATION"
        return {
            # Same key as the condition rule for this IF, so the two merge —
            # they are one business rule, and the obligation phrasing wins.
            "raw_key": f"IF::{object_id}::{controlling_if['start_line']}",
            "is_obligation": True,
            "category": category, "structural_pattern": classify_pattern(cond),
            "name": make_rule_name(category, subject, cond, qualifier),
            "description": f"The operation must not proceed when {cond}. "
                           f"Violation raises {exc} ({object_id}, line {line}).",
            "condition_text": cond, "signal_strength": 5, "confidence": "confirmed",
            "requires_sme_review": False,
            "raises": exc,
            "source": {"kind": "named_exception", "object_id": object_id,
                       "statement_id": raise_stmt["statement_id"], "line": line},
        }

    # Shape 2 — inside an exception handler. Handlers of nested blocks are
    # recorded with no parent, so locate the enclosing handler by line span.
    handler = next((s for s in statements.values()
                    if s["statement_type"] == "EXCEPTION_HANDLER"
                    and s["start_line"] <= line <= s.get("end_line", line)), None)
    handler_for = [h.upper() for h in (handler.get("handler_for") if handler else []) or []]

    if "NO_DATA_FOUND" in handler_for:
        query = _nearest_preceding(statements, line, "SELECT_INTO")
        tables = ", ".join(query.get("tables") or []) if query else "the source table"
        preds = ", ".join(query.get("predicate_reads") or []) if query else ""
        where = f" identified by {preds}" if preds else ""

        # A procedure that looks the same row up twice (source account, then
        # destination account) produces two rules whose predicate_reads are
        # identical — both `account_number`. What tells them apart is the BIND
        # PARAMETER, so name the rule after it.
        bind = ""
        if query is not None:
            qtext = raw_snippet(abs_path, query["start_line"], query["end_line"])
            bm = re.search(r"WHERE\b.*?=\s*(p_[A-Za-z0-9_$#]+)", qtext, re.IGNORECASE | re.DOTALL)
            if bm:
                bind = business_name(bm.group(1))
        entity = business_name(tables.split(",")[0].strip() or "record")
        name = (f"Require the {entity} record for {bind} to exist" if bind
                else f"Require the {entity} record to exist")
        return {
            "raw_key": f"EXISTS::{object_id}::{line}",
            "is_obligation": True,
            "category": "VALIDATION", "structural_pattern": "EXISTENCE_CHECK",
            "name": name,
            "description": f"The referenced row in {tables}{where} must exist. "
                           f"If the lookup returns no data the operation is rejected and "
                           f"{exc} is raised ({object_id}, line {line}).",
            "condition_text": f"row must exist in {tables}{where}",
            "signal_strength": 5, "confidence": "confirmed", "requires_sme_review": False,
            "raises": exc,
            "source": {"kind": "named_exception", "object_id": object_id,
                       "statement_id": raise_stmt["statement_id"], "line": line},
        }

    return None


_CURSOR_WHERE_RE = re.compile(r"\bWHERE\b(.*?)(?:;|\bORDER\s+BY\b|\bGROUP\s+BY\b|$)",
                              re.IGNORECASE | re.DOTALL)


def mine_from_cursors(obj: dict, object_id: str, abs_path: str) -> list[dict]:
    """
    A cursor's WHERE clause defines WHICH records the process applies to —
    the eligibility rule, and frequently the single most important rule in a
    batch procedure. `WHERE account_status='ACTIVE' AND account_type LIKE
    'SAVINGS%'` is the statement of who earns interest; without it the BRD
    describes how interest is computed but never says for whom.
    """
    rules = []
    for cur in obj.get("cursors", []):
        line = cur.get("line")
        if not line:
            continue
        # A cursor declaration runs from its line to its terminating semicolon.
        decl = raw_snippet(abs_path, line, line + 20)
        decl = decl.split(";")[0]
        m = _CURSOR_WHERE_RE.search(decl)
        if not m:
            continue
        predicate = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(")").strip()
        if not predicate:
            continue
        tables = re.search(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_$#.]*)", decl, re.IGNORECASE)
        table = tables.group(1) if tables else "the source table"
        rules.append({
            "raw_key": f"CURSOR::{object_id}::{cur.get('name', line)}",
            "is_obligation": True,
            "category": "VALIDATION", "structural_pattern": "SET_MEMBERSHIP",
            "name": f"Restrict processing to eligible {business_name(table)} records",
            "description": f"This process applies only to rows of {table} where {predicate}. "
                           f"Records outside this population are not processed. "
                           f"Defined by cursor {cur.get('name', '')} in {object_id}, line {line}.",
            "condition_text": predicate,
            "signal_strength": 5, "confidence": "confirmed", "requires_sme_review": False,
            "source": {"kind": "cursor_eligibility", "object_id": object_id,
                       "statement_id": None, "line": line},
        })
    return rules


def mine_from_statements(parser_root: Path, object_index: dict, file_abs_paths: dict) -> list[dict]:
    rules = []
    for object_id, rel_path in object_index.items():
        obj_path = parser_root / rel_path
        if not obj_path.exists():
            continue
        obj = json.loads(obj_path.read_text(encoding="utf-8"))
        abs_path = file_abs_paths.get(obj.get("file_id"))
        if not abs_path:
            continue
        statements = obj.get("statements", {})
        known_fields = [p["name"] for p in obj.get("parameters", [])] + \
                       [d["name"] for d in obj.get("declarations", [])]

        rules.extend(mine_from_cursors(obj, object_id, abs_path))

        for stmt in statements.values():
            st = stmt["statement_type"]

            if st == "IF":
                cond = extract_if_condition(abs_path, stmt["start_line"], stmt["end_line"])
                rules.append(_emit_condition_rule(
                    object_id, stmt, cond, stmt["start_line"], known_fields,
                    outcome=_branch_outcome(stmt, statements, "THEN", abs_path)))

                # Each ELSIF is its own business outcome.
                for i, econd in enumerate(
                        _elsif_conditions(abs_path, stmt["start_line"], stmt["end_line"]), start=1):
                    line = _branch_start_line(stmt, statements, f"ELSIF{i}") or stmt["start_line"]
                    rules.append(_emit_condition_rule(
                        object_id, stmt, econd, line, known_fields, f"ELSIF branch {i}",
                        outcome=_branch_outcome(stmt, statements, f"ELSIF{i}", abs_path)))

                # The ELSE branch is the default outcome — also a rule.
                if _has_else(abs_path, stmt["start_line"], stmt["end_line"]):
                    line = _branch_start_line(stmt, statements, "ELSE") or stmt["start_line"]
                    # Name the default after WHAT it defaults on. Four rules all
                    # called "Apply default handling when no condition matches"
                    # are indistinguishable to a BRD reader.
                    subject = business_name(guess_subject(cond, known_fields))
                    rules.append({
                        "raw_key": f"IF::{object_id}::{line}",
                        "category": "VALIDATION", "structural_pattern": "DEFAULT_BRANCH",
                        "name": f"Apply default {subject} handling",
                        "description": f"When none of the preceding {subject} conditions hold, the "
                                       f"system applies its default handling. "
                                       f"Implemented in {object_id}, line {line}.",
                        "condition_text": "no preceding condition matched",
                        "outcome_text": _branch_outcome(stmt, statements, "ELSE", abs_path),
                        "signal_strength": 3, "confidence": "medium", "requires_sme_review": False,
                        "source": {"kind": "conditional_branch", "object_id": object_id,
                                   "statement_id": stmt["statement_id"], "line": line},
                    })

            elif st == "ASSIGNMENT":
                rules.extend(mine_from_case_expression(object_id, stmt, abs_path, known_fields))

            elif st == "RAISE":
                r = _raise_to_obligation(object_id, stmt, statements, abs_path, known_fields)
                if r:
                    rules.append(r)

            elif st == "EXCEPTION_HANDLER":
                for handler_name in stmt.get("handler_for", []):
                    upper = handler_name.upper()

                    # A handler for one of Oracle's PREDEFINED exceptions that
                    # sets an outcome instead of re-raising carries information
                    # found nowhere else: the database detected the condition.
                    # A handler for a USER-DEFINED exception does not — that
                    # rule was already captured at its RAISE site, so emitting
                    # it again is duplicate noise.
                    if upper in _PREDEFINED_EXCEPTIONS:
                        children = [s for s in statements.values()
                                    if s.get("parent_id") == stmt["statement_id"]]
                        if any(c["statement_type"] == "RAISE" for c in children):
                            continue  # re-raises: handled by the RAISE obligation path
                        outcomes = [raw_snippet(abs_path, c["start_line"], c["end_line"]).rstrip(";")
                                    for c in children if c["statement_type"] == "ASSIGNMENT"]
                        if not outcomes:
                            continue
                        # Name the rule after WHAT was not found. Two procedures
                        # each handling NO_DATA_FOUND otherwise both produce the
                        # identical, uninformative "Report No Data Found".
                        query = _nearest_preceding(statements, stmt["start_line"], "SELECT_INTO")
                        entity = ((query.get("tables") or [None])[0] if query else None)
                        name = (f"Report missing {business_name(entity)} record" if entity
                                else f"Report {business_name(handler_name)}")
                        rules.append({
                            "raw_key": f"PREDEF::{object_id}::{stmt['start_line']}",
                            "is_obligation": True,
                            "category": "ERROR_HANDLING", "structural_pattern": "CONDITION_NAME",
                            "name": name,
                            "description": f"When the database reports {handler_name} — the requested "
                                           f"record does not exist or the query returned no row — the "
                                           f"system responds with: {'; '.join(outcomes[:2])}. "
                                           f"Implemented in {object_id}, line {stmt['start_line']}.",
                            "condition_text": handler_name,
                            "outcome_text": "; ".join(outcomes[:2]),
                            "signal_strength": 5, "confidence": "confirmed",
                            "requires_sme_review": False,
                            "source": {"kind": "predefined_exception", "object_id": object_id,
                                       "statement_id": stmt["statement_id"], "line": stmt["start_line"]},
                        })
                        continue

                    if upper != "OTHERS":
                        continue

                    # Not every WHEN OTHERS is plumbing. What the handler DOES
                    # decides:
                    #   swallows the error and continues -> a resilience policy
                    #     ("one bad record must not stop the batch")
                    #   raises a specific application error code -> an error
                    #     contract that callers depend on
                    #   bare RAISE -> genuine plumbing, catalogue only
                    children = [s for s in statements.values()
                                if s.get("parent_id") == stmt["statement_id"]]
                    kinds = {c["statement_type"] for c in children}
                    body = " ".join(raw_snippet(abs_path, c["start_line"], c["end_line"])
                                    for c in children)
                    app_err = re.search(r"RAISE_APPLICATION_ERROR\s*\(\s*(-?\d+)", body, re.IGNORECASE)
                    recovers = "RAISE" not in kinds and not app_err
                    writes_log = bool(kinds & {"INSERT", "UPDATE", "DELETE"})

                    if recovers and writes_log:
                        rules.append({
                            "raw_key": f"RESILIENCE::{object_id}::{stmt['start_line']}",
                            "is_obligation": True,
                            "category": "ERROR_HANDLING", "structural_pattern": "FAILURE_ISOLATION",
                            "name": "Isolate per-record failures from the batch",
                            "description": f"A failure while processing one record is recorded and the "
                                           f"run continues; a single bad record must not abort the batch. "
                                           f"Implemented in {object_id}, line {stmt['start_line']}.",
                            "condition_text": "unhandled error on a single record",
                            "outcome_text": "record the failure and continue with the "
                                            "remaining records",
                            "signal_strength": 5, "confidence": "confirmed",
                            "requires_sme_review": False,
                            "source": {"kind": "failure_isolation", "object_id": object_id,
                                       "statement_id": stmt["statement_id"], "line": stmt["start_line"]},
                        })
                        continue

                    if app_err:
                        rules.append({
                            "raw_key": f"ERRCONTRACT::{object_id}::{stmt['start_line']}",
                            "is_obligation": True,
                            "category": "ERROR_HANDLING", "structural_pattern": "ERROR_CONTRACT",
                            "name": f"Report run failure as error {app_err.group(1)}",
                            "description": f"An unrecoverable failure rolls the run back and reports "
                                           f"application error {app_err.group(1)} to the caller. Callers "
                                           f"depend on this code. Implemented in {object_id}, "
                                           f"line {stmt['start_line']}.",
                            "condition_text": f"unrecoverable failure -> {app_err.group(1)}",
                            "outcome_text": f"roll back the run and report application error "
                                            f"{app_err.group(1)} to the caller",
                            "signal_strength": 5, "confidence": "confirmed",
                            "requires_sme_review": False,
                            "source": {"kind": "error_contract", "object_id": object_id,
                                       "statement_id": stmt["statement_id"], "line": stmt["start_line"]},
                        })
                        continue

                    # Bare propagation: real behaviour, but not a business rule.
                    rules.append({
                        "raw_key": f"EXC::OTHERS::{object_id}::{stmt['start_line']}",
                        "category": "ERROR_HANDLING", "structural_pattern": "CONDITION_NAME",
                        "generic_handler": True,
                        "name": "Handle Unexpected Error",
                        "description": f"A catch-all WHEN OTHERS handler covers any unnamed exception. "
                                       f"Implemented in {object_id}, line {stmt['start_line']}.",
                        "condition_text": "OTHERS", "signal_strength": 2, "confidence": "low",
                        "requires_sme_review": False,
                        "source": {"kind": "generic_exception", "object_id": object_id,
                                   "statement_id": stmt["statement_id"], "line": stmt["start_line"]},
                    })
    return rules


def deduplicate(rules: list[dict]) -> list[dict]:
    """
    Merge rules sharing a raw_key.

    An IF condition and the RAISE it guards are ONE business rule expressed
    twice — they deliberately share a key so they collapse here. When that
    happens the obligation phrasing wins ("must not proceed when X" rather
    than "when X, branching occurs"), because it states the rule rather than
    the mechanism. Without this preference the merge would keep whichever
    happened to be mined first.
    """
    by_key: dict[str, dict] = {}
    for r in rules:
        key = r["raw_key"]
        if key not in by_key:
            merged = dict(r)
            merged["sources"] = [r["source"]]
            merged["is_duplicated"] = False
            by_key[key] = merged
            continue

        existing = by_key[key]
        incoming_better = (
            (r.get("is_obligation") and not existing.get("is_obligation"))
            or (r.get("is_obligation") == existing.get("is_obligation")
                and r.get("signal_strength", 0) > existing.get("signal_strength", 0))
        )
        if incoming_better:
            sources = existing["sources"] + [r["source"]]
            promoted = dict(r)
            promoted["sources"] = sources
            promoted["is_duplicated"] = len({json.dumps(s, sort_keys=True) for s in sources}) > 1
            by_key[key] = promoted
        else:
            existing["sources"].append(r["source"])
            existing["is_duplicated"] = len(
                {json.dumps(s, sort_keys=True) for s in existing["sources"]}) > 1
    return list(by_key.values())


def group_rule_sets(rules: list[dict]) -> list[dict]:
    by_category: dict[str, list[str]] = {}
    for r in rules:
        by_category.setdefault(r["category"], []).append(r["rule_id"])
    sets = []
    for i, (cat, rule_ids) in enumerate(sorted(by_category.items()), start=1):
        sets.append({"rule_set_id": f"RS-{i:03d}", "name": f"{cat.replace('_', ' ').title()} rules",
                       "rule_count": len(rule_ids), "rule_ids": rule_ids})
    return sets


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 5: Deterministic PL/SQL business rule miner")
    ap.add_argument("--parser-root", default="output/parser")
    ap.add_argument("--parser-run", default="latest")
    ap.add_argument("--data-root", default="output/data")
    ap.add_argument("--data-run", default="latest")
    ap.add_argument("--inventory-root", default="output/inventory")
    ap.add_argument("--inventory-run", default="latest")
    ap.add_argument("--logic-root", default="output/logic")
    ap.add_argument("--logic-run", default="latest")
    ap.add_argument("--output-root", default="output/rules")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    parser_artifact, parser_run_version = load_run(args.parser_root, args.parser_run, "parser_artifact.json")
    data_artifact, data_run_version = load_run(args.data_root, args.data_run, "data_artifact.json")
    inventory, inv_run_version = load_run(args.inventory_root, args.inventory_run, "inventory-artifact.json")
    parser_root = Path(args.parser_root) / parser_run_version
    file_abs_paths = {fid: meta["abs_path"] for fid, meta in inventory["file_metadata"].items()}

    # Agent 4's variable slices are optional: if this agent is run before
    # 4_logic, rule mining degrades to condition+DDL sources rather than
    # failing outright.
    try:
        logic_artifact, logic_run_version = load_run(args.logic_root, args.logic_run, "logic_artifact.json")
        logic_dir = Path(args.logic_root) / logic_run_version
    except (FileNotFoundError, KeyError):
        logic_artifact, logic_run_version, logic_dir = {"object_index": {}}, None, Path(".")

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_mined = mine_from_ddl_candidates(data_artifact) + \
        mine_from_statements(parser_root, parser_artifact["object_index"], file_abs_paths) + \
        mine_from_variable_slices(logic_dir, logic_artifact, parser_root,
                                  parser_artifact["object_index"], file_abs_paths)
    # Generic WHEN OTHERS handlers are catalogued, never promoted to BR-xxx rules.
    generic_handlers = [r for r in raw_mined if r.get("generic_handler")]
    raw_rules = [r for r in raw_mined if not r.get("generic_handler")]
    deduped = deduplicate(raw_rules)
    for i, r in enumerate(sorted(deduped, key=lambda x: (-x["signal_strength"], x["name"])), start=1):
        r["rule_id"] = f"BR-{i:03d}"
        del r["raw_key"]
    rule_sets = group_rule_sets(deduped)

    error_handling_catalogue = generic_handlers + \
        [r for r in raw_rules if r["category"] == "ERROR_HANDLING" and r.get("signal_strength", 0) <= 2]
    for r in error_handling_catalogue:
        r.pop("raw_key", None)

    stats = {
        "branches_examined": sum(1 for r in raw_rules if r["source"]["kind"] == "conditional_branch"),
        "rules_extracted": len(deduped),
        "duplicates_merged": sum(1 for r in deduped if r["is_duplicated"]),
        "requires_sme_review": sum(1 for r in deduped if r["requires_sme_review"]),
        "by_category": {cat: sum(1 for r in deduped if r["category"] == cat) for cat in CATEGORY_PRIORITY},
        "by_confidence": {c: sum(1 for r in deduped if r["confidence"] == c) for c in ("confirmed", "high", "medium", "low")},
    }

    rules_artifact = {
        "pipeline_stage": "5_rules", "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {"parser_run_version": parser_run_version, "data_run_version": data_run_version,
                      "inventory_run_version": inv_run_version},
        "design_references": DESIGN_REFERENCES,
        "stats": stats,
        "rule_sets": rule_sets,
        "business_rules": deduped,
        "error_handling_catalogue": error_handling_catalogue,
    }
    (run_dir / "rules_artifact.json").write_text(json.dumps(rules_artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        (run_dir / "run_meta.json").write_text(json.dumps(
            {"stage": "5_rules", "run_version": run_version, "status": "success",
             "generated_at": rules_artifact["generated_at"], "upstream": rules_artifact["upstream"],
             "stats_summary": stats}, indent=2), encoding="utf-8")
        (Path(args.output_root) / "latest.json").write_text(json.dumps(
            {"run_version": run_version, "path": f"{run_version}/rules_artifact.json",
             "updated_at": rules_artifact["generated_at"]}, indent=2), encoding="utf-8")

    print("=== Rules Agent Complete ===")
    print(f"Branches examined      : {stats['branches_examined']}")
    print(f"Rules extracted        : {stats['rules_extracted']}")
    for cat, n in stats["by_category"].items():
        print(f"  {cat:15}: {n}")
    print(f"Duplicates merged      : {stats['duplicates_merged']}")
    print(f"Requires SME review    : {stats['requires_sme_review']}")
    print(f"Output                 : {run_dir / 'rules_artifact.json'}")
    print("============================")


if __name__ == "__main__":
    main()
