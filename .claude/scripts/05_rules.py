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


def raw_snippet(abs_path: str, start: int, end: int) -> str:
    if abs_path not in _SOURCE_CACHE:
        try:
            _SOURCE_CACHE[abs_path] = Path(abs_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            _SOURCE_CACHE[abs_path] = []
    lines = _SOURCE_CACHE[abs_path]
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


def make_rule_name(category: str, subject: str, source_text: str) -> str:
    verb = VERB_BY_CATEGORY.get(category, "Enforce")
    return f"{verb} {business_name(subject)}".strip()


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
        known_fields = [p["name"] for p in obj.get("parameters", [])] + [d["name"] for d in obj.get("declarations", [])]

        for stmt in obj.get("statements", {}).values():
            if stmt["statement_type"] == "IF":
                cond = extract_if_condition(abs_path, stmt["start_line"], stmt["end_line"])
                pattern = classify_pattern(cond)
                # A null/negative guard clause is an input-validation check
                # regardless of what the field is named or whether it's
                # combined with other guards via OR (which otherwise wins
                # the overall structural_pattern as MULTI_CONDITION) — a
                # field named "rate" or "amount" would otherwise keyword-
                # match into CALCULATION, misclassifying an ordinary
                # "is this required input present?" guard as an arithmetic
                # rule. Checked against the raw text, independent of
                # classify_pattern's single overall label.
                has_null_check = re.search(r"IS\s+NULL|IS\s+NOT\s+NULL", cond, re.IGNORECASE) is not None
                category = "VALIDATION" if has_null_check else classify_category(cond)
                subject = guess_subject(cond, known_fields)
                signal = 4 if any(f.lower() in cond.lower() for f in known_fields) else 2
                rules.append({
                    "raw_key": f"IF::{category}::{pattern}::{subject.upper()}",
                    "category": category, "structural_pattern": pattern,
                    "name": make_rule_name(category, subject, cond),
                    "description": f"When {cond}, the system branches to different handling. "
                                    f"Implemented in {object_id}, line {stmt['start_line']}.",
                    "condition_text": cond, "signal_strength": signal,
                    "confidence": "high" if signal >= 4 else "low",
                    "requires_sme_review": signal < 4,
                    "source": {"kind": "conditional_branch", "object_id": object_id,
                                "statement_id": stmt["statement_id"], "line": stmt["start_line"]},
                })

            if stmt["statement_type"] == "EXCEPTION_HANDLER":
                for handler_name in stmt.get("handler_for", []):
                    if handler_name.upper() == "OTHERS":
                        # Generic plumbing, not a named business rule — but it is
                        # still error-handling behaviour worth cataloguing. Emit it
                        # flagged so the caller can route it to the error-handling
                        # catalogue and keep it out of the BR-xxx rule set.
                        rules.append({
                            "raw_key": f"EXC::OTHERS::{object_id}::{stmt['start_line']}",
                            "category": "ERROR_HANDLING", "structural_pattern": "CONDITION_NAME",
                            "generic_handler": True,
                            "name": "Handle Unexpected Error",
                            "description": f"A catch-all WHEN OTHERS handler covers any unnamed "
                                            f"exception. Implemented in {object_id}, "
                                            f"line {stmt['start_line']}.",
                            "condition_text": "OTHERS", "signal_strength": 2, "confidence": "low",
                            "requires_sme_review": False,
                            "source": {"kind": "generic_exception", "object_id": object_id,
                                        "statement_id": stmt["statement_id"], "line": stmt["start_line"]},
                        })
                        continue
                    category = classify_category(handler_name)
                    rules.append({
                        "raw_key": f"EXC::{handler_name.upper()}",
                        "category": category, "structural_pattern": "CONDITION_NAME",
                        "name": f"Handle {business_name(handler_name)}",
                        "description": f"The system explicitly detects and handles the '{handler_name}' condition. "
                                        f"Implemented in {object_id}, line {stmt['start_line']}.",
                        "condition_text": handler_name, "signal_strength": 5, "confidence": "confirmed",
                        "requires_sme_review": False,
                        "source": {"kind": "named_exception", "object_id": object_id,
                                    "statement_id": stmt["statement_id"], "line": stmt["start_line"]},
                    })
    return rules


def deduplicate(rules: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for r in rules:
        key = r["raw_key"]
        if key in by_key:
            by_key[key]["sources"].append(r["source"])
            by_key[key]["is_duplicated"] = True
        else:
            merged = dict(r)
            merged["sources"] = [r["source"]]
            merged["is_duplicated"] = False
            by_key[key] = merged
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
    ap.add_argument("--output-root", default="output/rules")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    parser_artifact, parser_run_version = load_run(args.parser_root, args.parser_run, "parser_artifact.json")
    data_artifact, data_run_version = load_run(args.data_root, args.data_run, "data_artifact.json")
    inventory, inv_run_version = load_run(args.inventory_root, args.inventory_run, "inventory-artifact.json")
    parser_root = Path(args.parser_root) / parser_run_version
    file_abs_paths = {fid: meta["abs_path"] for fid, meta in inventory["file_metadata"].items()}

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_mined = mine_from_ddl_candidates(data_artifact) + \
        mine_from_statements(parser_root, parser_artifact["object_index"], file_abs_paths)
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
