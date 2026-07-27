---
name: reference-graph
description: >
  Reads the object_registry produced by the file-catalog skill. Scans every
  file's content for outgoing cross-references — package/procedure calls,
  table reads/writes, trigger targets, file includes, %TYPE/%ROWTYPE
  dependencies, and dynamic SQL — and builds a directed dependency graph
  (nodes + typed edges). Collects all issues. Produces the final
  inventory-artifact.json schema sections: stats, dependency_graph, and
  issues. Implemented deterministically by 00_inventory.py; used
  exclusively by the Inventory Agent (1_inventory_plsql).
---

## Purpose

For every object in the object_registry, detect outgoing references to
other objects, tables, and packages. Build a directed graph. Distinguish
references to genuinely external/standard functionality from references
that should resolve locally but don't. Collect unresolved references and
dynamic references as issues.

Do NOT read or interpret PL/SQL logic, variable assignments, or control
flow inside a body. Only scan for the specific reference patterns below,
against content with string literals and comments already masked out.

---

## Edge types

| Edge type | Detected from | Notes |
|---|---|---|
| `CALLS` | `pkg.proc(` / `pkg.proc;` where `pkg` matches a known local `PACKAGE_SPEC`/`PACKAGE_BODY` name | Qualified call |
| `CALLS` | bare `proc_name(` or `proc_name;` where `proc_name` matches a known top-level `PROCEDURE`/`FUNCTION` | Unqualified call; restricted to registry-known names to avoid matching every expression/function call in the file |
| `CALLS` | `DBMS_*.member` / `UTL_*.member` | Always external — never an issue |
| `IMPLEMENTS_SPEC` | Every `PACKAGE_BODY`/`TYPE_BODY` is matched against a `PACKAGE_SPEC`/`TYPE_SPEC` of the same owner+name | If no match, logged as `unresolved_reference` |
| `READS` | `FROM table` / `JOIN table` | |
| `READS` | `table@dblink` | Creates an `EXTERNAL` `DBLINK-*` node; always resolved |
| `WRITES` | `INSERT INTO table`, `UPDATE table` (not `UPDATE SET`/`UPDATE ON`), `DELETE FROM table`, `MERGE INTO table` | |
| `TRIGGERS_ON` | `CREATE TRIGGER ... ON table` | Extracted once from the trigger's own header, not per-line |
| `INCLUDES` | `@file` / `@@file` (SQL\*Plus include) | Resolved against file_registry by filename match |
| `DEPENDS_ON` | `owner.column%TYPE` / `owner.table%ROWTYPE` | Bare `variable%TYPE` (no dot) is intentionally ignored — it references another PL/SQL variable, not a table |
| `DEPENDS_ON` | `INDEX ... ON table` | Index-to-table structural dependency |
| `DYNAMIC_REF` | `EXECUTE IMMEDIATE` | Target always `null`, `confirmed: false` — cannot be resolved statically. Logged as an `info`-severity issue, not a blocking one |

A CALLS/BARE-CALL scan is **never** run against an object's own header line
(the line containing its `CREATE`/`GRANT`/DML declaration) — that line's
`owner.name (columns...)` or `owner.name;` shape is structurally identical
to a call, but it is the object declaring itself, not calling anything.

---

## External vs. unresolved

- `DBMS_*` and `UTL_*` package references are always classified as
  `EXTERNAL` origin nodes (id: `EXTERNAL-<PACKAGE>`). They are resolved by
  definition and never generate an issue.
- A qualified call `pkg.proc(...)` where `pkg` is **not** `DBMS_*`/`UTL_*`
  and does not match any local package: edge recorded with `to: null`,
  `resolved: false`, plus an `unresolved_reference` warning — this looks
  like it should be a local package and isn't.
- `READS`/`WRITES` edges to a table not found in the local registry are
  recorded with `resolved: false` but **do not** generate an issue by
  default — most repositories legitimately read/write tables owned by
  schemas outside the scanned tree, and flagging every one would drown out
  genuinely high-signal issues.
- `TRIGGERS_ON`, `INCLUDES`, and `DEPENDS_ON` (%TYPE/%ROWTYPE) unresolved
  targets **do** generate an `unresolved_reference` warning — these three
  are structurally required to exist in-repo for the object to function,
  so a miss is meaningful.
- `CREATE SYNONYM ... FOR target` mappings are recorded on the synonym's
  own object_registry entry (`synonym_for`) only — never resolved through
  to build a transitive edge.

---

## Graph construction rules

```
1. Start with one node per object_registry entry (origin: REPO).
2. For each PACKAGE_BODY/TYPE_BODY, look for a matching PACKAGE_SPEC/
   TYPE_SPEC (same owner + name) -> IMPLEMENTS_SPEC edge or unresolved
   issue.
3. For every file, walk its masked, scaffold-stripped lines once. For each
   line, determine the enclosing object (the object_registry entry whose
   [start_line, terminator_line] span contains that line; falls back to
   the file_id if the line sits between objects). Apply every edge-type
   pattern above against that line, attributing matches to the enclosing
   object as the edge's "from".
4. DBMS_/UTL_ references and @dblink references create/reuse EXTERNAL
   nodes on first sight (ensure_external_node) rather than duplicating
   them.
5. TRIGGERS_ON and INDEX-on-TABLE edges are derived once from metadata
   already captured during file-catalog boundary marking, not by a second
   line-by-line scan.
6. Sort nodes by id and edges by (type, from, to, source_line_hint) before
   writing the artifact.
```

---

## Output specification

This skill produces the following sections of `inventory-artifact.json`
(the file-catalog skill produces `file_registry` and `object_registry`):

```json
{
  "meta": {
    "generated_at": "2026-07-20T18:09:30+00:00",
    "source_dir": "/absolute/path/to/repo",
    "agent_version": "1_inventory@1.0",
    "tool": "00_inventory.py",
    "total_files_scanned": 7
  },
  "stats": {
    "by_type": { "PACKAGE_BODY": 2, "TABLE": 1, "...": "..." },
    "total_objects": 15,
    "total_files": 7,
    "total_nodes": 17,
    "total_edges": 17,
    "edges_by_type": { "CALLS": 2, "READS": 3, "...": "..." },
    "issues_by_severity": { "error": 1, "warning": 4, "info": 1 },
    "incremental": { "enabled": true, "new": 0, "changed": 0, "unchanged": 7, "deleted": 0 }
  },
  "file_registry": [ ],
  "object_registry": [ ],
  "dependency_graph": {
    "nodes": [
      { "id": "TBL-APP.ACCOUNTS", "type": "TABLE", "origin": "REPO", "path": "01_schema.sql" },
      { "id": "EXTERNAL-DBMS_OUTPUT", "type": "EXTERNAL_PACKAGE", "origin": "EXTERNAL" },
      { "id": "DBLINK-FINANCE_LINK", "type": "DBLINK", "origin": "EXTERNAL" }
    ],
    "edges": [
      {
        "from": "PKGB-APP.ACCOUNT_MGMT",
        "to": "EXTERNAL-DBMS_OUTPUT",
        "type": "CALLS",
        "resolved": true,
        "confirmed": true,
        "source_line_hint": 14
      },
      {
        "from": "PKGB-APP.ACCOUNT_MGMT",
        "to": null,
        "type": "DYNAMIC_REF",
        "resolved": false,
        "confirmed": false,
        "source_line_hint": 28
      }
    ]
  },
  "issues": [
    {
      "severity": "warning",
      "type": "unresolved_reference",
      "file": "02_account_mgmt.sql",
      "line": 15,
      "message": "CALL target 'AUDIT_LOG_PKG.RECORD_TXN' not found among scanned packages."
    }
  ]
}
```

---

## Error handling

| Condition | Severity | Action |
|---|---|---|
| Qualified CALLS target not `DBMS_*`/`UTL_*` and not a known local package | `warning` | Edge with `resolved: false`, log `unresolved_reference` |
| `PACKAGE_BODY`/`TYPE_BODY` has no matching spec in this repo | `warning` | Log `unresolved_reference`, no edge created |
| `TRIGGERS_ON` / `INCLUDES` / `%TYPE`/`%ROWTYPE` target not found | `warning` | Edge with `resolved: false` (or omitted for INCLUDES), log `unresolved_reference` |
| `READS`/`WRITES` target not found | — | Edge with `resolved: false`, **no issue** (too common/noisy to be high-signal) |
| `EXECUTE IMMEDIATE` detected | `info` | Edge `DYNAMIC_REF`, `confirmed: false`, log `dynamic_ref` |
| Bare/unqualified CALLS candidate not in registry | — | No edge, no issue (would otherwise match every function call in every expression) |
