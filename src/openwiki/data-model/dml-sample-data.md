---
type: DataModel
title: Sample Data Loader
description: 00_dml_load_sample_schema.sql - the seed dataset engineered to exercise the branch logic of every program, including the absent 06-10, keyed to the reference date 30-JUN-2026.
resource: 00_dml_load_sample_schema.sql
tags: [data-model, dml, sample-data, fixtures]
---

# Sample Data Loader

Source file: [`00_dml_load_sample_schema.sql`](../../00_dml_load_sample_schema.sql). This script seeds every table created by the [DDL](ddl-schema.md). The data is deliberately shaped to exercise the branching logic in each of the ten programs the suite envisions — including the [absent programs 06-10](../coverage-and-gaps.md). It ends with a `COMMIT`.

## Run order and reference date

- **Run AFTER** `00_ddl_create_schema.sql` and AFTER compiling the programs (file header lines 9-12). Some DML rows deliberately **simulate output the batch programs would otherwise generate** (e.g. prior-quarter NPA classifications), giving a baseline dataset to diff against.
- **Reference date: `30-JUN-2026`** (file header line 13) — a quarter-end / month-end date. All dormancy, DPD, and quarter-boundary fixtures are calibrated to this date.

## What each dataset is engineered to trigger

| Table | Rows | Exercises |
| --- | --- | --- |
| [`customers`](tables/customers.md) | 8 (L19-34) | Multiple `registered_country` values for the fraud geo-mismatch rule (#9). |
| [`accounts`](tables/accounts.md) | 12 (L41-64) | Dormancy ([02](../programs/02-dormant-account-status.md)), below-minimum-balance ([03](../programs/03-minimum-balance.md)), tiered slabs ([04](../programs/04-monthly-interest-credit.md)), transfer validation ([05](../programs/05-fund-transfer.md)). |
| [`transaction_ledger`](tables/transaction-ledger.md) | many (L75-120) | Fraud triggers for the absent #9. |
| [`loan_master`](tables/loan-master.md) | 5 (L130-139) | Every NPA bucket / restructure override for the absent #10, and a floating-rate loan for #7. |
| [`loan_rate_reset_history`](tables/loan-rate-reset-history.md) | 2 (L144-147) | Floating-rate resets on `LN5000011235`. |
| [`interest_rate_master`](tables/interest-rate-master.md) | 9 (L153-172) | Product/slab rate lookup for the absent #8. |
| [`holiday_calendar`](tables/holiday-calendar.md) | 3 (L177-182) | Holiday skip for the absent #8. |
| [`loan_repayment_tracker`](tables/loan-repayment-tracker.md) | 5 (L194-203) | DPD spanning every NPA bucket for #10. |
| [`npa_classification_history`](tables/npa-classification-history.md) | 4 (L210-217) | Prior-quarter baseline for #10 movement reporting. |

## Account fixtures and the branches they exercise

- `AC1000234570` (`CURRENT_REGULAR`, balance `3200`) — below the `5000` minimum-balance requirement for its type ([03](../programs/03-minimum-balance.md)); also carries a **velocity burst** of six `TRANSFER_OUT` rows within ~7 minutes on `2026-06-28` (L85-96) for the fraud program.
- `AC1000234571` and `AC1000234577` (`DORMANT`, `last_transaction_date` in 2024) — dormancy fixtures for [02](../programs/02-dormant-account-status.md).
- `AC1000234575` (`SAVINGS_REGULAR`, balance `6,500,000`) — top tiered-interest slab for [04](../programs/04-monthly-interest-credit.md); also a **large first-time-beneficiary** transfer to `BENEF9001` (L115-116).
- `AC1000234576` (`SAVINGS_PREMIUM`, customer registered `USA`) — **geo-mismatch + impossible travel**: withdrawals from `ARE` then `GBR` 40 minutes apart (L99-102).
- `AC1000234569` — **amount anomaly**: a `25,000` withdrawal against a ~`2,000` historical average (L104-112).
- `AC1000234574` (`CURRENT_PREMIUM`) — **odd-hour high-value** transfer at `02:15` (L118-120).

## Loan fixtures and the NPA buckets they exercise

The DML comment block at lines 184-192 spells out the intended mapping consumed by the absent NPA program (#10):

| Loan | DPD (as of `2026-06-30`) | Expected classification |
| --- | --- | --- |
| `LN5000011234` | 0 | STANDARD |
| `LN5000011235` | 45 | SPECIAL_MENTION |
| `LN5000011236` | 20 | STANDARD by DPD, but restructured within 12 months → overridden to SPECIAL_MENTION |
| `LN5000011237` | 400 | DOUBTFUL (was SUBSTANDARD last quarter → DOWNGRADED) |
| `LN5000011238` | 650 | LOSS |

## What depends on this file

The DML is the shared baseline for validating all five present programs (and the absent ones once restored). Because the fraud, accrual, amortization, and NPA fixtures target programs that are not in this checkout, they currently sit unread; see [coverage-and-gaps](../coverage-and-gaps.md).
