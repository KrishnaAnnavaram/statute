#!/usr/bin/env python3
"""
Regression tests for .claude/scripts/06_diagram.py and the CFG fix it
surfaced in 02_parser.py's build_cfg.

Two real bugs found by inspecting actual rendered output, not by
inspection of the code:
  1. build_cfg only ever linked SIBLINGS to each other — a decision
     (IF) node had no edge to ANY of its branches, only a fallthrough
     edge to whatever follows the whole IF/ELSIF/ELSE. A rendered
     diagram would show the decision skipping straight past all three
     branches.
  2. Mermaid node IDs derived directly from statement_ids can start with
     a digit (e.g. "02_SIMPLE_..."), which is unreliable across
     Mermaid renderers.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY_SCRIPT = ROOT / ".claude" / "scripts" / "00_inventory.py"
PARSER_SCRIPT = ROOT / ".claude" / "scripts" / "02_parser.py"
DIAGRAM_SCRIPT = ROOT / ".claude" / "scripts" / "06_diagram.py"

sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        inv_dir = work_dir / "inventory"
        subprocess.run([sys.executable, str(INVENTORY_SCRIPT), str(ROOT / "src"),
                         "--output", str(inv_dir / "run" / "inventory-artifact.json")],
                        capture_output=True, text=True, check=True)
        (inv_dir / "latest.json").write_text(json.dumps(
            {"run_version": "run", "path": "run/inventory-artifact.json", "updated_at": "test"}))

        parser_dir = work_dir / "parser"
        subprocess.run([sys.executable, str(PARSER_SCRIPT), "--inventory-root", str(inv_dir),
                         "--output", str(parser_dir / "run")], capture_output=True, text=True, check=True)
        (parser_dir / "latest.json").write_text(json.dumps(
            {"run_version": "run", "path": "run/parser_artifact.json", "updated_at": "test"}))

        # Regression guard #1, checked directly on Agent 2's CFG output
        obj = json.loads((parser_dir / "run" / "raw_structure" /
                           "PROC-.SP_UPDATE_DORMANT_ACCOUNT_STATUS.json").read_text(encoding="utf-8"))
        cfg = obj["control_flow_graph"]
        branch_entries = [e for e in cfg["edges"] if e["type"] == "BRANCH_ENTRY"]
        if_stmt_id = next(s["statement_id"] for s in obj["statements"].values() if s["statement_type"] == "IF")
        from_if = {e["branch"]: e["to"] for e in branch_entries if e["from"] == if_stmt_id}
        check(len(branch_entries) >= 3, "CFG has BRANCH_ENTRY edges (decision connects to its branches, not just siblings)")
        check(set(from_if.keys()) == {"true", "elsif", "false"}, f"IF has true/elsif/false branch entries, got {set(from_if.keys())}")

        diagram_dir = work_dir / "diagram_out"
        r = subprocess.run([sys.executable, str(DIAGRAM_SCRIPT), "--parser-root", str(parser_dir),
                             "--output", str(diagram_dir)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"06_diagram.py failed:\n{r.stdout}\n{r.stderr}")
        print(r.stdout)

        flow_files = list((diagram_dir / "diagrams").glob("flow_*SP_UPDATE_DORMANT*.mmd"))
        check(len(flow_files) == 1, "flow diagram generated for the dormant-account procedure")
        if flow_files:
            text = flow_files[0].read_text(encoding="utf-8")
            check(text.startswith("flowchart TD"), "flow diagram starts with a valid Mermaid declaration")
            check("-->|true|" in text and "-->|elsif|" in text and "-->|false|" in text,
                  "rendered diagram shows all three branch labels on the decision node")
            node_id_lines = [l.strip().split("[")[0].split("(")[0] for l in text.splitlines()
                              if l.strip() and not l.strip().startswith(("flowchart", "START", "ANY_ERROR"))]
            bad_ids = [nid for nid in node_id_lines if nid and nid[0].isdigit()]
            check(not bad_ids, f"no Mermaid node id starts with a digit, found: {bad_ids}")

        component_text = (diagram_dir / "diagrams" / "component_overview.mmd").read_text(encoding="utf-8")
        check("RAISE_APPLICATION_ERROR" not in component_text or "external" not in component_text.lower(),
              "RAISE_APPLICATION_ERROR (a standard Oracle builtin) is not drawn as an external/unresolved node")

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll tests passed.")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
