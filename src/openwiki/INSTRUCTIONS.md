# Wiki brief

## What this codebase is
Production Oracle PL/SQL for a retail banking system. Two layers:

- DDL/DML files that define and seed the physical data model.
- PL/SQL programs (functions and procedures) implementing banking operations.

Treat every file as production code. This logic moves money and enforces
policy. Accuracy outranks coverage: a wrong statement is worse than an
absent one. When the source does not establish something, say so.

## Audience — write for both at once

1. HUMAN. A business analyst who cannot read PL/SQL, and an engineer who
   must reimplement this behaviour on a different platform. Neither should
   need to open the SQL to understand what the system decides and why.
2. MACHINE. Downstream tooling parses this wiki. Every page carries typed
   OKF front matter, and every business rule is additionally emitted as a
   parseable JSON record.

## Required wiki structure

- An overview page: what the system does, its major domains, and how the
  files relate to each other.
- One page per source file, describing what it contains and what depends
  on it.
- A data-model page holding the ERD, plus one page per table.
- One page per PL/SQL program.
- A business-rules index page.
- A coverage-and-gaps page (see below).

Cross-link heavily. Every rule links to the program that enforces it and
the tables it touches; every table links to the programs that read or
write it.

## Data model and ERD

Build a Mermaid `erDiagram` from the DDL only. Include every table,
column, datatype, nullability, primary key, foreign key, unique
constraint, CHECK constraint, and default value.

- Relationships must derive from declared FOREIGN KEY constraints.
- Where a relationship is implied by column naming or by procedural
  usage but has NO declared foreign key, include it and label it
  INFERRED explicitly. Never present an inferred link as declared.
- Record each constraint's enforcement state where the DDL declares one
  (ENABLED/DISABLED, VALIDATED/NOT VALIDATED). A disabled constraint
  documents an intention, not a guarantee — say which it is.
- For each column, state its business meaning, not just its type.

## Program documentation — statement level

For each function or procedure, cover:

- Purpose in one sentence, in business terms.
- Signature: every parameter, its mode (IN/OUT/IN OUT), type, and meaning.
- Preconditions the caller must satisfy.
- A walkthrough in source order. For every statement that reads, writes,
  branches, loops, raises, or handles an exception, state what it does
  and why it exists. Do not skip statements. Do not compress several
  statements into one vague sentence.
- Transaction behaviour: where COMMIT, ROLLBACK and SAVEPOINT occur, and
  what is left uncommitted on each failure path.
- Every exit path and what the caller observes on each.

## Business rules and traceability

Every condition that gates an outcome becomes a numbered rule.

Each rule MUST carry:

- A stable ID `BR-NN`, assigned once and never renumbered.
- The obligation in plain English — what MUST or MUST NOT happen — not a
  restatement of the IF condition.
- The source expression, quoted verbatim.
- A citation: source file and line number(s).
- The enforcing program or constraint, named exactly.
- Enforcement type: DATABASE (schema constraint) or CODE (procedural
  logic). These fail differently and that difference matters.
- A category: Validation, Calculation, Routing, Limit-check, or
  Error-handling.

Maintain an index table of all rules:

| ID | Rule | Source file:line | Enforced by | Type | Category |

TRACEABILITY IS MANDATORY. Never state a business rule without a
file:line citation. If you cannot cite it, do not publish it as a rule —
record it under "Unverified observations" and state what evidence is
missing.

## Machine-readable layer

- Every page carries OKF front matter with a precise `type`: Overview,
  DataModel, Table, Procedure, Function, BusinessRule, Index, Gaps.
- On the rules page, emit each rule as a fenced json block with keys:
  id, statement, source_file, source_lines, expression, enforced_by,
  enforcement_type, category.
- Keep identifiers, table names, column names and file paths byte-for-byte
  as they appear in the source. Never reformat, re-case, or pretty-print
  them.

## Coverage and gaps — required page

Report honestly on what the source does NOT contain:

- Tables defined in the DDL that no program reads or writes.
- Constants and thresholds hard-coded in procedural logic where a
  reference table exists for the same purpose.
- Validation performed in code that has no corresponding database
  constraint, and therefore can be bypassed by direct SQL.
- Gaps in the file numbering or naming that suggest missing programs.
- Anything a reimplementation team would need but cannot find here.

## Accuracy discipline

- Quote every threshold, limit and constant exactly as written.
- Never infer behaviour from banking convention. If the code does not
  do it, do not document it.
- Distinguish what the DATABASE enforces from what CODE enforces.
- Ground every diagram in inspected source. No invented entities,
  states or relationships.
- Where two parts of the source disagree, document the disagreement
  rather than picking a winner.
