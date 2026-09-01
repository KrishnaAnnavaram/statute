---
type: Table
title: "Table: interest_rate_master"
description: Reference table of annual rates by product code and balance slab. Intended for the absent EOD accrual program #8; the present monthly-interest program hard-codes rates instead of reading it.
resource: 00_ddl_create_schema.sql
tags: [table, interest-rate-master, interest, reference-data]
---

# Table: `interest_rate_master`

Reference lookup of annual interest rates by product and balance slab. Defined at `00_ddl_create_schema.sql` lines 178-186. The DDL header comment states it is **"used by #8"** — the absent end-of-day accrual program.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `product_code` | `VARCHAR2(20)` | NOT NULL | Product this rate applies to (matches `accounts.account_type` values, INFERRED — no FK). Part of PK. |
| `min_balance` | `NUMBER(18,2)` | NOT NULL, default `0` | Lower bound of the balance slab (inclusive). Part of PK. |
| `max_balance` | `NUMBER(18,2)` | nullable | Upper bound of the slab; `NULL` means no upper bound. |
| `annual_rate` | `NUMBER(6,3)` | NOT NULL | Annual rate (percent) for the slab. |
| `effective_date` | `DATE` | NOT NULL | Date the rate becomes effective. Part of PK. |

## Constraints

- `pk_interest_rate_master` PRIMARY KEY (`product_code`, `min_balance`, `effective_date`) — ENABLED, VALIDATED.

## Programs that read or write it

**None in this checkout.** This is the intended rate source for the absent accrual program (#8).

### Coverage note: divergence from program 04

The present [monthly interest program (04)](../../programs/04-monthly-interest-credit.md) does **not** read this table. It hard-codes its own tiered rates (`3.0`/`3.5`/`4.0`/`4.5`) directly in procedural logic (`04_medium_process_monthly_interest_credit.sql` lines 38-46), using different slab boundaries than the rows here. This is a documented divergence between hard-coded constants and an available reference table; see [coverage-and-gaps](../../coverage-and-gaps.md).

## Sample data

Rate rows for `SAVINGS_REGULAR`, `SAVINGS_PREMIUM`, `SAVINGS_ZERO_BAL`, `TERM_DEPOSIT`, and `OVERDRAFT`, all effective `2026-01-01` (`00_dml_load_sample_schema.sql` lines 153-172). See [sample data](../dml-sample-data.md).
