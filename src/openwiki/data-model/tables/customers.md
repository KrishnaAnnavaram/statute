---
type: Table
title: "Table: customers"
description: Master record for each banking customer - identity, KYC status, and relationship start date. Parent of accounts and loan_master.
resource: 00_ddl_create_schema.sql
tags: [table, customers, core-banking]
---

# Table: `customers`

Master identity record for each banking customer. Defined at `00_ddl_create_schema.sql` lines 40-48. It is the top of both the account and loan hierarchies via declared foreign keys.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `customer_id` | `VARCHAR2(20)` | NOT NULL | Primary key. Business identifier for the customer (sample form `CUST00001`). |
| `customer_name` | `VARCHAR2(150)` | NOT NULL | Full legal name of the customer. |
| `date_of_birth` | `DATE` | nullable | Customer's date of birth. |
| `registered_country` | `VARCHAR2(3)` | NOT NULL | ISO country code of registration (e.g. `IND`, `GBR`, `USA`). Used by the absent fraud program (#9) to detect geo-mismatch. |
| `kyc_status` | `VARCHAR2(20)` | default `'VERIFIED'` | Know-Your-Customer verification state. |
| `customer_since_date` | `DATE` | default `SYSDATE` | Date the customer relationship began. |

## Constraints

- `pk_customers` PRIMARY KEY (`customer_id`) — ENABLED, VALIDATED (no disable/novalidate declared).

## Relationships

- Parent of [`accounts`](accounts.md) via `fk_accounts_customer` (declared).
- Parent of [`loan_master`](loan-master.md) via `fk_loan_customer` (declared).

## Programs that read or write it

No present program reads or writes `customers` directly; the five programs on disk operate on [`accounts`](accounts.md), [`transaction_ledger`](transaction-ledger.md), and [`batch_error_log`](batch-error-log.md). `registered_country` is consumed only by the absent fraud program (#9). See [coverage-and-gaps](../../coverage-and-gaps.md).

## Sample data

Eight customers are seeded (`00_dml_load_sample_schema.sql` lines 19-34), spanning countries `IND`, `GBR`, `SGP`, `ARE`, `USA`, `DEU`, all `kyc_status = 'VERIFIED'`. See [sample data](../dml-sample-data.md).
