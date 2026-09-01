---
type: Table
title: "Table: npa_classification_history"
description: Per-loan, per-date NPA classification with provisioning amount and movement type - output of the absent NPA program #10. Seeded with prior-quarter history for movement testing.
resource: 00_ddl_create_schema.sql
tags: [table, npa-classification-history, program-output, loans]
---

# Table: `npa_classification_history`

Per-loan, per-date Non-Performing-Asset classification record. Defined at `00_ddl_create_schema.sql` lines 243-255. The DDL header comment states it is the **"output of program #10"** — the absent NPA-classification batch.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `loan_account_number` | `VARCHAR2(20)` | NOT NULL | Loan classified (INFERRED link to [`loan_master`](loan-master.md); no FK). Part of PK. |
| `classification_date` | `DATE` | NOT NULL | Date of classification (quarter end). Part of PK. |
| `classification` | `VARCHAR2(20)` | NOT NULL | `STANDARD`, `SPECIAL_MENTION`, `SUBSTANDARD`, `DOUBTFUL`, or `LOSS`. |
| `days_past_due` | `NUMBER` | nullable | DPD driving the classification. |
| `outstanding_principal` | `NUMBER(18,2)` | nullable | Principal outstanding at classification time. |
| `collateral_cover_pct` | `NUMBER(6,2)` | nullable | Collateral value as a percentage of outstanding principal. |
| `provisioning_amount` | `NUMBER(18,2)` | nullable | Provision to be held against the loan. |
| `prior_classification` | `VARCHAR2(20)` | nullable | Classification in the previous period. |
| `movement_type` | `VARCHAR2(20)` | nullable | `NEW`, `UNCHANGED`, `UPGRADED`, or `DOWNGRADED`. |

## Constraints

- `pk_npa_class_hist` PRIMARY KEY (`loan_account_number`, `classification_date`) — ENABLED, VALIDATED. There is **no** foreign key to `loan_master`; that link is INFERRED.

## Programs that read or write it

**None in this checkout.** It is the output table of the absent NPA program (#10), which would read [`loan_repayment_tracker`](loan-repayment-tracker.md) and [`loan_master`](loan-master.md), compare against the prior period stored here, and write a new row per loan. See [coverage-and-gaps](../../coverage-and-gaps.md).

## Sample data

Four prior-quarter (`2026-03-31`) rows are seeded to test movement reporting — e.g. `LN5000011237` was `SUBSTANDARD` and should show as `DOWNGRADED` to `DOUBTFUL` this quarter (`00_dml_load_sample_schema.sql` lines 210-217). See [sample data](../dml-sample-data.md).
