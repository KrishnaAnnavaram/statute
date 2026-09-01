---
type: Table
title: "Table: npa_provisioning_summary"
description: Quarter-end control total - total accounts and total provisioning across all loans. Output of the absent NPA program #10. Orphan in this checkout.
resource: 00_ddl_create_schema.sql
tags: [table, npa-provisioning-summary, program-output, orphan]
---

# Table: `npa_provisioning_summary`

Quarter-end control-total table for NPA provisioning. Defined at `00_ddl_create_schema.sql` lines 260-266. The DDL header comment describes it as the **"quarter-end control total, output of #10"** — the absent NPA-classification batch.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `quarter_end_date` | `DATE` | NOT NULL | Primary key; the quarter-end the summary covers. |
| `total_accounts` | `NUMBER` | nullable | Count of loans classified in the run. |
| `total_provisioning_amount` | `NUMBER(20,2)` | nullable | Sum of provisioning across all classified loans. |
| `run_timestamp` | `TIMESTAMP` | default `SYSTIMESTAMP` | When the summary was produced. |

## Constraints

- `pk_npa_provisioning_summary` PRIMARY KEY (`quarter_end_date`) — ENABLED, VALIDATED. It is keyed only on the quarter-end date; there is no link to individual loans (the per-loan detail lives in [`npa_classification_history`](npa-classification-history.md)).

## Programs that read or write it

**None in this checkout.** It is a roll-up output of the absent NPA program (#10). It is an **orphan** here and receives no sample data. See [coverage-and-gaps](../../coverage-and-gaps.md).
