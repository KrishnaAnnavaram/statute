---
type: Overview
title: Quickstart
description: Entry point to the plsql_to_brd wiki - what the repository is, how the SQL scripts install and run, and a task-routing table from change intent to the owning page, source, rules, and validation.
tags: [quickstart, navigation, plsql, oracle, retail-banking]
---

# Quickstart

This repository is **production Oracle PL/SQL for a retail banking system**: a physical data model plus five banking-operation programs. There is no application layer in the checkout — the SQL scripts are the deliverable. Start with the [System Overview](overview.md) for the full picture; this page is the map and the task router.

## What is here

| Layer | Files | Wiki |
| --- | --- | --- |
| Schema | `00_ddl_create_schema.sql` (3 sequences, 15 tables) | [Data model & ERD](data-model/ddl-schema.md), [per-table pages](data-model/tables/customers.md) |
| Seed data | `00_dml_load_sample_schema.sql` | [Sample data](data-model/dml-sample-data.md) |
| Programs | `01`-`05` (functions/procedures) | [Programs overview](programs/overview.md) |

## Install and run order

1. Run `00_ddl_create_schema.sql` — creates sequences and tables. Target: Oracle 12c+.
2. Compile the five programs (`01`-`05`).
3. Run `00_dml_load_sample_schema.sql` — seeds a dataset keyed to the reference date `30-JUN-2026`, shaped to exercise every program's branches.

The DDL/DML also reference programs `06`-`10` that are **not in this checkout**; see [coverage and gaps](coverage-and-gaps.md).

## Major concepts

- **Data model** — 15 tables across Core banking, Loans, Interest, Batch audit, Operational, and Program outputs domains, with declared and INFERRED relationships. See the [ERD](data-model/ddl-schema.md).
- **Programs** — [01 simple interest](programs/01-simple-interest.md) (pure function), [02 dormancy](programs/02-dormant-account-status.md), [03 minimum balance](programs/03-minimum-balance.md), [04 monthly interest batch](programs/04-monthly-interest-credit.md), [05 validated fund transfer](programs/05-fund-transfer.md).
- **Business rules** — every gating condition as a traceable [`BR-NN` rule](business-rules.md) with file:line, enforcing object, and DATABASE-vs-CODE type.
- **Coverage & gaps** — orphan tables, hard-coded constants vs reference tables, code-only validations, and the absent programs 06-10. See [coverage and gaps](coverage-and-gaps.md).

## Task-routing table

| I want to change / understand… | Go to | Source entrypoint / symbol | Rules | Minimal validation |
| --- | --- | --- | --- | --- |
| A table's columns, constraints, or ownership | the table's [page](data-model/tables/accounts.md) | `00_ddl_create_schema.sql` | [BR-01](business-rules.md) (status CHECK) | Recreate DDL; inspect `USER_CONSTRAINTS` |
| The schema or a relationship (ERD) | [Data model & ERD](data-model/ddl-schema.md) | `00_ddl_create_schema.sql` | structural PK/FK | Run the DDL against an empty schema |
| Simple-interest formula / input validation | [01](programs/01-simple-interest.md) | `fn_calculate_simple_interest` | [BR-02](business-rules.md)-[BR-06](business-rules.md) | `SELECT fn_calculate_simple_interest(100000,7.5,180,'365') FROM dual` |
| Dormancy / reactivation threshold | [02](programs/02-dormant-account-status.md) | `sp_update_dormant_account_status` | [BR-07](business-rules.md)-[BR-09](business-rules.md) | Call with a DORMANT sample account and check `p_result` |
| Minimum-balance rules / penalty | [03](programs/03-minimum-balance.md) | `sp_check_minimum_balance` | [BR-10](business-rules.md) | Call with `AC1000234570` (below `5000`) |
| Monthly interest crediting / tiered rates / batch error handling | [04](programs/04-monthly-interest-credit.md) | `sp_process_monthly_interest_credit` | [BR-11](business-rules.md)-[BR-15](business-rules.md) | Call and inspect `transaction_ledger` INT_CREDIT rows + `batch_error_log` |
| Fund transfer / locking / daily limit / atomicity | [05](programs/05-fund-transfer.md) | `sp_transfer_funds` | [BR-16](business-rules.md)-[BR-20](business-rules.md) | Call a valid + an over-limit transfer; check `p_status` and ledger rows |
| Why a table is unused / a rate is hard-coded | [Coverage & gaps](coverage-and-gaps.md) | DDL/DML comments | — | Cross-check `interest_rate_master` vs [04](programs/04-monthly-interest-credit.md) |
| What the sample data triggers | [Sample data](data-model/dml-sample-data.md) | `00_dml_load_sample_schema.sql` | — | Run the DML sanity `SELECT`s at file end |
| A new business rule's traceability | [Business rules](business-rules.md) | the program that enforces it | new `BR-NN` | Cite file:line; classify DATABASE/CODE |

## Validation notes

- The programs require an Oracle database; there is no automated test suite in the checkout. The narrowest checks are the per-program sample calls above and the sanity `SELECT`s at the end of `00_dml_load_sample_schema.sql`.
- Enable `SET SERVEROUTPUT ON` to see `DBMS_OUTPUT` from [01](programs/01-simple-interest.md)'s error path.

## Backlog (deferred, evidence-blocked)

The suite's schema and sample data anticipate five programs that are **absent from this checkout**; they cannot be documented from source and are deferred until their code is restored. Each is catalogued with its inferred responsibility, owned tables, and source anchor in [coverage and gaps](coverage-and-gaps.md):

- **#6** account statements — `00_dml_load_sample_schema.sql:39`.
- **#7** loan amortization schedule — `00_ddl_create_schema.sql:159`.
- **#8** end-of-day interest accrual — `00_ddl_create_schema.sql:176,188,204`.
- **#9** transaction fraud scoring — `00_ddl_create_schema.sql:213`, `00_dml_load_sample_schema.sql:66-120`.
- **#10** NPA classification & provisioning — `00_ddl_create_schema.sql:226-266`.
