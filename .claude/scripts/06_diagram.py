#!/usr/bin/env python3
"""
Stage 6: DIAGRAM (deterministic, no LLM)
--------------------------------------------
Translates existing structured data into Mermaid diagrams. Does not
extract or interpret anything new — the ERD is already Agent 3's job
(it owns the entity model that produces it); this agent covers what's
left: a component diagram from Agent 2's resolved CALL edges, and a
per-object process-flow diagram from Agent 2's control_flow_graph.

Zero LLM calls. 100% deterministic.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


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


def safe_node_id(object_id: str) -> str:
    # Mermaid node IDs starting with a digit are unreliable across
    # renderers — a statement_id like "02_SIMPLE_..." would produce one.
    # Prefix everything so this can never happen regardless of source id.
    return "N_" + re.sub(r"[^A-Za-z0-9]", "_", object_id)


def build_component_diagram(parser_artifact: dict, parser_root: Path, rules_by_object: dict[str, int]) -> tuple[str, int, int]:
    lines = ["flowchart LR"]
    node_ids: dict[str, str] = {}
    edges: list[tuple[str, str, bool]] = []

    for object_id in parser_artifact["object_index"]:
        node_ids[object_id] = safe_node_id(object_id)

    for object_id, rel_path in parser_artifact["object_index"].items():
        obj_path = parser_root / rel_path
        if not obj_path.exists():
            continue
        obj = json.loads(obj_path.read_text(encoding="utf-8"))
        for stmt in obj.get("statements", {}).values():
            if stmt.get("statement_type") != "CALL":
                continue
            target_id = stmt.get("call_target_object_id")
            if target_id and target_id in node_ids:
                edges.append((object_id, target_id, True))
            elif not stmt.get("resolved"):
                external_label = stmt.get("call_target", "EXTERNAL")
                external_id = safe_node_id(f"EXT_{external_label}")
                if external_id not in node_ids.values():
                    lines.append(f'    {external_id}["{external_label}\\n(external/unresolved)"]:::external')
                    node_ids[f"__ext__{external_label}"] = external_id
                edges.append((object_id, f"__ext__{external_label}", False))

    for object_id, node_id in node_ids.items():
        if object_id.startswith("__ext__"):
            continue
        rule_count = rules_by_object.get(object_id, 0)
        label = object_id.replace("::", "\\n::")
        suffix = f"\\n({rule_count} rule{'s' if rule_count != 1 else ''})" if rule_count else ""
        lines.append(f'    {node_id}["{label}{suffix}"]')

    for src, dst, resolved in edges:
        src_id = node_ids.get(src)
        dst_id = node_ids.get(dst)
        if not src_id or not dst_id:
            continue
        arrow = "-->" if resolved else "-.->|unresolved| "
        lines.append(f"    {src_id} {arrow} {dst_id}" if resolved else f"    {src_id} -.-> {dst_id}")

    lines.append("    classDef external fill:#f5f5f5,stroke:#999,stroke-dasharray: 4 2")
    return "\n".join(lines) + "\n", len(node_ids), len(edges)


_CFG_LABELS = {
    "IF": "Decision", "LOOP": "Repeat", "CASE": "Select Case",
    "EXCEPTION_HANDLER": "On Error", "COMMIT": "Commit", "ROLLBACK": "Rollback",
}


def short_label(stmt_id: str, statements: dict) -> str:
    s = statements.get(stmt_id)
    if not s:
        return stmt_id
    kind = _CFG_LABELS.get(s["statement_type"], s["statement_type"])
    return f"{kind}\\nL{s['start_line']}"


def build_flow_diagram(object_id: str, obj: dict) -> str:
    statements = obj.get("statements", {})
    cfg = obj.get("control_flow_graph", {"nodes": [], "edges": []})
    if not cfg["nodes"]:
        return ""

    lines = ["flowchart TD", f'    START(["{object_id}"])']
    node_ids = {sid: safe_node_id(sid) for sid in cfg["nodes"]}
    for sid, nid in node_ids.items():
        lines.append(f'    {nid}["{short_label(sid, statements)}"]')

    # The true entry point is the top-level statement (parent_id is None)
    # with the lowest sequence number — NOT "whatever edge happens to be
    # first in the list", which is order-fragile once BRANCH_ENTRY edges
    # are mixed in alongside SEQUENCE edges.
    top_level = [s for s in statements.values() if s.get("parent_id") is None]
    if top_level:
        first_stmt = min(top_level, key=lambda s: s["statement_id"])
        lines.append(f"    START --> {node_ids.get(first_stmt['statement_id'], 'START')}")

    for e in cfg["edges"]:
        if e["from"] == "*":
            continue
        src, dst = node_ids.get(e["from"]), node_ids.get(e["to"])
        if not src or not dst:
            continue
        if e["type"] == "EXCEPTION_EDGE":
            style = "-.->|exception|"
        elif e["type"] == "LOOP_BACK_EDGE":
            style = "-->|loop back|"
        elif e["type"] == "BRANCH_ENTRY":
            style = f'-->|{e.get("branch", "")}|'
        else:
            style = "-->"
        lines.append(f"    {src} {style} {dst}")

    for e in cfg["edges"]:
        if e["from"] == "*" and node_ids.get(e["to"]):
            lines.append(f'    ANY_ERROR{{"Any statement"}} -.->|{e.get("on", "OTHERS")}| {node_ids[e["to"]]}')

    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 6: Deterministic PL/SQL diagram generator")
    ap.add_argument("--parser-root", default="output/parser")
    ap.add_argument("--parser-run", default="latest")
    ap.add_argument("--rules-root", default="output/rules")
    ap.add_argument("--rules-run", default="latest")
    ap.add_argument("--output-root", default="output/diagram")
    ap.add_argument("--output", default=None)
    ap.add_argument("--max-nodes", type=int, default=40)
    args = ap.parse_args()

    parser_artifact, parser_run_version = load_run(args.parser_root, args.parser_run, "parser_artifact.json")
    parser_root = Path(args.parser_root) / parser_run_version
    try:
        rules_artifact, rules_run_version = load_run(args.rules_root, args.rules_run, "rules_artifact.json")
    except FileNotFoundError:
        rules_artifact, rules_run_version = {"business_rules": []}, None

    rules_by_object: dict[str, int] = {}
    for r in rules_artifact.get("business_rules", []):
        oid = r.get("source", {}).get("object_id")
        if oid:
            rules_by_object[oid] = rules_by_object.get(oid, 0) + 1

    versioned_run = args.output is None
    run_version = generate_run_version()
    run_dir = Path(args.output_root) / run_version if versioned_run else Path(args.output)
    diagrams_dir = run_dir / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    component_mmd, node_count, edge_count = build_component_diagram(parser_artifact, parser_root, rules_by_object)
    (diagrams_dir / "component_overview.mmd").write_text(component_mmd, encoding="utf-8")

    diagram_index = {"component_overview.mmd": {"type": "component", "nodes": node_count, "edges": edge_count}}
    flow_count = 0
    for object_id, rel_path in parser_artifact["object_index"].items():
        obj_path = parser_root / rel_path
        if not obj_path.exists():
            continue
        obj = json.loads(obj_path.read_text(encoding="utf-8"))
        flow_mmd = build_flow_diagram(object_id, obj)
        if not flow_mmd:
            continue
        fname = f"flow_{safe_node_id(object_id)}.mmd"
        (diagrams_dir / fname).write_text(flow_mmd, encoding="utf-8")
        diagram_index[fname] = {"type": "process_flow", "object_id": object_id}
        flow_count += 1

    diagrams_artifact = {
        "pipeline_stage": "6_diagram", "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream": {"parser_run_version": parser_run_version, "rules_run_version": rules_run_version},
        "diagram_index": diagram_index,
        "stats": {"component_nodes": node_count, "component_edges": edge_count, "process_flow_diagrams": flow_count},
    }
    (run_dir / "diagrams_artifact.json").write_text(json.dumps(diagrams_artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    if versioned_run:
        (run_dir / "run_meta.json").write_text(json.dumps(
            {"stage": "6_diagram", "run_version": run_version, "status": "success",
             "generated_at": diagrams_artifact["generated_at"], "upstream": diagrams_artifact["upstream"]},
            indent=2), encoding="utf-8")
        (Path(args.output_root) / "latest.json").write_text(json.dumps(
            {"run_version": run_version, "path": f"{run_version}/diagrams_artifact.json",
             "updated_at": diagrams_artifact["generated_at"]}, indent=2), encoding="utf-8")

    print("=== Diagram Agent Complete ===")
    print(f"Component diagram    : {node_count} nodes, {edge_count} edges")
    print(f"Process flow diagrams: {flow_count}")
    print(f"Output                : {run_dir / 'diagrams_artifact.json'}")
    print("==============================")


if __name__ == "__main__":
    main()
