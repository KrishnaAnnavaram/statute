---
type: Table
title: "Table: fraud_score_results"
description: Per-transaction fraud risk scores and reasons - output of the absent fraud-scoring program #9. Orphan in this checkout; sample transaction data is engineered to trigger it.
resource: 00_ddl_create_schema.sql
tags: [table, fraud-score-results, program-output, orphan]
---

# Table: `fraud_score_results`

Per-transaction fraud risk scores. Defined at `00_ddl_create_schema.sql` lines 216-224. The DDL header comment states it is the **"output of program #9"** — the absent fraud-scoring engine.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `txn_id` | `NUMBER` | NOT NULL | Primary key; the scored transaction (conceptually [`transaction_ledger.txn_id`](transaction-ledger.md), INFERRED — no FK). |
| `account_number` | `VARCHAR2(20)` | NOT NULL | Account of the scored transaction (INFERRED link to [`accounts`](accounts.md); no FK). |
| `txn_amount` | `NUMBER(18,2)` | NOT NULL | Amount of the scored transaction. |
| `risk_score` | `NUMBER(5,0)` | default `0` | Computed risk score. |
| `risk_reasons` | `VARCHAR2(4000)` | nullable | Human-readable reasons contributing to the score. |
| `scored_date` | `TIMESTAMP` | default `SYSTIMESTAMP` | When the transaction was scored. |

## Constraints

- `pk_fraud_score_results` PRIMARY KEY (`txn_id`) — ENABLED, VALIDATED. There is **no** foreign key to `transaction_ledger` or `accounts`; those links are INFERRED.

## Programs that read or write it

**None in this checkout.** It is the output table of the absent fraud program (#9). It is an **orphan** here and receives no sample data — instead, the [`transaction_ledger`](transaction-ledger.md) sample data is deliberately shaped to trigger the six fraud rules (velocity, geo-mismatch, impossible travel, amount anomaly, first-time beneficiary, odd-hour) that #9 would score. See [sample data](../dml-sample-data.md) and [coverage-and-gaps](../../coverage-and-gaps.md).
