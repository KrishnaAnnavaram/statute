---
type: Table
title: "Table: transaction_ledger"
description: Append-only ledger of every account transaction - type, amount, running balance, and fraud-relevant fields. Written by the interest-credit and fund-transfer programs.
resource: 00_ddl_create_schema.sql
tags: [table, transaction-ledger, core-banking]
---

# Table: `transaction_ledger`

Append-only ledger of every account movement. Defined at `00_ddl_create_schema.sql` lines 75-94. It records interest credits, transfers, deposits, withdrawals, fees, EMI debits, and salary credits, and carries the fields the absent fraud program (#9) scores on.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `txn_id` | `NUMBER` | NOT NULL | Primary key. Populated from sequence `seq_txn_id`. |
| `account_number` | `VARCHAR2(20)` | NOT NULL | Owning account; foreign key to [`accounts`](accounts.md). |
| `txn_date` | `DATE` | NOT NULL, default `SYSDATE` | Timestamp of the transaction (sample data stores intraday `TIMESTAMP` values here). |
| `txn_type` | `VARCHAR2(20)` | NOT NULL | Transaction category; see enumerated values below. |
| `txn_amount` | `NUMBER(18,2)` | NOT NULL | Amount of the transaction. |
| `running_balance` | `NUMBER(18,2)` | nullable | Account balance immediately after the transaction. |
| `reference_number` | `VARCHAR2(50)` | nullable | External reference; set by [05](../../programs/05-fund-transfer.md) from `p_txn_ref`. |
| `narration` | `VARCHAR2(200)` | nullable | Free-text description. |
| `origin_country` | `VARCHAR2(3)` | nullable | ISO country the transaction originated from; used by the absent fraud program (#9) for geo-mismatch and impossible-travel checks. |
| `beneficiary_id` | `VARCHAR2(20)` | nullable | Destination beneficiary; used by the fraud program for first-time-beneficiary detection. |
| `hold_flag` | `VARCHAR2(1)` | default `'N'` | Whether the transaction is held. |

## Enumerated domain (from source)

`txn_type` (comment at DDL lines 79-81): `TRANSFER_IN`, `TRANSFER_OUT`, `INT_CREDIT`, `DEPOSIT`, `WITHDRAWAL`, `FEE`, `CHARGE`, `EMI_DEBIT`, `SALARY_CREDIT`. Documented convention only — **not** a CHECK constraint.

## Constraints and index

- `pk_transaction_ledger` PRIMARY KEY (`txn_id`) — ENABLED, VALIDATED.
- `fk_txn_account` FOREIGN KEY (`account_number`) → [`accounts`](accounts.md) — ENABLED, VALIDATED.
- Index `idx_txn_ledger_acct_date (account_number, txn_date)` (line 94) — supports the daily-limit aggregate in [05](../../programs/05-fund-transfer.md) and the account/date scans the absent programs would run.

## Programs that read or write it

- [04 `sp_process_monthly_interest_credit`](../../programs/04-monthly-interest-credit.md): `INSERT` of an `INT_CREDIT` row per credited account.
- [05 `sp_transfer_funds`](../../programs/05-fund-transfer.md): reads today's `TRANSFER_OUT` sum for the daily-limit check ([BR-20](../../business-rules.md)); inserts a `TRANSFER_OUT` and a `TRANSFER_IN` row for each transfer.

## Sample data

The DML seeds normal history plus deliberately engineered fraud triggers — a velocity burst, a geo-mismatch/impossible-travel pair, an amount anomaly, a first-time large-beneficiary transfer, and an odd-hour high-value transaction (`00_dml_load_sample_schema.sql` lines 66-120) — all targeting the absent fraud program. See [sample data](../dml-sample-data.md).
