---
type: Table
title: "Table: batch_control_log"
description: Generic batch-run control table (run id, timings, counts, control totals). Defined in the DDL but not read or written by any program present in this checkout.
resource: 00_ddl_create_schema.sql
tags: [table, batch-control-log, batch-audit, orphan]
---

# Table: `batch_control_log`

Generic control-record table for batch runs — one row per run capturing timings, record counts, and a control total. Defined at `00_ddl_create_schema.sql` lines 108-120.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `batch_run_id` | `NUMBER` | NOT NULL | Primary key. Intended to come from sequence `seq_batch_run_id`. |
| `batch_name` | `VARCHAR2(50)` | NOT NULL | Name of the batch job. |
| `business_date` | `DATE` | NOT NULL | Business (accounting) date the run covers. |
| `start_time` | `TIMESTAMP` | nullable | Run start timestamp. |
| `end_time` | `TIMESTAMP` | nullable | Run end timestamp. |
| `status` | `VARCHAR2(20)` | default `'RUNNING'` | Run status (e.g. `RUNNING`, and by convention success/failure states). |
| `records_processed` | `NUMBER` | nullable | Count of successfully processed records. |
| `records_failed` | `NUMBER` | nullable | Count of failed records. |
| `control_total` | `NUMBER(20,2)` | nullable | Reconciliation total for the run. |
| `error_message` | `VARCHAR2(1000)` | nullable | Terminal error message if the run failed. |

## Constraints

- `pk_batch_control_log` PRIMARY KEY (`batch_run_id`) — ENABLED, VALIDATED.

## Programs that read or write it

**None in this checkout.** Sequence `seq_batch_run_id` exists solely to feed this table but has no present consumer. The batch program that is present, [04](../../programs/04-monthly-interest-credit.md), reports its counts through `OUT` parameters and does not write a control row here. This table is an **orphan** in the current repository; see [coverage-and-gaps](../../coverage-and-gaps.md).
