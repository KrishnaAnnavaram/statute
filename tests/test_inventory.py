#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/01_inventory.py.

Two layers:
  1. Explicit structural assertions — readable failures that say WHAT broke.
  2. A golden-file diff over the normalised artifact — catches anything the
     explicit assertions don't think to check.

Normalisation (why these fields are excluded from the golden diff):
    generated_at   run timestamp, different every run
    source_dir     absolute path, different on every machine
    abs_path       absolute path, different on every machine
    last_modified  file mtime — changes on every git clone
    sha256         content hash; shifts with CRLF/LF line-ending translation
    size_bytes     same line-ending problem

Everything that actually exercises the agent's logic — file_id derivation,
role classification, complexity scoring, content hints, line counts, summary
aggregation, warnings — is compared exactly.

NOTE ON SCOPE: this agent produces a FILE-level inventory. It does not
produce an object_registry or dependency_graph, despite those appearing in
.claude/skills/{file-catalog,reference-graph}/SKILL.md. That is a known,
tracked feature gap (see .claude/agents/2_parser_agent.md, "Known scope
limitation") — Agent 2 currently performs its own object discovery to
compensate. This test therefore asserts the schema the agent ACTUALLY has;
it is not a statement that the larger schema was abandoned.

Usage:
    python tests/test_inventory.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "sample_plsql"
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "expected-inventory-artifact.json"
SCRIPT_PATH = ROOT / ".claude" / "scripts" / "01_inventory.py"

NORMALISED = "<normalised>"
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def normalize(artifact: dict) -> dict:
    """Strip environment-dependent values so the golden diff is portable."""
    a = json.loads(json.dumps(artifact))  # deep copy
    a["generated_at"] = NORMALISED
    a["source_dir"] = NORMALISED
    for meta in a.get("file_metadata", {}).values():
        for field in ("abs_path", "last_modified", "sha256", "size_bytes"):
            if field in meta:
                meta[field] = NORMALISED
    return a


def run_inventory(out_path: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(FIXTURE_DIR), "--output", str(out_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"01_inventory.py exited {result.returncode}\n{result.stdout}\n{result.stderr}")
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_structure(artifact: dict) -> None:
    print("\n=== Artifact structure ===")
    expected_keys = {"pipeline_stage", "schema_version", "generated_at", "source_dir",
                     "cli_args", "summary", "file_index", "file_metadata"}
    check(set(artifact) == expected_keys,
          f"top-level keys are exactly the file-level inventory schema (unexpected: "
          f"{set(artifact) ^ expected_keys or 'none'})")
    check(artifact["pipeline_stage"] == "01_inventory", "pipeline_stage identifies the producing stage")
    check(artifact["schema_version"] == "2.0", "schema_version is 2.0")
    check(set(artifact["file_index"]) == set(artifact["file_metadata"]),
          "file_index and file_metadata are keyed by the same file_ids (normalised, not duplicated)")


def test_file_ids(artifact: dict) -> None:
    print("\n=== Stable file_id derivation ===")
    ids = artifact["file_index"]
    check(len(ids) == 7, f"all 7 fixture files catalogued, got {len(ids)}")
    check(all("__" in fid for fid in ids), "every file_id has the SLUG__HASH shape")
    check("02_ACCOUNT_MGMT__C1C9EA52" in ids,
          "file_id is derived from the relative path and is therefore stable across runs")
    check(ids.get("02_ACCOUNT_MGMT__C1C9EA52") == "02_account_mgmt.sql",
          "file_index maps the id back to its relative path")


def test_classification(artifact: dict) -> None:
    print("\n=== Role and complexity classification ===")
    meta = artifact["file_metadata"]
    by_path = {m["file"]: m for m in meta.values()}

    check(by_path["02_account_mgmt.sql"]["file_role"] == "package", "package file classified as package")
    check(by_path["03_seed.sql"]["file_role"] == "seed_data", "INSERT-only file classified as seed_data")
    check(by_path["V002__add_status_column.sql"]["file_role"] == "migration",
          "Flyway-named file classified as migration by filename convention")
    check(by_path["00_run_all.sql"]["file_role"] == "unknown",
          "SQL*Plus include-only script has no recognisable role")

    check(by_path["02_account_mgmt.sql"]["complexity"] == "high",
          "file with dynamic SQL and DBMS calls scored high complexity")
    hints = by_path["02_account_mgmt.sql"]["content_hints"]
    check(hints.get("has_dynamic_sql") is True, "EXECUTE IMMEDIATE detected as a content hint")
    check(hints.get("has_package") is True, "CREATE PACKAGE detected as a content hint")
    check("has_forall" not in hints, "absent hints are omitted rather than emitted as false")


def test_summary(artifact: dict) -> None:
    print("\n=== Summary aggregation ===")
    s = artifact["summary"]
    check(s["total_files_found"] == 7 and s["total_files_ok"] == 7, "all 7 files read successfully")
    check(s["total_files_excluded"] == 0, "no fixture file matched an exclusion pattern")
    check(s["files_by_role"].get("package") == 2, "both package files counted by role")
    check(s["high_complexity_files"] == ["02_account_mgmt.sql"],
          "high-complexity files surfaced by name for downstream prioritisation")
    check(s["total_code_lines"] < s["total_lines"],
          "code_lines excludes blank and comment-only lines")


def test_golden_diff(artifact: dict) -> None:
    print("\n=== Golden-file diff (normalised) ===")
    if not GOLDEN_PATH.exists():
        check(False, f"golden fixture missing at {GOLDEN_PATH}")
        return
    actual = normalize(artifact)
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if actual == expected:
        check(True, "normalised artifact is byte-identical to the golden fixture")
        return

    import difflib
    diff = list(difflib.unified_diff(
        json.dumps(expected, indent=2, sort_keys=True).splitlines(),
        json.dumps(actual, indent=2, sort_keys=True).splitlines(),
        "expected", "actual", lineterm=""))
    check(False, "normalised artifact matches the golden fixture")
    print("\n".join(diff[:60]))
    print(f"\n  To accept these changes deliberately:\n"
          f"    python tests/test_inventory.py --update-golden")


def update_golden() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        artifact = run_inventory(Path(tmp) / "inventory-artifact.json")
    GOLDEN_PATH.write_text(
        json.dumps(normalize(artifact), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"Golden fixture regenerated: {GOLDEN_PATH}")
    print("Review the diff before committing — this file is the regression baseline.")
    return 0


def main() -> int:
    if "--update-golden" in sys.argv:
        return update_golden()

    with tempfile.TemporaryDirectory() as tmp:
        artifact = run_inventory(Path(tmp) / "inventory-artifact.json")

    test_structure(artifact)
    test_file_ids(artifact)
    test_classification(artifact)
    test_summary(artifact)
    test_golden_diff(artifact)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
