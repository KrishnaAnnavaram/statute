#!/usr/bin/env python3
"""
Golden-file regression test for 00_inventory.py.

Runs the inventory tool against tests/fixtures/sample_plsql/ and asserts
the result is byte-identical to tests/fixtures/expected-inventory-artifact.json,
except for meta.generated_at (the one field the tool is allowed to vary).

This guards against silent under-detection: any change to the taxonomy,
id assignment, boundary marking, or reference-graph regexes that alters
the artifact shape will fail this test until the golden file is
deliberately regenerated and reviewed.

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
SCRIPT_PATH = ROOT / ".claude" / "scripts" / "00_inventory.py"


def normalize(artifact: dict) -> dict:
    artifact = json.loads(json.dumps(artifact))  # deep copy
    artifact["meta"]["generated_at"] = "NORMALIZED"
    return artifact


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        output_path = Path(tmp) / "inventory-artifact.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), str(FIXTURE_DIR), "--output", str(output_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("FAIL: 00_inventory.py exited non-zero")
            print(result.stdout)
            print(result.stderr)
            return 1

        actual = json.loads(output_path.read_text(encoding="utf-8"))
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

        actual_n = normalize(actual)
        expected_n = normalize(expected)

        if actual_n == expected_n:
            print("PASS: inventory-artifact.json matches golden fixture "
                  "(byte-equal except meta.generated_at).")
            return 0

        print("FAIL: inventory-artifact.json does not match golden fixture.")
        actual_s = json.dumps(actual_n, indent=2, sort_keys=True).splitlines()
        expected_s = json.dumps(expected_n, indent=2, sort_keys=True).splitlines()
        import difflib
        diff = list(difflib.unified_diff(expected_s, actual_s, "expected", "actual", lineterm=""))
        print("\n".join(diff[:200]))
        return 1


if __name__ == "__main__":
    sys.exit(main())
