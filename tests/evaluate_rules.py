#!/usr/bin/env python3
"""
Ground-truth evaluation harness for the Rules Agent (05_rules.py).

Every serious paper in the business-rule-extraction field reports precision
and recall against hand-annotated rules — COBREX scores F1 0.59, COBRAIN
0.73, A-COBREX P=0.62/R=0.74. Without this harness any claim about our own
quality is an assertion rather than a measurement.

MATCHING CRITERION (this is where these evaluations usually go wrong)
---------------------------------------------------------------------
Exact string matching on rule names measures phrasing luck, not extraction
quality. A-COBREX used an undefined "fuzzy match". We use an objective,
arguable-with criterion instead:

    An extracted rule MATCHES a ground-truth rule when it cites a source
    line within +/- LINE_TOLERANCE of any line the ground-truth rule spans.

Line provenance is machine-checkable and phrasing-independent. Subject
agreement is reported SEPARATELY as a quality signal rather than folded
into the match decision, so a correct extraction with an awkward name is
not punished as a miss.

    precision = matched_extracted / total_extracted   (how much noise?)
    recall    = matched_truth    / total_truth        (how much missed?)

Usage:
    python tests/evaluate_rules.py                 # evaluate current output
    python tests/evaluate_rules.py --baseline      # write BASELINE.json
    python tests/evaluate_rules.py --compare       # diff against BASELINE.json
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "scripts"
GT_DIR = ROOT / "tests" / "fixtures" / "ground_truth"
BASELINE_PATH = GT_DIR / "BASELINE.json"

# A rule legitimately spans a few lines (condition on one, RAISE on the next).
LINE_TOLERANCE = 2


def build_pipeline(work: Path) -> Path:
    """Run stages 1-5 against src/ and return the rules run directory."""
    inv = work / "inventory"
    subprocess.run([sys.executable, str(SCRIPTS / "01_inventory.py"), str(ROOT / "src"),
                    "--output", str(inv / "run" / "inventory-artifact.json")],
                   capture_output=True, text=True, check=True)
    (inv / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "t"}))

    parser = work / "parser"
    subprocess.run([sys.executable, str(SCRIPTS / "02_parser.py"), "--inventory-root", str(inv),
                    "--output", str(parser / "run")], capture_output=True, text=True, check=True)
    (parser / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/parser_artifact.json", "updated_at": "t"}))

    data = work / "data"
    subprocess.run([sys.executable, str(SCRIPTS / "03_data.py"), "--inventory-root", str(inv),
                    "--parser-root", str(parser), "--output", str(data / "run")],
                   capture_output=True, text=True, check=True)
    (data / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/data_artifact.json", "updated_at": "t"}))

    logic = work / "logic"
    subprocess.run([sys.executable, str(SCRIPTS / "04_logic.py"), "--parser-root", str(parser),
                    "--inventory-root", str(inv), "--output", str(logic / "run")],
                   capture_output=True, text=True, check=True)
    (logic / "latest.json").write_text(json.dumps(
        {"run_version": "run", "path": "run/logic_artifact.json", "updated_at": "t"}))

    rules = work / "rules"
    cmd = [sys.executable, str(SCRIPTS / "05_rules.py"), "--parser-root", str(parser),
           "--data-root", str(data), "--inventory-root", str(inv), "--output", str(rules / "run")]
    # The redesigned agent consumes logic output; tolerate the older signature.
    r = subprocess.run(cmd + ["--logic-root", str(logic)], capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return rules / "run"


def extracted_rules_for(rules_artifact: dict, object_id: str) -> list[dict]:
    out = []
    for r in rules_artifact.get("business_rules", []):
        src = r.get("source", {})
        if src.get("object_id") != object_id:
            continue
        lines = []
        if src.get("line"):
            lines.append(src["line"])
        for extra in r.get("source_lines", []) or []:
            lines.append(extra)
        out.append({"rule_id": r.get("rule_id"), "name": r.get("name"),
                    "lines": lines, "category": r.get("category"),
                    "condition": r.get("condition_text", "")})
    return out


def evaluate_object(gt: dict, extracted: list[dict]) -> dict:
    truth = gt["rules"]
    matched_truth, matched_extracted = set(), set()
    pairs = []

    # Assign each ground-truth rule its CLOSEST unmatched candidate, not the
    # first one within tolerance. First-match is order-dependent and lets an
    # earlier rule greedily consume a line that plainly belongs to a later one
    # (observed: a formula at line 49 swallowing the guard at line 54, which
    # then reported as a miss even though it had been extracted correctly).
    for ti, t in enumerate(truth):
        best_ei, best_dist = None, None
        for ei, e in enumerate(extracted):
            if ei in matched_extracted:
                continue
            dists = [abs(el - tl) for el in e["lines"] for tl in t["source_lines"]]
            if not dists:
                continue
            d = min(dists)
            if d <= LINE_TOLERANCE and (best_dist is None or d < best_dist):
                best_ei, best_dist = ei, d
        if best_ei is not None:
            e = extracted[best_ei]
            matched_truth.add(ti)
            matched_extracted.add(best_ei)
            subject_ok = t["subject"].lower().lstrip("pv_") in (e["name"] or "").lower().replace(" ", "_")
            pairs.append({"truth": t["id"], "truth_statement": t["statement"],
                          "extracted": e["rule_id"], "extracted_name": e["name"],
                          "subject_agreement": subject_ok})

    tp = len(matched_truth)
    precision = tp / len(extracted) if extracted else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "object_id": gt["object_id"],
        "ground_truth_count": len(truth),
        "extracted_count": len(extracted),
        "matched": tp,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "subject_agreement_rate": round(
            sum(1 for p in pairs if p["subject_agreement"]) / len(pairs), 4) if pairs else 0.0,
        "missed_rules": [{"id": t["id"], "statement": t["statement"], "lines": t["source_lines"]}
                          for i, t in enumerate(truth) if i not in matched_truth],
        "unmatched_extracted": [{"rule_id": e["rule_id"], "name": e["name"], "lines": e["lines"]}
                                 for i, e in enumerate(extracted) if i not in matched_extracted],
        "pairs": pairs,
    }


def run_evaluation() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        rules_dir = build_pipeline(Path(tmp))
        artifact = json.loads((rules_dir / "rules_artifact.json").read_text(encoding="utf-8"))

    results, tot_tp, tot_ex, tot_gt = [], 0, 0, 0
    for gt_file in sorted(GT_DIR.glob("*.json")):
        if gt_file.name == "BASELINE.json":
            continue
        gt = json.loads(gt_file.read_text(encoding="utf-8"))
        res = evaluate_object(gt, extracted_rules_for(artifact, gt["object_id"]))
        results.append(res)
        tot_tp += res["matched"]
        tot_ex += res["extracted_count"]
        tot_gt += res["ground_truth_count"]

    p = tot_tp / tot_ex if tot_ex else 0.0
    r = tot_tp / tot_gt if tot_gt else 0.0
    return {
        "overall": {
            "precision": round(p, 4), "recall": round(r, 4),
            "f1": round(2 * p * r / (p + r), 4) if (p + r) else 0.0,
            "matched": tot_tp, "extracted": tot_ex, "ground_truth": tot_gt,
        },
        "per_object": results,
    }


def report(ev: dict) -> None:
    o = ev["overall"]
    print("=" * 66)
    print("RULES AGENT — GROUND TRUTH EVALUATION")
    print("=" * 66)
    print(f"  Precision : {o['precision']:.3f}   ({o['matched']}/{o['extracted']} extracted rules are real)")
    print(f"  Recall    : {o['recall']:.3f}   ({o['matched']}/{o['ground_truth']} real rules were found)")
    print(f"  F1        : {o['f1']:.3f}")
    print(f"\n  For reference — published results on COBOL:")
    print(f"    COBREX (rule-based)  F1 0.59      COBRAIN (LLM)  F1 0.73")
    print(f"    A-COBREX  P 0.62 / R 0.74")
    for res in ev["per_object"]:
        print(f"\n--- {res['object_id']}")
        print(f"    P {res['precision']:.3f}  R {res['recall']:.3f}  F1 {res['f1']:.3f}"
              f"   (matched {res['matched']}/{res['ground_truth_count']}, "
              f"extracted {res['extracted_count']})")
        print(f"    subject agreement on matches: {res['subject_agreement_rate']:.3f}")
        if res["missed_rules"]:
            print("    MISSED:")
            for m in res["missed_rules"]:
                print(f"      - [{m['id']}] {m['statement'][:78]}  (lines {m['lines']})")
        if res["unmatched_extracted"]:
            print("    EXTRACTED BUT NOT IN GROUND TRUTH (noise or over-extraction):")
            for u in res["unmatched_extracted"][:8]:
                print(f"      - {u['rule_id']} {u['name']}  (line {u['lines']})")
    print()


def main() -> int:
    ev = run_evaluation()
    report(ev)

    if "--baseline" in sys.argv:
        BASELINE_PATH.write_text(json.dumps(ev, indent=2), encoding="utf-8")
        print(f"Baseline written to {BASELINE_PATH}")
        return 0

    if "--compare" in sys.argv and BASELINE_PATH.exists():
        base = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["overall"]
        cur = ev["overall"]
        print("=" * 66)
        print("CHANGE VS BASELINE")
        print("=" * 66)
        for k in ("precision", "recall", "f1"):
            delta = cur[k] - base[k]
            arrow = "improved" if delta > 0 else ("regressed" if delta < 0 else "unchanged")
            print(f"  {k:10}: {base[k]:.3f} -> {cur[k]:.3f}   ({delta:+.3f}, {arrow})")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
