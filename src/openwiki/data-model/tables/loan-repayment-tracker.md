---
type: Table
title: "Table: loan_repayment_tracker"
description: Days-past-due snapshot per loan and as-of-date - the input to the absent NPA-classification program #10. Seeded with sample DPD spanning every NPA bucket.
resource: 00_ddl_create_schema.sql
tags: [table, loan-repayment-tracker, loans]
---

# Table: `loan_repayment_tracker`

Days-past-due (DPD) snapshot per loan as of a given date. Defined at `00_ddl_create_schema.sql` lines 229-238. The DDL header comment describes it as the **"days-past-due snapshot feeding NPA classification, #10"** — the absent NPA program.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `loan_account_number` | `VARCHAR2(20)` | NOT NULL | Loan the snapshot is for; foreign key to [`loan_master`](loan-master.md). Part of PK. |
| `as_of_date` | `DATE` | NOT NULL | Snapshot date. Part of PK. |
| `days_past_due` | `NUMBER` | default `0` | Days the loan is overdue; drives the NPA bucket. |
| `last_payment_date` | `DATE` | nullable | Date of the most recent repayment. |
| `last_payment_amount` | `NUMBER(18,2)` | nullable | Amount of the most recent repayment. |

## Constraints

- `pk_loan_repayment_tracker` PRIMARY KEY (`loan_account_number`, `as_of_date`) — ENABLED, VALIDATED.
- `fk_repay_tracker_loan` FOREIGN KEY (`loan_account_number`) → [`loan_master`](loan-master.md) — ENABLED, VALIDATED.

## Programs that read or write it

**None in this checkout.** It is the input to the absent NPA-classification program (#10), which would map DPD to `STANDARD`/`SPECIAL_MENTION`/`SUBSTANDARD`/`DOUBTFUL`/`LOSS`. See [coverage-and-gaps](../../coverage-and-gaps.md).

## Sample data

Five DPD snapshots as of quarter-end `2026-06-30`, deliberately spanning every NPA bucket boundary: `0` (STANDARD), `45` (SPECIAL_MENTION), `20` (STANDARD by DPD but restructured → override), `400` (DOUBTFUL), `650` (LOSS) — `00_dml_load_sample_schema.sql` lines 194-203. See [sample data](../dml-sample-data.md).
