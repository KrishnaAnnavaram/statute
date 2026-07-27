# Vendored: Oracle PL/SQL ANTLR4 Python parser

Generated code — do not hand-edit. Regenerate with the command below if the
grammar needs to change.

## Provenance

- Grammar source: https://github.com/antlr/grammars-v4/tree/master/sql/plsql
  (`PlSqlLexer.g4`, `PlSqlParser.g4`), commit as of 2026-07-27.
- Original grammar authors: Alexandre Porcelli, Ivan Kochurkin, Mark Adams.
- License: Apache License 2.0 (see header of the original `.g4` files).
- ANTLR tool version: 4.13.2 (`antlr4-4.13.2-complete.jar` from Maven Central).
- Python target runtime: `antlr4-python3-runtime==4.13.2` (must match the
  tool version exactly — this is the #1 source of cryptic runtime errors
  if it ever drifts).

## Regeneration command

```bash
java -jar antlr4-4.13.2-complete.jar -Dlanguage=Python3 -visitor -no-listener \
    PlSqlLexer.g4 PlSqlParser.g4
```

## Key entry rules used by 02_parser.py

- `sql_script` — top-level rule; parses an entire file as a sequence of
  `unit_statement`s separated by `;` and optional SQL*Plus `/`.
- `create_procedure_body`, `create_function_body`, `create_package`,
  `create_package_body`, `create_trigger` — the object types 02_parser.py
  extracts structure from.
- `body` → `BEGIN seq_of_statements (EXCEPTION exception_handler+)? END` —
  the core executable-block shape walked by the statement visitor.
