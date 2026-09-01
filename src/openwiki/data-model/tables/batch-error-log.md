---
type: Table
title: "Table: batch_error_log"
description: Generic per-row batch failure log. Written by the monthly interest-credit program to record account-level errors without aborting the batch.
resource: 00_ddl_create_schema.sql
tags: [table, batch-error-log, batch-audit]
---

# Table: `batch_error_log`

Generic audit table for per-entity failures inside batch jobs. Defined at `00_ddl_create_schema.sql` lines 99-106. It is the mechanism by which a batch can record that a single row failed and keep processing the rest.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `log_id` | `NUMBER` | NOT NULL | Primary key. Populated from sequence `seq_log_id`. |
| `batch_name` | `VARCHAR2(50)` | NOT NULL | Name of the batch that logged the error (e.g. `'MONTHLY_INTEREST_CREDIT'`). |
| `entity_key` | `VARCHAR2(50)` | nullable | Identifier of the failing entity (e.g. the account number). |
| `error_message` | `VARCHAR2(1000)` | nullable | The captured `SQLERRM` text. |
| `log_date` | `DATE` | default `SYSDATE` | When the error was logged. |

## Constraints

- `pk_batch_error_log` PRIMARY KEY (`log_id`) — ENABLED, VALIDATED.

## Programs that read or write it

- [04 `sp_process_monthly_interest_credit`](../../programs/04-monthly-interest-credit.md): in its inner exception handler, inserts a row with `batch_name = 'MONTHLY_INTEREST_CREDIT'`, `entity_key = account_number`, and `error_message = SQLERRM`, then continues the loop. This is the concrete realisation of the per-row error-isolation rule ([BR-11](../../business-rules.md)).

No present program reads this table.
