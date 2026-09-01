---
type: Table
title: "Table: loan_master"
description: One row per loan account - principal, outstanding balance, rate, tenure, collateral, and restructure flag. Parent of the loan history/schedule/tracker tables.
resource: 00_ddl_create_schema.sql
tags: [table, loan-master, loans]
---

# Table: `loan_master`

Master record for each loan account. Defined at `00_ddl_create_schema.sql` lines 125-143. It is the parent of the rate-reset, amortization, and repayment-tracker tables and feeds the absent NPA-classification program (#10).

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `loan_account_number` | `VARCHAR2(20)` | NOT NULL | Primary key (sample form `LN5000011234`). |
| `customer_id` | `VARCHAR2(20)` | NOT NULL | Owning customer; foreign key to [`customers`](customers.md). |
| `loan_type` | `VARCHAR2(20)` | NOT NULL | `HOME_LOAN`, `AUTO_LOAN`, `PERSONAL_LOAN`, `EDUCATION_LOAN`, `MORTGAGE` (documented convention, not a CHECK). |
| `principal_amount` | `NUMBER(18,2)` | NOT NULL | Original disbursed principal. |
| `outstanding_principal` | `NUMBER(18,2)` | NOT NULL | Current principal outstanding; feeds provisioning. |
| `annual_interest_rate` | `NUMBER(6,3)` | NOT NULL | Current annual rate (percent). |
| `tenure_months` | `NUMBER` | NOT NULL | Loan tenure in months. |
| `disbursement_date` | `DATE` | NOT NULL | Date the loan was disbursed. |
| `rate_reset_frequency_months` | `NUMBER` | default `0` | Reset cadence; `0` means a fixed-rate loan. |
| `collateral_value` | `NUMBER(18,2)` | default `0` | Security value; drives collateral-cover percentage in NPA provisioning. |
| `is_restructured` | `VARCHAR2(1)` | default `'N'` | `Y`/`N` restructure flag; a `Y` within 12 months forces a `SPECIAL_MENTION` override in the absent NPA program. |
| `restructure_date` | `DATE` | nullable | Date of restructure, if any. |
| `loan_status` | `VARCHAR2(20)` | default `'ACTIVE'` | Loan lifecycle status. |

## Constraints

- `pk_loan_master` PRIMARY KEY (`loan_account_number`) — ENABLED, VALIDATED.
- `fk_loan_customer` FOREIGN KEY (`customer_id`) → [`customers`](customers.md) — ENABLED, VALIDATED.

## Child tables

- [`loan_rate_reset_history`](loan-rate-reset-history.md) via `fk_rate_reset_loan`.
- [`loan_amortization_schedule`](loan-amortization-schedule.md) via `fk_amort_sched_loan`.
- [`loan_repayment_tracker`](loan-repayment-tracker.md) via `fk_repay_tracker_loan`.
- [`npa_classification_history`](npa-classification-history.md) by `loan_account_number` (INFERRED — no declared FK).

## Programs that read or write it

**None in this checkout.** All loan logic belongs to the absent programs (#7 amortization, #10 NPA classification). See [coverage-and-gaps](../../coverage-and-gaps.md).

## Sample data

Five loans are seeded (`00_dml_load_sample_schema.sql` lines 130-139): a fixed-rate home loan, a floating-rate auto loan, a restructured personal loan, a far-past-due mortgage, and a current education loan — chosen to exercise every NPA bucket the absent program #10 would classify. See [sample data](../dml-sample-data.md).
