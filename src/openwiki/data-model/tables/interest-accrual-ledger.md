---
type: Table
title: "Table: interest_accrual_ledger"
description: Daily interest-accrual entries per account (accrued amount, applied rate, posted flag) - output of the absent EOD accrual program #8. Orphan in this checkout.
resource: 00_ddl_create_schema.sql
tags: [table, interest-accrual-ledger, interest, orphan]
---

# Table: `interest_accrual_ledger`

Daily interest-accrual entries per account. Defined at `00_ddl_create_schema.sql` lines 191-201. The DDL header comment states it is the **"output of program #8"** — the absent end-of-day accrual batch.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `account_number` | `VARCHAR2(20)` | NOT NULL | Account the accrual belongs to; foreign key to [`accounts`](accounts.md). Part of PK. |
| `accrual_date` | `DATE` | NOT NULL | Date the interest was accrued. Part of PK. |
| `accrued_amount` | `NUMBER(18,4)` | NOT NULL | Interest accrued for the day (four decimal places for daily precision). |
| `applied_rate` | `NUMBER(6,3)` | nullable | Annual rate used for the accrual. |
| `posted_flag` | `VARCHAR2(1)` | default `'N'` | Whether the accrual has been posted to the account. |
| `last_updated` | `TIMESTAMP` | default `SYSTIMESTAMP` | Last modification timestamp. |

## Constraints

- `pk_interest_accrual_ledger` PRIMARY KEY (`account_number`, `accrual_date`) — ENABLED, VALIDATED.
- `fk_accrual_account` FOREIGN KEY (`account_number`) → [`accounts`](accounts.md) — ENABLED, VALIDATED.

## Programs that read or write it

**None in this checkout.** It is the output table of the absent accrual program (#8), which would read [`interest_rate_master`](interest-rate-master.md) and skip holidays via [`holiday_calendar`](holiday-calendar.md). It is an **orphan** here and receives no sample data. See [coverage-and-gaps](../../coverage-and-gaps.md).
