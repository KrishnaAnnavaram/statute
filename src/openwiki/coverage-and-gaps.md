---
type: Gaps
title: Coverage and Gaps
description: Honest report of what the source does not contain - orphan tables, hard-coded constants where reference tables exist, code-only validations bypassable by direct SQL, and the absent programs 06-10 the schema references.
tags: [coverage, gaps, orphan-tables, missing-programs, reimplementation]
---

# Coverage and Gaps

This page reports honestly on what the on-disk source does **not** contain. It is essential for anyone reimplementing this system, because the schema was built for ten programs but only five ([01](programs/01-simple-interest.md)-[05](programs/05-fund-transfer.md)) are present in this checkout.

## Tables no present program reads or writes (orphans)

The following tables are created by the [DDL](data-model/ddl-schema.md) and seeded (or not) by the [DML](data-model/dml-sample-data.md), but **no present program** touches them. Each is owned by an absent program:

| Table | Owning absent program (per DDL/DML comment) | Anchor |
| --- | --- | --- |
| [`batch_control_log`](data-model/tables/batch-control-log.md) | Generic batch control; unused by the one present batch (04) | `00_ddl_create_schema.sql:108-120` |
| [`loan_amortization_schedule`](data-model/tables/loan-amortization-schedule.md) | #7 amortization (output) | `00_ddl_create_schema.sql:159-173` |
| [`interest_rate_master`](data-model/tables/interest-rate-master.md) | #8 EOD accrual (input) | `00_ddl_create_schema.sql:176-186` |
| [`interest_accrual_ledger`](data-model/tables/interest-accrual-ledger.md) | #8 EOD accrual (output) | `00_ddl_create_schema.sql:188-201` |
| [`holiday_calendar`](data-model/tables/holiday-calendar.md) | #8 EOD accrual (holiday skip) | `00_ddl_create_schema.sql:204-211` |
| [`fraud_score_results`](data-model/tables/fraud-score-results.md) | #9 fraud scoring (output) | `00_ddl_create_schema.sql:213-224` |
| [`loan_rate_reset_history`](data-model/tables/loan-rate-reset-history.md) | #7 amortization (input) | `00_ddl_create_schema.sql:148-156` |
| [`loan_repayment_tracker`](data-model/tables/loan-repayment-tracker.md) | #10 NPA classification (input) | `00_ddl_create_schema.sql:229-238` |
| [`npa_classification_history`](data-model/tables/npa-classification-history.md) | #10 NPA classification (output) | `00_ddl_create_schema.sql:243-255` |
| [`npa_provisioning_summary`](data-model/tables/npa-provisioning-summary.md) | #10 NPA classification (roll-up) | `00_ddl_create_schema.sql:260-266` |

Additionally, [`customers`](data-model/tables/customers.md) is referenced by the present programs only indirectly (through foreign keys); no present program reads or writes it.

## Hard-coded constants where a reference table exists for the same purpose

- **Monthly interest rates.** [`sp_process_monthly_interest_credit`](programs/04-monthly-interest-credit.md) hard-codes tiered rates `3.0/3.5/4.0/4.5` at slab boundaries `100000/1000000/10000000` (`04_medium_process_monthly_interest_credit.sql:38-46`, [BR-12](business-rules.md)). A reference table for exactly this purpose — [`interest_rate_master`](data-model/tables/interest-rate-master.md) — exists (`00_ddl_create_schema.sql:178-186`) and is seeded (`00_dml_load_sample_schema.sql:153-172`) with **different** slab boundaries and rates. The program does not read it. This is the clearest constant-vs-reference-table divergence in the codebase.
- **Minimum-balance thresholds.** [`sp_check_minimum_balance`](programs/03-minimum-balance.md) hard-codes per-type minimums (`1000/10000/0/5000/25000`) in a `CASE` (`03_simple_check_minimum_balance.sql:27-35`, [BR-10](business-rules.md)). There is **no** reference table for minimum balances; a reimplementation would need one.
- **Dormancy threshold and day-count basis.** The `365`-day dormancy threshold ([BR-07](business-rules.md)) and the `360/365` day-count basis ([BR-05](business-rules.md), [BR-06](business-rules.md), [BR-13](business-rules.md)) are literals in code with no configuration table.

## Validations performed in code with no matching database constraint

These are bypassable by direct SQL because only procedural logic enforces them (the database would accept a violating row/update):

| Business intent | Enforced only in | No DB constraint for |
| --- | --- | --- |
| Both accounts ACTIVE before transfer ([BR-19](business-rules.md)) | [05](programs/05-fund-transfer.md) | Nothing prevents a direct `UPDATE accounts SET balance` on a non-active account |
| Sufficient source balance ([BR-18](business-rules.md)) | [05](programs/05-fund-transfer.md) | No CHECK forbids a debit driving `balance` negative (and `OVERDRAFT` accounts are intentionally negative) |
| Daily transfer limit ([BR-20](business-rules.md)) | [05](programs/05-fund-transfer.md) | `daily_transfer_limit` is a column, not an enforced ceiling |
| Same-account guard ([BR-17](business-rules.md)) | [05](programs/05-fund-transfer.md) | No constraint |
| Savings-only, active-only crediting ([BR-14](business-rules.md)) | [04](programs/04-monthly-interest-credit.md) | No constraint |
| `account_type` / `txn_type` value domains | convention comments only | No CHECK constraint (unlike `account_status`, which has [BR-01](business-rules.md)) |

The one business-domain value rule the **database** does enforce is `ck_accounts_status` ([BR-01](business-rules.md)).

## Gaps in file numbering — the absent programs 06-10

The filenames run `01`-`05`, but the DDL/DML repeatedly reference programs `06`-`10`. Their responsibilities are inferable **only from those comments** — the program source is not in this checkout, so the following are labelled inferences, not verified behaviour:

| # | Inferred responsibility | Owned tables | Source anchor |
| --- | --- | --- | --- |
| 06 | Account statement generation | (reads history; no dedicated output table) | `00_dml_load_sample_schema.sql:39,74` |
| 07 | Loan amortization schedule generation | [`loan_amortization_schedule`](data-model/tables/loan-amortization-schedule.md) (out), [`loan_rate_reset_history`](data-model/tables/loan-rate-reset-history.md) (in) | `00_ddl_create_schema.sql:159` |
| 08 | End-of-day interest accrual, skipping holidays | [`interest_accrual_ledger`](data-model/tables/interest-accrual-ledger.md) (out), [`interest_rate_master`](data-model/tables/interest-rate-master.md) + [`holiday_calendar`](data-model/tables/holiday-calendar.md) (in) | `00_ddl_create_schema.sql:176,188,204` |
| 09 | Transaction fraud scoring (velocity, geo-mismatch, impossible travel, amount anomaly, first-time beneficiary, odd-hour) | [`fraud_score_results`](data-model/tables/fraud-score-results.md) (out) | `00_ddl_create_schema.sql:213`; `00_dml_load_sample_schema.sql:66-120` |
| 10 | NPA classification and provisioning with movement reporting | [`npa_classification_history`](data-model/tables/npa-classification-history.md), [`npa_provisioning_summary`](data-model/tables/npa-provisioning-summary.md) (out), [`loan_repayment_tracker`](data-model/tables/loan-repayment-tracker.md) (in) | `00_ddl_create_schema.sql:226-266`; `00_dml_load_sample_schema.sql:184-217` |

The sample data is fully engineered to exercise these absent programs (fraud triggers, NPA DPD buckets, rate resets), so their expected behaviour is testable the moment their source is restored — see [sample data](data-model/dml-sample-data.md).

## What a reimplementation team needs but cannot find here

- The source for programs 06-10 (statements, amortization, EOD accrual, fraud scoring, NPA classification).
- The exact fraud scoring weights and thresholds (only trigger scenarios are described).
- The NPA DPD-to-bucket boundaries as executable logic (only the expected mapping is in DML comments).
- The amortization/EMI formula (only the output columns exist).
- Any wiring that would make [04](programs/04-monthly-interest-credit.md) read [`interest_rate_master`](data-model/tables/interest-rate-master.md) instead of hard-coded rates.

## Project-context note

Git history (a README/docs on the branch, not present on disk) frames these files as the sample input corpus for a "STATUTE" PL/SQL-to-BRD pipeline. That framing explains the complexity grading and the 06-10 references but is context, not on-disk content; it is recorded here and in the [overview](overview.md) as a labelled inference.
