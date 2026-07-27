---
name: file-catalog
description: >
  Recursively traverses a PL/SQL repository directory tree. Classifies every
  top-level object in every .sql file against a fixed type taxonomy,
  assigns owner-qualified path-independent ids, and marks coarse line
  boundaries for each object. Produces the raw file_registry and
  object_registry that the Inventory Agent assembles into the final
  artifact. Implemented deterministically by 00_inventory.py; used
  exclusively by the Inventory Agent (1_inventory_plsql).
---

## Purpose

Walk the repository filesystem. For every `.sql` file found, record its
path, hash its content, and detect every top-level `CREATE` (plus `GRANT`,
DML seed statements, and anonymous PL/SQL blocks). Classify each into a
type, assign it an owner-qualified id, and mark its coarse start/terminator
line. Produce structured registry lists.

Do NOT descend into nested `BEGIN`/`END` blocks, parse statement bodies, or
resolve cross-references — that is the reference-graph skill's job.

---

## Type taxonomy

| Type | Prefix | Detected from |
|---|---|---|
| `PACKAGE_SPEC` | `PKGS` | `CREATE [OR REPLACE] PACKAGE owner.name` (not followed by `BODY`) |
| `PACKAGE_BODY` | `PKGB` | `CREATE [OR REPLACE] PACKAGE BODY owner.name` |
| `PROCEDURE` | `PROC` | `CREATE [OR REPLACE] PROCEDURE owner.name` |
| `FUNCTION` | `FUNC` | `CREATE [OR REPLACE] FUNCTION owner.name` |
| `TRIGGER` | `TRG` | `CREATE [OR REPLACE] TRIGGER owner.name` |
| `TYPE_SPEC` | `TYPS` | `CREATE [OR REPLACE] TYPE owner.name` (not followed by `BODY`) |
| `TYPE_BODY` | `TYPB` | `CREATE [OR REPLACE] TYPE BODY owner.name` |
| `VIEW` | `VIEW` | `CREATE [OR REPLACE] [FORCE] VIEW owner.name` |
| `MVIEW` | `MVW` | `CREATE [OR REPLACE] MATERIALIZED VIEW owner.name` |
| `TABLE` | `TBL` | `CREATE [GLOBAL TEMPORARY] TABLE owner.name` |
| `INDEX` | `IDX` | `CREATE [UNIQUE\|BITMAP] INDEX owner.name ON ...` |
| `SEQUENCE` | `SEQ` | `CREATE SEQUENCE owner.name` |
| `SYNONYM` | `SYN` | `CREATE [OR REPLACE] [PUBLIC] SYNONYM name FOR target` |
| `DML_SEED` | `SEED` | Top-level `INSERT` / `UPDATE` / `DELETE` / `MERGE` |
| `SQLPLUS_SCRIPT` | `SPS` | File contains only SQL*Plus scaffolding / `@include` lines and no CREATE/GRANT/DML |
| `MIGRATION` | `MIG` | Filename matches Flyway (`V\d+__...`) or contains `changelog`, AND no top-level object detected |
| `GRANT` | `GRT` | Top-level `GRANT ...` |
| `ANONYMOUS_BLOCK` | `ANON` | Top-level `DECLARE`/`BEGIN` not part of a `CREATE` |
| `UNKNOWN` | `UNK` | None of the above matched anywhere in the file |

**Critical:** `PACKAGE` vs `PACKAGE BODY` and `TYPE` vs `TYPE BODY` are
distinct types — the `BODY` alternative is always tried first in the
matching regex so it takes priority over the bare spec keyword.

---

## Object and file ids

```
object_id = "{TYPE_PREFIX}-{OWNER}.{OBJECT_NAME}"     e.g. PKGB-APP.ACCOUNT_MGMT
```

- `OWNER` and `OBJECT_NAME` are upper-cased unless the source used a
  double-quoted identifier, in which case the exact case inside the quotes
  is preserved.
- If no owner is present in the source (e.g. a bare `CREATE TABLE ACCOUNTS`),
  the owner slot is left as an empty string but still occupies its place in
  the id: `TBL-.ACCOUNTS`.
- `file_id` = the `object_id` of the file's **dominant** object, defined as
  the object with the lowest `start_line` in that file (the first top-level
  construct encountered).
- **Collision rule:** ids are assigned from a single global namespace shared
  across every file. On a repeat of an already-assigned id, the new
  occurrence gets a numeric suffix (`_2`, `_3`, ...) and a `duplicate_id`
  error is logged. Never silently deduplicate — both entries are kept.
- Types with no declared object name in the source (`GRANT`,
  `ANONYMOUS_BLOCK`, `SQLPLUS_SCRIPT`, `MIGRATION`, `UNKNOWN`, or a
  `DML_SEED`/`GRANT` whose target table couldn't be extracted) fall back to
  `{FILENAME}_L{line}` as the name and log an `unassigned_id` warning.

---

## Boundary marking

- **Per file:** `line_span: [1, N]` and `byte_span: [0, size_bytes]`.
- **Per object:** a coarse `start_line` (the line the `CREATE`/`GRANT`/DML
  keyword appears on) and `terminator_line`:
  - `PACKAGE_SPEC`, `PACKAGE_BODY`, `PROCEDURE`, `FUNCTION`, `TRIGGER`,
    `TYPE_SPEC`, `TYPE_BODY`, `ANONYMOUS_BLOCK` (types that can contain
    nested `BEGIN`/`END` blocks with their own semicolons) terminate at the
    next line that is a **lone `/`** (SQL*Plus run marker). Never terminate
    these on an internal `;` — that would cut the object off mid-body.
  - All other types (`VIEW`, `MVIEW`, `TABLE`, `INDEX`, `SEQUENCE`,
    `SYNONYM`, `GRANT`, `DML_SEED`) terminate at the first top-level `;`,
    found by scanning content with string literals and comments already
    masked out (so a `;` inside a string or comment can never be mistaken
    for a terminator).
  - If no lone `/` is found before EOF for a compiled type, the terminator
    is assumed to be EOF and a `missing_terminator` warning is logged.
- This is coarse boundary marking only — never descend into the object body
  to look for nested structure. That is the Parser Agent's job.

---

## Noise handling

- **SQL\*Plus scaffolding** (`SET`, `PROMPT`, `SPOOL`, `DEFINE`, `UNDEFINE`,
  `WHENEVER`, `ACCEPT`, `COLUMN`, `TTITLE`, `BTITLE`, `CLEAR`, `PAUSE`,
  `REM`) is blanked out of the working copy used for object detection
  before boundary marking runs, so it never mis-fires a `CREATE`/`GRANT`/DML
  match. The original file content is never modified on disk.
- Inline `&substitution` and `&&substitution` tokens are blanked the same
  way.
- A file whose only non-blank content is scaffolding lines and/or
  `@`/`@@include` lines, with zero detected objects, is classified as a
  single `SQLPLUS_SCRIPT` object spanning the whole file.
- **Wrapped objects:** if the word `WRAPPED` appears on the object's own
  `CREATE` line, the object is tagged `"wrapped": true`. Its garbled body is
  never parsed further — only its declared header (owner, name, type) and
  terminator are recorded.

---

## Execution steps

```
1. Recursively find all *.sql files under REPO_ROOT (sorted by relative path).
   Apply EXCLUDE_DIRS / default exclusion globs.
2. For each included file:
   a. Compute sha256, size, last_modified, encoding (utf-8 with latin-1
      fallback), and line/code/comment/blank line counts.
   b. If empty or unreadable, record status accordingly and skip object
      scanning for that file.
   c. Otherwise, mask string literals and comments, strip SQL*Plus
      scaffolding, then sequentially scan for top-level CREATE / GRANT /
      DML / anonymous-block constructs (see "Boundary marking" above).
      Each detected construct becomes one raw object; scanning resumes
      immediately after its terminator so nested content is never
      re-scanned.
   d. Assign each raw object its id (with collision handling), producing
      the final object_registry entries for that file.
   e. Assign the file's file_id from its dominant object.
3. Build:
   - file_registry      (one entry per physical file)
   - object_registry     (one entry per top-level object, referencing its
                          parent file via file_id)
4. Return both lists to the Inventory Agent for merging with the
   reference-graph skill's output.
```

---

## Output structures

### file_registry entry

```json
{
  "path": "app/plsql/account_mgmt.sql",
  "abs_path": "/repo/app/plsql/account_mgmt.sql",
  "size_bytes": 1205,
  "sha256": "c140e9b9...",
  "last_modified": "2026-07-20T18:05:51+00:00",
  "byte_span": [0, 1205],
  "status": "ok",
  "line_span": [1, 42],
  "encoding_used": "utf-8",
  "warnings": [],
  "file_id": "PKGS-APP.ACCOUNT_MGMT",
  "object_ids": ["PKGB-APP.ACCOUNT_MGMT", "PKGS-APP.ACCOUNT_MGMT", "TRG-APP.ACCOUNTS_BIU"],
  "incremental_status": "unchanged"
}
```

### object_registry entry

```json
{
  "object_id": "PKGB-APP.ACCOUNT_MGMT",
  "type": "PACKAGE_BODY",
  "owner": "APP",
  "name": "ACCOUNT_MGMT",
  "start_line": 8,
  "terminator_line": 33,
  "wrapped": false,
  "nameless": false
}
```

`SYNONYM` objects additionally carry `"synonym_for": "OWNER.TARGET"`
(recorded only — never resolved through). `TRIGGER` objects carry
`"triggers_on": {"owner": ..., "name": ...}`. `INDEX` objects carry
`"indexes_table": {"owner": ..., "name": ...}`.

---

## Error handling

| Condition | Severity | Action |
|---|---|---|
| File cannot be read | — | Record `status: "unreadable"`, skip object scanning, continue |
| File is 0 bytes | — | Record `status: "empty"`, skip object scanning, continue |
| Object has no declared name | `warning` | Fall back to `{FILENAME}_L{line}`, log `unassigned_id` |
| Object id already assigned elsewhere | `error` | Suffix the new occurrence (`_2`, `_3`, ...), log `duplicate_id`, keep both |
| No lone `/` terminator found for a compiled type | `warning` | Assume EOF, log `missing_terminator` |
| `files_found != excluded + cataloged + skipped` | fatal | Tool exits non-zero — this is a logic bug, not a data issue |
