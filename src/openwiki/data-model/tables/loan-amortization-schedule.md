---
type: Table
title: "Table: loan_amortization_schedule"
description: Per-installment EMI breakdown (opening balance, interest, principal, closing balance) - the output of the absent amortization program #7. Orphan in this checkout.
resource: 00_ddl_create_schema.sql
tags: [table, loan-amortization-schedule, loans, orphan]
---

# Table: `loan_amortization_schedule`

Per-installment amortization breakdown for a loan. Defined at `00_ddl_create_schema.sql` lines 161-173. The DDL header comment states it is the **"output of program #7"** — the amortization-schedule generator, which is not present in this checkout.

## Columns

| Column | Type | Nullability | Meaning |
| --- | --- | --- | --- |
| `loan_account_number` | `VARCHAR2(20)` | NOT NULL | Loan the row belongs to; foreign key to [`loan_master`](loan-master.md). Part of PK. |
| `installment_no` | `NUMBER` | NOT NULL | Installment sequence number. Part of PK. |
| `due_date` | `DATE` | NOT NULL | Date the installment is due. |
| `opening_balance` | `NUMBER(18,2)` | NOT NULL | Principal outstanding at the start of the period. |
| `emi_amount` | `NUMBER(18,2)` | NOT NULL | Equated monthly installment amount. |
| `interest_component` | `NUMBER(18,2)` | NOT NULL | Portion of the EMI that is interest. |
| `principal_component` | `NUMBER(18,2)` | NOT NULL | Portion of the EMI that reduces principal. |
| `closing_balance` | `NUMBER(18,2)` | NOT NULL | Principal outstanding at the end of the period. |

## Constraints

- `pk_loan_amort_sched` PRIMARY KEY (`loan_account_number`, `installment_no`) — ENABLED, VALIDATED.
- `fk_amort_sched_loan` FOREIGN KEY (`loan_account_number`) → [`loan_master`](loan-master.md) — ENABLED, VALIDATED.

## Programs that read or write it

**None in this checkout.** It is the output table of the absent amortization program (#7). It is an **orphan** here and receives no sample data. See [coverage-and-gaps](../../coverage-and-gaps.md).
