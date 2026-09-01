---
type: Index
title: Programs Overview
description: The five present PL/SQL programs - complexity tiers, common patterns, error codes, and the tables each reads or writes. Notes the absent programs 06-10 the schema references.
tags: [programs, plsql, index, procedures, functions]
---

# Programs Overview

The suite contains **five present PL/SQL programs**, graded by complexity through their filename prefix (`NN_tier_name.sql`). The DDL and DML reference **ten** programs; programs **06-10 are absent** from this checkout and are catalogued in [coverage-and-gaps](../coverage-and-gaps.md).

| # | File | Object | Kind | Tier | Tables read/written | Error codes / result mechanism |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | `01_simple_calculate_simple_interest.sql` | [`fn_calculate_simple_interest`](01-simple-interest.md) | Function | SIMPLE | none (pure) | raises `-20001`/`-20002`/`-20003`; re-raises on `OTHERS` |
| 02 | `02_simple_update_dormant_account_status.sql` | [`sp_update_dormant_account_status`](02-dormant-account-status.md) | Procedure | SIMPLE | read/write [`accounts`](../data-model/tables/accounts.md) | `OUT p_result` strings; `NO_DATA_FOUND` handled; re-raises on `OTHERS` |
| 03 | `03_simple_check_minimum_balance.sql` | [`sp_check_minimum_balance`](03-minimum-balance.md) | Procedure | SIMPLE | read [`accounts`](../data-model/tables/accounts.md) | `OUT p_message` strings; `NO_DATA_FOUND` handled; re-raises on `OTHERS` |
| 04 | `04_medium_process_monthly_interest_credit.sql` | [`sp_process_monthly_interest_credit`](04-monthly-interest-credit.md) | Procedure | MEDIUM | read/write [`accounts`](../data-model/tables/accounts.md), insert [`transaction_ledger`](../data-model/tables/transaction-ledger.md), insert [`batch_error_log`](../data-model/tables/batch-error-log.md) | `OUT` counters; raises `-20010` on fatal error |
| 05 | `05_medium_fund_transfer_with_validation.sql` | [`sp_transfer_funds`](05-fund-transfer.md) | Procedure | MEDIUM | read/write [`accounts`](../data-model/tables/accounts.md), read/insert [`transaction_ledger`](../data-model/tables/transaction-ledger.md) | `OUT p_status`/`p_message`; 5 custom exceptions |

## Common patterns

- **Result via `OUT` parameters.** Procedures signal *expected* outcomes through `OUT` status/message strings (e.g. `ACCOUNT_MARKED_DORMANT`, `BELOW_MINIMUM_BALANCE`, `SUCCESS`) rather than raising. Callers branch on these strings.
- **`RAISE_APPLICATION_ERROR` for invalid input / fatal errors.** Codes are unique per condition: `-20001`/`-20002`/`-20003` in [01](01-simple-interest.md) for principal/rate/tenure validation, `-20010` in [04](04-monthly-interest-credit.md) for a fatal batch failure.
- **Exception-handling styles differ by tier.**
  - Simple programs ([01](01-simple-interest.md)-[03](03-minimum-balance.md)) catch `NO_DATA_FOUND` for the "not found" case and re-raise (or set an error message) on `WHEN OTHERS`.
  - [04](04-monthly-interest-credit.md) uses a **nested block inside the loop** so a single-row failure is logged to [`batch_error_log`](../data-model/tables/batch-error-log.md) and the batch continues; only an outer failure rolls back and raises.
  - [05](05-fund-transfer.md) declares **named custom exceptions** and pairs each with a `ROLLBACK TO SAVEPOINT` handler.
- **Transaction discipline.** [02](02-dormant-account-status.md), [04](04-monthly-interest-credit.md), and [05](05-fund-transfer.md) `COMMIT` on success and `ROLLBACK` (or `ROLLBACK TO SAVEPOINT`) on failure. [01](01-simple-interest.md) and [03](03-minimum-balance.md) perform no DML and never commit. [05](05-fund-transfer.md) is the only program using `SAVEPOINT` and `SELECT ... FOR UPDATE`.
- **`DBMS_OUTPUT`** is used only by [01](01-simple-interest.md) to echo the error text before re-raising.

## Traceability

Every gating condition in these programs is enumerated as a `BR-NN` rule on the [business-rules index](../business-rules.md), each linking back to the program that enforces it and the tables it touches.
