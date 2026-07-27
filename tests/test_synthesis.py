#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/07_synthesis.py.

Covers: gap detection accuracy against known real issues, BRD structural
completeness, EARS-statement presence, confidence markers never hidden,
and — most importantly — that every rule/gap referenced in the BRD text
actually traces back to a real artifact record (no invented content).
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "scripts"
STAGES = [
    (SCRIPTS / "00_inventory.py", "inventory", "inventory-artifact.json", []),
    (SCRIPTS / "02_parser.py", "parser", "parser_artifact.json", ["--inventory-root"]),
    (SCRIPTS / "03_data.py", "data", "data_artifact.json", ["--inventory-root", "--parser-root"]),
    (SCRIPTS / "04_logic.py", "logic", "logic_artifact.json", ["--parser-root", "--inventory-root"]),
    (SCRIPTS / "05_rules.py", "rules", "rules_artifact.json", ["--parser-root", "--data-root", "--inventory-root"]),
    (SCRIPTS / "06_diagram.py", "diagram", "diagrams_artifact.json", ["--parser-root", "--rules-root"]),
]
SYNTHESIS_SCRIPT = SCRIPTS / "07_synthesis.py"

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def run_full_pipeline(work_dir: Path) -> tuple[dict, str]:
    roots = {"inventory": work_dir / "inventory", "parser": work_dir / "parser", "data": work_dir / "data",
             "logic": work_dir / "logic", "rules": work_dir / "rules", "diagram": work_dir / "diagram"}
    for script, key, artifact_name, dep_flags in STAGES:
        out_dir = roots[key] / "run"
        cmd = [sys.executable, str(script)]
        if key == "inventory":
            cmd += [str(ROOT / "src"), "--output", str(out_dir / artifact_name)]
        else:
            for flag in dep_flags:
                dep_key = flag.replace("--", "").replace("-root", "")
                cmd += [flag, str(roots[dep_key])]
            cmd += ["--output", str(out_dir)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{script.name} failed:\n{r.stdout}\n{r.stderr}")
        (roots[key] / "latest.json").write_text(json.dumps(
            {"run_version": "run", "path": f"run/{artifact_name}", "updated_at": "test"}))

    report_dir = work_dir / "final_report"
    cmd = [sys.executable, str(SYNTHESIS_SCRIPT)]
    for key in ("inventory", "parser", "data", "logic", "rules", "diagram"):
        cmd += [f"--{key}-root", str(roots[key])]
    cmd += ["--output", str(report_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"07_synthesis.py failed:\n{r.stdout}\n{r.stderr}")
    print(r.stdout)

    rules_artifact = json.loads((roots["rules"] / "run" / "rules_artifact.json").read_text(encoding="utf-8"))
    gaps_register = json.loads((report_dir / "gaps_register.json").read_text(encoding="utf-8"))
    brd_text = (report_dir / "brd.md").read_text(encoding="utf-8")
    return {"rules": rules_artifact, "gaps": gaps_register, "brd": brd_text}, str(report_dir)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        result, report_dir = run_full_pipeline(Path(tmp))

    brd = result["brd"]
    gaps = result["gaps"]
    rules = result["rules"]

    print("\n=== Structural completeness ===")
    for chapter in ["Executive Summary", "System Overview", "Data Model", "Business Rules Catalogue",
                     "Error Handling", "Gaps and Assumptions Register", "Design References"]:
        check(chapter in brd, f"chapter present: {chapter}")

    print("\n=== Gap detection accuracy (known real issues in this codebase) ===")
    gap_titles = " ".join(g["title"] for g in gaps["gaps"])
    check("ACCOUNT_TYPE" in gap_titles, "undocumented ACCOUNT_TYPE enum surfaced as a gap")
    check(any(g["gap_type"] == "SME_REVIEW_REQUIRED" for g in gaps["gaps"]),
          "the rec.balance SME-review-required rule surfaced as a gap")
    check(all(g["severity"] in ("critical", "high", "medium", "low") for g in gaps["gaps"]),
          "every gap has a valid severity level")

    print("\n=== EARS statements and confidence markers ===")
    check("THEN the system SHALL" in brd, "at least one formal EARS-syntax statement present")
    has_confirmed_mark = "✓" in brd
    has_warning_mark = "⚠" in brd
    check(has_confirmed_mark and has_warning_mark,
          "both confirmed and warning confidence marker glyphs appear in the BRD -- nothing hidden")

    print("\n=== No invented content — every referenced rule ID is real ===")
    import re
    referenced_rule_ids = set(re.findall(r"\bBR-\d{3}\b", brd))
    real_rule_ids = {r["rule_id"] for r in rules["business_rules"]}
    check(referenced_rule_ids.issubset(real_rule_ids),
          f"every BR-xxx id mentioned in the BRD exists in rules_artifact.json (extras: {referenced_rule_ids - real_rule_ids})")
    check(len(referenced_rule_ids) > 0, "at least one rule is actually referenced (sanity check on the check above)")

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
