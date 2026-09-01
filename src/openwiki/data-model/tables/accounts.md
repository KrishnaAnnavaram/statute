---
type: Table
title: "Table: accounts"
description: One row per deposit/overdraft account - balance, type, status, and daily transfer limit. The central table read or written by four of the five present programs.
resource: 00_ddl_create_schema.sql
tags: [table, accounts, core-banking]
---

# Table: `accounts`

One row per banking account (savings, current, term deposit, or overdraft). Defined at `00_ddl_create_schema.sql` lines 53-70. This is the most heavily used table in the present programs: it is read or written by [02](../../programs/02-dormant-account-status.md), [03](../../programs/03-minimum-balance.md), [04](../../programs/04-monthly-interest-credit.md), and [05](../../programs/05-fund-transfer.md).

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `account_number` | `VARCHAR2(20)` | NOT NULL | Primary key. Account identifier (sample form `AC1000234567`). |
| `customer_id` | `VARCHAR2(20)` | NOT NULL | Owning customer; foreign key to [`customers`](customers.md). |
| `account_type` | `VARCHAR2(20)` | NOT NULL | Product code. See enumerated values below. |
| `balance` | `NUMBER(18,2)` | NOT NULL, default `0` | Current ledger balance. May be negative for `OVERDRAFT` accounts. |
| `account_status` | `VARCHAR2(20)` | NOT NULL, default `'ACTIVE'` | Lifecycle status; constrained to `ACTIVE`, `DORMANT`, `CLOSED`. |
| `daily_transfer_limit` | `NUMBER(18,2)` | default `500000` | Maximum cumulative outward transfer per day, enforced in code by [05](../../programs/05-fund-transfer.md). |
| `last_transaction_date` | `DATE` | nullable | Date of the last activity; drives dormancy in [02](../../programs/02-dormant-account-status.md) and is updated by [04](../../programs/04-monthly-interest-credit.md) and [05](../../programs/05-fund-transfer.md). |
| `status_change_date` | `DATE` | nullable | When `account_status` last changed (set by [02](../../programs/02-dormant-account-status.md)). |
| `last_modified_by` | `VARCHAR2(50)` | nullable | Actor of the last modification; [02](../../programs/02-dormant-account-status.md) writes `'SYSTEM_BATCH'`. |
| `account_open_date` | `DATE` | default `SYSDATE` | Date the account was opened. |

## Enumerated domains (from source)

- `account_type` (comment at DDL lines 56-58): `SAVINGS_REGULAR`, `SAVINGS_PREMIUM`, `SAVINGS_ZERO_BAL`, `CURRENT_REGULAR`, `CURRENT_PREMIUM`, `TERM_DEPOSIT`, `OVERDRAFT`. This is a documented convention, **not** a CHECK constraint — the database does not enforce it.
- `account_status`: `ACTIVE`, `DORMANT`, `CLOSED`, enforced by CHECK `ck_accounts_status`.

## Constraints

- `pk_accounts` PRIMARY KEY (`account_number`) — ENABLED, VALIDATED.
- `fk_accounts_customer` FOREIGN KEY (`customer_id`) → [`customers`](customers.md) — ENABLED, VALIDATED.
- `ck_accounts_status` CHECK (`account_status IN ('ACTIVE','DORMANT','CLOSED')`) — ENABLED, VALIDATED. This is a DATABASE-enforced business rule; see [BR-01](../../business-rules.md).

## Programs that read or write it

- [02 `sp_update_dormant_account_status`](../../programs/02-dormant-account-status.md): reads `last_transaction_date`/`account_status`; updates `account_status`, `status_change_date`, `last_modified_by`.
- [03 `sp_check_minimum_balance`](../../programs/03-minimum-balance.md): reads `balance`, `account_type` (read-only).
- [04 `sp_process_monthly_interest_credit`](../../programs/04-monthly-interest-credit.md): reads active `SAVINGS%` rows; updates `balance`, `last_transaction_date`.
- [05 `sp_transfer_funds`](../../programs/05-fund-transfer.md): `SELECT ... FOR UPDATE` on both accounts; updates `balance`, `last_transaction_date`.

## Child tables

- [`transaction_ledger`](transaction-ledger.md) via `fk_txn_account` (declared).
- [`interest_accrual_ledger`](interest-accrual-ledger.md) via `fk_accrual_account` (declared; written only by the absent EOD program #8).

## Sample data

Twelve accounts are seeded (`00_dml_load_sample_schema.sql` lines 41-64), deliberately spanning dormancy, below-minimum-balance, tiered-interest slabs, and transfer-validation scenarios. See [sample data](../dml-sample-data.md).
