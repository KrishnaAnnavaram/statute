"""The STATUTE stage contract as the console understands it.

This is a *declared* registry, so health check H8 re-derives each stage's inputs
from the script's own argparse flags and reports any disagreement — the
registry cannot silently drift from the code.
"""
from __future__ import annotations

STAGES: list[dict] = [
    {"key": "01_inventory", "n": 1, "dir": "inventory", "title": "Inventory",
     "artifact": "inventory-artifact.json", "script": "01_inventory.py",
     "agent": "1_inventory_plsql_agent.md", "requires": [], "optional": [],
     "purpose": "Catalogue .sql files, classify roles, assign stable file IDs and hashes"},
    {"key": "02_parser", "n": 2, "dir": "parser", "title": "Parser",
     "artifact": "parser_artifact.json", "script": "02_parser.py",
     "agent": "2_parser_agent.md", "requires": ["01_inventory"], "optional": [],
     "purpose": "ANTLR parse of procedures, functions, packages and triggers into statement trees and control flow"},
    {"key": "03_data", "n": 3, "dir": "data", "title": "Data",
     "artifact": "data_artifact.json", "script": "03_data.py",
     "agent": "3_data_agent.md", "requires": ["01_inventory", "02_parser"], "optional": [],
     "purpose": "DDL to data dictionary with constraint enforcement state, ERD and cross-validation"},
    {"key": "04_logic", "n": 4, "dir": "logic", "title": "Logic",
     "artifact": "logic_artifact.json", "script": "04_logic.py",
     "agent": "4_logic_agent.md", "requires": ["01_inventory", "02_parser"], "optional": [],
     "purpose": "Pseudocode, complexity, variable slices, CRUD matrix and transaction hazards"},
    {"key": "05_rules", "n": 5, "dir": "rules", "title": "Rules",
     "artifact": "rules_artifact.json", "script": "05_rules.py",
     "agent": "5_rules_agent.md", "requires": ["01_inventory", "02_parser", "03_data"],
     "optional": ["04_logic"],
     "purpose": "Mine, name, classify and de-duplicate business rules from nine sources"},
    {"key": "06_diagram", "n": 6, "dir": "diagram", "title": "Diagram",
     "artifact": "diagrams_artifact.json", "script": "06_diagram.py",
     "agent": "6_diagram_agent.md", "requires": ["02_parser"],
     "optional": ["01_inventory", "03_data", "04_logic", "05_rules"],
     "purpose": "Renderer-agnostic diagram model rendered to Mermaid, with quality gates"},
    {"key": "07_synthesis", "n": 7, "dir": "final_report", "title": "Synthesis",
     "artifact": "brd_index.json", "script": "07_synthesis.py",
     "agent": "7_synthesis_agent.md",
     "requires": ["01_inventory", "02_parser", "03_data", "04_logic", "05_rules", "06_diagram"],
     "optional": [],
     "purpose": "Business Requirements Document, machine index and gaps register"},
    {"key": "08_graph", "n": 8, "dir": "graph", "title": "Graph",
     "artifact": "graph_artifact.json", "script": "08_graph.py",
     "agent": "8_graph_agent.md", "requires": ["02_parser"],
     "optional": ["01_inventory", "03_data", "04_logic", "05_rules", "06_diagram", "07_synthesis"],
     "purpose": "Property-graph export (Cypher + CSV) and plain-English question interface"},
]

BY_KEY = {s["key"]: s for s in STAGES}
BY_DIR = {s["dir"]: s for s in STAGES}
ORDER = [s["key"] for s in STAGES]

# upstream field names used in run_meta.json -> canonical stage key
UPSTREAM_FIELDS = {
    "inventory_run_version": "01_inventory",
    "parser_run_version": "02_parser",
    "data_run_version": "03_data",
    "logic_run_version": "04_logic",
    "rules_run_version": "05_rules",
    "diagram_run_version": "06_diagram",
    "report_run_version": "07_synthesis",
}

# argparse "--<x>-root" flag names -> canonical stage key (used by health check H8)
ROOT_FLAGS = {
    "inventory": "01_inventory", "parser": "02_parser", "data": "03_data", "logic": "04_logic",
    "rules": "05_rules", "diagram": "06_diagram", "report": "07_synthesis",
}

# run_meta "stage" values seen in the wild -> canonical key
LEGACY_STAGE_NAMES = {
    "01_inventory": "01_inventory", "1_inventory": "01_inventory",
    "2_parser": "02_parser", "3_data": "03_data", "4_logic": "04_logic", "5_rules": "05_rules",
    "6_diagram": "06_diagram", "7_synthesis": "07_synthesis", "8_graph": "08_graph",
}


def inputs_of(key: str) -> list[str]:
    s = BY_KEY[key]
    return s["requires"] + s["optional"]


def downstream_of(key: str) -> list[str]:
    return [s["key"] for s in STAGES if key in s["requires"] or key in s["optional"]]
