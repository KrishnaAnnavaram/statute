---
type: Table
title: "Table: loan_rate_reset_history"
description: Floating-rate reset events for a loan - the installment number a revised annual rate takes effect from. Populated as sample data; no present program reads or writes it.
resource: 00_ddl_create_schema.sql
tags: [table, loan-rate-reset-history, loans]
---

# Table: `loan_rate_reset_history`

Records floating-rate reset events for a loan. Defined at `00_ddl_create_schema.sql` lines 148-156. Each row states the installment number from which a revised annual rate applies.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `loan_account_number` | `VARCHAR2(20)` | NOT NULL | Loan whose rate is being reset; foreign key to [`loan_master`](loan-master.md). Part of PK. |
| `effective_installment_no` | `NUMBER` | NOT NULL | Installment number from which the revised rate takes effect. Part of PK. |
| `revised_annual_rate` | `NUMBER(6,3)` | NOT NULL | The new annual rate (percent). |
| `reset_date` | `DATE` | default `SYSDATE` | Date the reset was recorded. |

## Constraints

- `pk_loan_rate_reset` PRIMARY KEY (`loan_account_number`, `effective_installment_no`) — ENABLED, VALIDATED.
- `fk_rate_reset_loan` FOREIGN KEY (`loan_account_number`) → [`loan_master`](loan-master.md) — ENABLED, VALIDATED.

## Programs that read or write it

**None in this checkout.** It supplies rate history to the absent amortization program (#7), which recomputes the schedule when a floating-rate loan resets. See [coverage-and-gaps](../../coverage-and-gaps.md).

## Sample data

Two reset rows for the floating-rate auto loan `LN5000011235` (`00_dml_load_sample_schema.sql` lines 144-147). See [sample data](../dml-sample-data.md).
